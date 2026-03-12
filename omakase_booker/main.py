"""Main orchestrator for Omakase auto-booking.

Workflow:
  1. Google Calendar check → identify days with free slots at preferred times
  2. Merge with user-specified candidate dates
  3. Omakase availability check → detect open time, check slots
  4. Matching → candidate dates × Omakase slots → book immediately
  5. Fast polling (0.5s) around per-restaurant reservation open times
  6. Complete payment after securing a slot
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

from .calendar_checker import get_available_dates, create_booking_event
from .config import Config, RestaurantTarget
from .notifier import notify_failure, notify_success
from .omakase_client import OmakaseClient, OmakaseBookingError

logger = logging.getLogger(__name__)

# Track successful bookings to avoid duplicates
_booked: set[tuple[str, str, str]] = set()  # (restaurant_url, date, time)

# Cache detected open times per restaurant URL
_open_times: dict[str, str] = {}  # restaurant_url -> "YYYY-MM-DDTHH:MM" or "HH:MM"

# Reference to current config (set in run_scheduler)
_current_config: Config | None = None


def _build_candidate_dates(
    config: Config,
    restaurant: RestaurantTarget,
) -> list[tuple[datetime, list[str]]]:
    """Build list of candidate (date, times) from user config + Google Calendar.

    Priority:
      1. User-specified candidate_dates (always included)
      2. Google Calendar free slots (if no candidate_dates, or as supplement)

    Returns:
        List of (date_datetime, matching_preferred_times).
    """
    candidates: dict[str, list[str]] = {}

    # User-specified candidate dates
    for date_str in restaurant.candidate_dates:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            candidates[date_str] = list(restaurant.preferred_times)
        except ValueError:
            logger.warning("Invalid candidate date format: %s (expected YYYY-MM-DD)", date_str)

    # Google Calendar free slots (supplement or primary source)
    if not restaurant.candidate_dates:
        try:
            cal_available = get_available_dates(config, restaurant.preferred_times)
            for cal_date, cal_times in cal_available:
                date_str = cal_date.strftime("%Y-%m-%d")
                if date_str not in candidates:
                    candidates[date_str] = cal_times
                else:
                    # Merge times (calendar confirms those user-specified dates are free)
                    for t in cal_times:
                        if t not in candidates[date_str]:
                            candidates[date_str].append(t)
        except Exception:
            logger.exception("Failed to check Google Calendar")

    result = []
    for date_str in sorted(candidates.keys()):
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        result.append((dt, candidates[date_str]))

    return result


async def try_book_restaurant(
    client: OmakaseClient,
    restaurant: RestaurantTarget,
    candidate_dates: list[tuple[datetime, list[str]]],
) -> bool:
    """Try to book a restaurant on any matching date/time.

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

    # Match Omakase slots with candidate dates
    for cal_date, cal_times in candidate_dates:
        date_str = cal_date.strftime("%Y-%m-%d")

        for slot in omakase_slots:
            slot_date = slot.get("date")
            slot_time = slot.get("time")

            if not slot_date or not slot_time:
                continue

            if slot_date != date_str:
                continue
            if slot_time not in cal_times:
                continue

            # Check if already booked
            key = (restaurant.omakase_url, slot_date, slot_time)
            if key in _booked:
                continue

            # Try to book (includes payment)!
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
                    # Add to Google Calendar
                    try:
                        create_booking_event(
                            _current_config,
                            restaurant.name,
                            slot_date,
                            slot_time,
                            restaurant.party_size,
                        )
                    except Exception:
                        logger.exception("Failed to create calendar event")
                    return True
                else:
                    notify_failure(restaurant.name, f"Slot {slot_date} {slot_time} - booking/payment failed")
            except Exception:
                logger.exception("Error booking %s", restaurant.name)
                notify_failure(restaurant.name, f"Slot {slot_date} {slot_time} - exception")

    return False


