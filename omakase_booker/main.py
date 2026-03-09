"""Main orchestrator for Omakase auto-booking.

Workflow:
  1. Load configuration
  2. Check Google Calendar for free slots
  3. For each target restaurant, check Omakase for availability
  4. If a matching slot is found (free in calendar + available on Omakase),
     attempt to book it
  5. Repeat at configured intervals, especially around reservation open times
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

from .calendar_checker import get_available_dates
from .config import Config
from .notifier import notify_failure, notify_success
from .omakase_client import OmakaseClient, OmakaseBookingError

logger = logging.getLogger(__name__)

# Track successful bookings to avoid duplicates
_booked: set[tuple[str, str, str]] = set()  # (restaurant_url, date, time)


async def try_book_restaurant(
    client: OmakaseClient,
    restaurant,
    calendar_available: list[tuple[datetime, list[str]]],
) -> bool:
    """Try to book a restaurant on any available date/time.

    Returns True if a booking was made.
    """
    # Get available slots from Omakase
    try:
        omakase_slots = await client.check_availability(restaurant)
    except Exception:
        logger.exception("Failed to check Omakase availability for %s", restaurant.name)
        return False

    if not omakase_slots:
        logger.info("No available slots on Omakase for %s", restaurant.name)
        return False

    # Match Omakase slots with calendar availability
    for cal_date, cal_times in calendar_available:
        date_str = cal_date.strftime("%Y-%m-%d")

        for slot in omakase_slots:
            slot_date = slot.get("date")
            slot_time = slot.get("time")

            if not slot_date or not slot_time:
                continue

            # Check if this slot matches our calendar availability
            if slot_date != date_str:
                continue
            if slot_time not in cal_times:
                continue

            # Check if already booked
            key = (restaurant.omakase_url, slot_date, slot_time)
            if key in _booked:
                continue

            # Try to book!
            logger.info(
                "Match found! %s on %s at %s",
                restaurant.name,
                slot_date,
                slot_time,
            )
            try:
                success = await client.book_slot(
                    restaurant, slot_date, slot_time
                )
                if success:
                    _booked.add(key)
                    notify_success(restaurant.name, slot_date, slot_time)
                    return True
                else:
                    notify_failure(restaurant.name, f"Slot {slot_date} {slot_time} - booking failed")
            except Exception:
                logger.exception("Error booking %s", restaurant.name)
                notify_failure(restaurant.name, f"Slot {slot_date} {slot_time} - exception")

    return False


async def run_booking_cycle(config: Config):
    """Run one complete booking cycle for all restaurants."""
    logger.info("Starting booking cycle at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    client = OmakaseClient(config)
    try:
        await client.start()

        for restaurant in config.target_restaurants:
            if not restaurant.omakase_url:
                continue

            # Get calendar availability for this restaurant's preferred times
            logger.info("Checking calendar for %s...", restaurant.name)
            try:
                calendar_available = get_available_dates(
                    config, restaurant.preferred_times
                )
            except Exception:
                logger.exception("Failed to check calendar")
                continue

            if not calendar_available:
                logger.info("No free calendar slots for %s", restaurant.name)
                continue

            logger.info(
                "%d available dates in calendar for %s",
                len(calendar_available),
                restaurant.name,
            )

            await try_book_restaurant(client, restaurant, calendar_available)

    except OmakaseBookingError:
        logger.exception("Omakase login/session error")
    finally:
        await client.close()

    logger.info("Booking cycle complete.")


def _is_near_open_time(config: Config, window_minutes: int = 5) -> bool:
    """Check if we're within a window around the reservation open time."""
    now = datetime.now()
    hour, minute = map(int, config.reservation_open_time.split(":"))
    open_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return abs((now - open_time).total_seconds()) < window_minutes * 60


async def run_scheduler(config: Config):
    """Main scheduling loop.

    - Near the reservation open time: poll rapidly (every few seconds)
    - Otherwise: poll at the configured interval
    """
    logger.info("Omakase Auto-Booker started. Monitoring %d restaurants.", len(config.target_restaurants))

    # Handle graceful shutdown
    shutdown = asyncio.Event()

    def handle_signal(*_):
        logger.info("Shutdown signal received.")
        shutdown.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while not shutdown.is_set():
        try:
            await run_booking_cycle(config)
        except Exception:
            logger.exception("Unexpected error in booking cycle")

        # Determine next check interval
        if _is_near_open_time(config):
            interval = 5  # Rapid polling near open time
            logger.info("Near reservation open time - rapid polling (5s)")
        else:
            interval = config.check_interval_seconds
            logger.info("Next check in %d seconds", interval)

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass

    logger.info("Omakase Auto-Booker stopped.")


def main():
    """Entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config_path = Path("config.yaml")
    if not config_path.exists():
        print("Error: config.yaml not found.")
        print("Copy config.example.yaml to config.yaml and fill in your settings.")
        sys.exit(1)

    config = Config.from_yaml(config_path)

    if not config.omakase_email or not config.omakase_password:
        print("Error: Omakase email and password must be set in config.yaml")
        sys.exit(1)

    if not config.target_restaurants:
        print("Error: No target restaurants configured in config.yaml")
        sys.exit(1)

    print(f"Omakase Auto-Booker")
    print(f"  Monitoring {len(config.target_restaurants)} restaurant(s)")
    print(f"  Reservation open time: {config.reservation_open_time} JST")
    print(f"  Check interval: {config.check_interval_seconds}s")
    print()

    asyncio.run(run_scheduler(config))


if __name__ == "__main__":
    main()