async def detect_open_times(client: OmakaseClient, config: Config):
    """Detect reservation open times for all target restaurants."""
    for restaurant in config.target_restaurants:
        if not restaurant.omakase_url:
            continue
        if restaurant.omakase_url in _open_times:
            continue

        try:
            open_time = await client.detect_reservation_open_time(restaurant)
            if open_time:
                _open_times[restaurant.omakase_url] = open_time
                logger.info(
                    "Restaurant %s: reservation opens at %s",
                    restaurant.name,
                    open_time,
                )
        except Exception:
            logger.exception("Failed to detect open time for %s", restaurant.name)


def _is_near_any_open_time(config: Config) -> bool:
    """Check if we're within the fast-polling window of any restaurant's open time."""
    now = datetime.now()
    window = timedelta(minutes=config.fast_poll_window_minutes)

    for restaurant in config.target_restaurants:
        url = restaurant.omakase_url
        open_time_str = _open_times.get(url)

        if open_time_str:
            try:
                if "T" in open_time_str:
                    # Full datetime: "YYYY-MM-DDTHH:MM"
                    open_dt = datetime.strptime(open_time_str, "%Y-%m-%dT%H:%M")
                else:
                    # Time only: "HH:MM" — assume today
                    hour, minute = map(int, open_time_str.split(":"))
                    open_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

                if abs((now - open_dt).total_seconds()) < window.total_seconds():
                    return True
            except ValueError:
                continue

    return False


async def run_booking_cycle(config: Config):
    """Run one complete booking cycle for all restaurants."""
    logger.info("Starting booking cycle at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    client = OmakaseClient(config)
    try:
        await client.start()

        # Step 1: Detect reservation open times (cached after first detection)
        await detect_open_times(client, config)

        for restaurant in config.target_restaurants:
            if not restaurant.omakase_url:
                continue

            # Handle lottery-based restaurants
            if restaurant.booking_mode == "lottery":
                logger.info("Lottery mode for %s", restaurant.name)
                booking_url = await client.check_lottery_result(restaurant)
                if booking_url:
                    candidate_dates = _build_candidate_dates(config, restaurant)
                    if candidate_dates:
                        await try_book_restaurant(client, restaurant, candidate_dates)
                else:
                    await client.enter_lottery(restaurant)
                continue

            # First-come-first-served mode
            # Step 2: Build candidate dates (user-specified + calendar)
            logger.info("Building candidate dates for %s...", restaurant.name)
            candidate_dates = _build_candidate_dates(config, restaurant)

            if not candidate_dates:
                logger.info("No candidate dates for %s", restaurant.name)
                continue

            logger.info(
                "%d candidate dates for %s",
                len(candidate_dates),
                restaurant.name,
            )

            # Steps 3-6: Check Omakase, match, book, pay
            await try_book_restaurant(client, restaurant, candidate_dates)

    except OmakaseBookingError:
        logger.exception("Omakase login/session error")
    finally:
        await client.close()

    logger.info("Booking cycle complete.")


async def run_scheduler(config: Config):
    """Main scheduling loop.

    - Near a restaurant's reservation open time: poll rapidly (0.5s)
    - Otherwise: poll at the configured interval
    """
    global _current_config
    _current_config = config
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
        if _is_near_any_open_time(config):
            interval = config.fast_poll_interval_seconds
            logger.info("Near reservation open time - fast polling (%.1fs)", interval)
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

    print("=" * 60)
    print("  Omakase Auto-Booker")
    print("=" * 60)
    print()
    print("  WARNING: Omakase (omakase.in) の利用規約では")
    print("  自動操作・ボットが禁止されています。")
    print("  本ツールの使用は自己責任です。")
    print("  アカウント停止のリスクがあります。")
    print()
    print(f"  Monitoring {len(config.target_restaurants)} restaurant(s)")
    for r in config.target_restaurants:
        mode = "lottery" if r.booking_mode == "lottery" else "first-come"
        dates_info = f", dates: {r.candidate_dates}" if r.candidate_dates else ""
        print(f"    - {r.name} ({mode}{dates_info})")
    print(f"  Fast poll interval: {config.fast_poll_interval_seconds}s")
    print(f"  Normal poll interval: {config.check_interval_seconds}s")
    print()

    asyncio.run(run_scheduler(config))


if __name__ == "__main__":
    main()
