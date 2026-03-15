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

from .approval import request_approval, APPROVED, REJECTED, PENDING
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


async def _try_book_from_slots(
    client: OmakaseClient,
    restaurant: RestaurantTarget,
    candidate_dates: list[tuple[datetime, list[str]]],
    omakase_slots: list[dict],
) -> bool:
    """Try to book using pre-fetched slots. Used by the parallel flow."""
    cancellation_policy = ""
    try:
        cancellation_policy = await client.scrape_cancellation_policy(restaurant)
    except Exception:
        logger.exception("Failed to scrape cancellation policy for %s", restaurant.name)

    for cal_date, cal_times in candidate_dates:
        date_str = cal_date.strftime("%Y-%m-%d")

        for slot in omakase_slots:
            slot_date = slot.get("date")
            slot_time = slot.get("time")
            if not slot_date or not slot_time:
                continue
            if slot_date != date_str or slot_time not in cal_times:
                continue

            key = (restaurant.omakase_url, slot_date, slot_time)
            if key in _booked:
                continue

            logger.info("Match found! %s on %s at %s - reserving...", restaurant.name, slot_date, slot_time)
            try:
                reserved = await client.reserve_slot(restaurant, slot_date, slot_time)
                if not reserved:
                    notify_failure(restaurant.name, f"Slot {slot_date} {slot_time} - reservation failed")
                    continue

                approval = await _request_cli_approval(restaurant, slot_date, slot_time, cancellation_policy)
                if approval != APPROVED:
                    logger.info("Payment %s for %s %s %s",
                                "rejected" if approval == REJECTED else "timed out",
                                restaurant.name, slot_date, slot_time)
                    notify_failure(restaurant.name, f"Slot {slot_date} {slot_time} - approval {approval}")
                    continue

                logger.info("Approval received, completing payment...")
                paid = await client.complete_payment()
                if paid:
                    _booked.add(key)
                    notify_success(restaurant.name, slot_date, slot_time)
                    try:
                        create_booking_event(_current_config, restaurant.name, slot_date, slot_time, restaurant.party_size)
                    except Exception:
                        logger.exception("Failed to create calendar event")
                    return True
                else:
                    notify_failure(restaurant.name, f"Slot {slot_date} {slot_time} - payment failed")
            except Exception:
                logger.exception("Error booking %s", restaurant.name)
                notify_failure(restaurant.name, f"Slot {slot_date} {slot_time} - exception")

    return False


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

    # Scrape cancellation policy once for approval cards
    cancellation_policy = ""
    try:
        cancellation_policy = await client.scrape_cancellation_policy(restaurant)
    except Exception:
        logger.exception("Failed to scrape cancellation policy for %s", restaurant.name)

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

            # Phase 1: Reserve the slot (no payment yet)
            logger.info(
                "Match found! %s on %s at %s - reserving...",
                restaurant.name,
                slot_date,
                slot_time,
            )
            try:
                reserved = await client.reserve_slot(
                    restaurant, slot_date, slot_time
                )
                if not reserved:
                    notify_failure(restaurant.name, f"Slot {slot_date} {slot_time} - reservation failed")
                    continue

                # Phase 2: Request approval via Google Chat
                approval = await _request_cli_approval(
                    restaurant, slot_date, slot_time, cancellation_policy
                )

                if approval != APPROVED:
                    logger.info("Payment %s for %s %s %s",
                                "rejected" if approval == REJECTED else "timed out",
                                restaurant.name, slot_date, slot_time)
                    notify_failure(restaurant.name, f"Slot {slot_date} {slot_time} - approval {approval}")
                    continue

                # Phase 3: Complete payment
                logger.info("Approval received, completing payment...")
                paid = await client.complete_payment()
                if paid:
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
                    notify_failure(restaurant.name, f"Slot {slot_date} {slot_time} - payment failed")
            except Exception:
                logger.exception("Error booking %s", restaurant.name)
                notify_failure(restaurant.name, f"Slot {slot_date} {slot_time} - exception")

    return False


async def _request_cli_approval(
    restaurant: RestaurantTarget,
    slot_date: str,
    slot_time: str,
    cancellation_policy: str = "",
) -> str:
    """Request approval for payment in CLI mode.

    Uses Google Chat if configured, otherwise falls back to CLI prompt.
    """
    config = _current_config
    if not config:
        return APPROVED

    if config.gchat_webhook_url:
        logger.info("Sending approval request to Google Chat...")
        result = await request_approval(
            webhook_url=config.gchat_webhook_url,
            restaurant_name=restaurant.name,
            booking_date=slot_date,
            booking_time=slot_time,
            party_size=restaurant.party_size,
            fee_per_person=config.approval_fee_per_person,
            callback_url=config.gchat_callback_url or None,
            timeout_seconds=config.approval_timeout_seconds,
            cancellation_policy=cancellation_policy,
        )
        if result != PENDING:
            return result
        logger.info("Google Chat approval timed out, falling back to CLI prompt")

    # Fallback: CLI prompt
    total_fee = config.approval_fee_per_person * restaurant.party_size
    print()
    print("=" * 50)
    print("  決済承認依頼")
    print("=" * 50)
    print(f"  レストラン: {restaurant.name}")
    print(f"  日時: {slot_date} {slot_time}")
    print(f"  人数: {restaurant.party_size}名")
    print(f"  手数料: ¥{config.approval_fee_per_person:,} x {restaurant.party_size} = ¥{total_fee:,}")
    if cancellation_policy:
        print()
        print("  【キャンセルポリシー】")
        for line in cancellation_policy.split("\n"):
            print(f"  {line}")
    print()

    answer = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: input("  決済を実行しますか？ (y/n): ").strip().lower(),
    )
    return APPROVED if answer in ("y", "yes") else REJECTED


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


async def _check_restaurant_parallel(
    client: OmakaseClient,
    restaurant: RestaurantTarget,
) -> list[dict]:
    """Check availability for one restaurant using a parallel page.

    Returns available slots, or empty list on error.
    """
    page = await client.create_parallel_page()
    try:
        # Temporarily swap the client's page for our parallel one
        original_page = client._page
        client._page = page

        slots = await client.check_availability(restaurant)
        return slots
    except Exception:
        logger.exception("Parallel check failed for %s", restaurant.name)
        return []
    finally:
        client._page = original_page
        await client.close_parallel_page(page)


async def _check_all_availability(
    client: OmakaseClient,
    restaurants: list[RestaurantTarget],
    max_concurrent: int,
) -> dict[str, list[dict]]:
    """Check availability for multiple restaurants in parallel.

    Uses a semaphore to limit concurrency.

    Returns:
        Dict mapping restaurant URL -> list of available slots.
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results: dict[str, list[dict]] = {}

    async def _check_one(rest: RestaurantTarget):
        async with semaphore:
            logger.info("Parallel check: %s", rest.name)
            slots = await _check_restaurant_parallel(client, rest)
            results[rest.omakase_url] = slots

    await asyncio.gather(*[_check_one(r) for r in restaurants])
    return results


async def run_booking_cycle(config: Config) -> bool:
    """Run one complete booking cycle for all restaurants.

    Uses parallel browser contexts to check availability concurrently,
    then processes matches sequentially (for booking/payment).

    Returns True if at least one booking was made.
    """
    logger.info("Starting booking cycle at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    any_booked = False
    client = OmakaseClient(config)
    try:
        await client.start()

        # Step 1: Detect reservation open times (cached after first detection)
        await detect_open_times(client, config)

        # Separate lottery vs first-come restaurants
        lottery_restaurants = []
        first_come_restaurants = []
        for restaurant in config.target_restaurants:
            if not restaurant.omakase_url:
                continue
            if restaurant.booking_mode == "lottery":
                lottery_restaurants.append(restaurant)
            else:
                first_come_restaurants.append(restaurant)

        # Handle lottery restaurants (sequential — each needs its own interaction)
        for restaurant in lottery_restaurants:
            logger.info("Lottery mode for %s", restaurant.name)
            booking_url = await client.check_lottery_result(restaurant)
            if booking_url:
                candidate_dates = _build_candidate_dates(config, restaurant)
                if candidate_dates:
                    if await try_book_restaurant(client, restaurant, candidate_dates):
                        any_booked = True
            else:
                await client.enter_lottery(restaurant)

        # First-come restaurants: check availability in parallel
        if first_come_restaurants:
            # Build candidate dates for all restaurants upfront
            restaurant_candidates: dict[str, list[tuple[datetime, list[str]]]] = {}
            for restaurant in first_come_restaurants:
                candidates = _build_candidate_dates(config, restaurant)
                if candidates:
                    restaurant_candidates[restaurant.omakase_url] = candidates
                    logger.info("%d candidate dates for %s", len(candidates), restaurant.name)
                else:
                    logger.info("No candidate dates for %s", restaurant.name)

            bookable = [r for r in first_come_restaurants if r.omakase_url in restaurant_candidates]

            if bookable:
                # Parallel availability check
                max_concurrent = min(config.max_concurrent_checks, len(bookable))
                logger.info(
                    "Checking %d restaurants in parallel (max %d concurrent)...",
                    len(bookable), max_concurrent,
                )
                all_slots = await _check_all_availability(client, bookable, max_concurrent)

                # Process matches sequentially (booking requires the main page)
                for restaurant in bookable:
                    slots = all_slots.get(restaurant.omakase_url, [])
                    if not slots:
                        logger.info("No available slots for %s", restaurant.name)
                        continue

                    candidates = restaurant_candidates[restaurant.omakase_url]
                    logger.info("%s: %d slots found, matching...", restaurant.name, len(slots))

                    if await _try_book_from_slots(client, restaurant, candidates, slots):
                        any_booked = True

    except OmakaseBookingError:
        logger.exception("Omakase login/session error")
    finally:
        await client.close()

    logger.info("Booking cycle complete. Booked: %s", any_booked)
    return any_booked


async def run_scheduler(config: Config):
    """Main scheduling loop.

    In continuous mode (default), keeps running indefinitely to catch cancellations.
    - Near a restaurant's reservation open time: poll rapidly (0.5s)
    - Otherwise: poll at the configured interval
    - After all restaurants have been booked once, switch to cancellation monitoring interval
    """
    global _current_config
    _current_config = config
    mode_label = "常時監視" if config.continuous_mode else "通常"
    logger.info(
        "Omakase Auto-Booker started (%s). Monitoring %d restaurants.",
        mode_label, len(config.target_restaurants),
    )

    # Handle graceful shutdown
    shutdown = asyncio.Event()

    def handle_signal(*_):
        logger.info("Shutdown signal received.")
        shutdown.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    cycle = 0
    while not shutdown.is_set():
        cycle += 1
        logger.info("=== Cycle %d ===", cycle)
        try:
            booked = await run_booking_cycle(config)
            # In non-continuous mode, stop if something was booked
            if booked and not config.continuous_mode:
                logger.info("Booking successful, exiting (non-continuous mode).")
                break
        except Exception:
            logger.exception("Unexpected error in booking cycle")

        # Determine next check interval
        if _is_near_any_open_time(config):
            interval = config.fast_poll_interval_seconds
            logger.info("Near reservation open time - fast polling (%.1fs)", interval)
        else:
            # In continuous mode, use cancellation check interval for background monitoring
            if config.continuous_mode:
                interval = config.cancellation_check_interval_seconds
                logger.info("Cancellation monitoring - next check in %ds", interval)
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
    import argparse

    parser = argparse.ArgumentParser(description="Omakase Auto-Booker CLI")
    parser.add_argument("--dry-run", action="store_true",
                        help="ドライランモード: 決済をスキップして動作検証")
    parser.add_argument("--config", default="config.yaml",
                        help="設定ファイルパス (default: config.yaml)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: {config_path} not found.")
        print("Copy config.example.yaml to config.yaml and fill in your settings.")
        sys.exit(1)

    config = Config.from_yaml(config_path)

    # Apply CLI overrides
    if args.dry_run:
        config.dry_run = True

    if not config.omakase_email or not config.omakase_password:
        print("Error: Omakase email and password must be set in config.yaml")
        sys.exit(1)

    if not config.target_restaurants:
        print("Error: No target restaurants configured in config.yaml")
        sys.exit(1)

    print("=" * 60)
    print("  Omakase Auto-Booker")
    if config.dry_run:
        print("  *** ドライランモード（決済はスキップされます） ***")
    print("=" * 60)
    print()
    print("  WARNING: Omakase (omakase.in) の利用規約では")
    print("  自動操作・ボットが禁止されています。")
    print("  本ツールの使用は自己責任です。")
    print("  アカウント停止のリスクがあります。")
    print()
    mode_label = "常時監視 (キャンセル待ち対応)" if config.continuous_mode else "通常"
    print(f"  モード: {mode_label}")
    print(f"  Monitoring {len(config.target_restaurants)} restaurant(s)")
    for r in config.target_restaurants:
        bmode = "lottery" if r.booking_mode == "lottery" else "first-come"
        dates_info = f", dates: {r.candidate_dates}" if r.candidate_dates else ""
        cancel = ", キャンセル待ち" if r.watch_cancellations else ""
        print(f"    - {r.name} ({bmode}{dates_info}{cancel})")
    print(f"  Fast poll interval: {config.fast_poll_interval_seconds}s")
    print(f"  Normal poll interval: {config.check_interval_seconds}s")
    if config.continuous_mode:
        print(f"  Cancellation check interval: {config.cancellation_check_interval_seconds}s")
    print()

    asyncio.run(run_scheduler(config))


if __name__ == "__main__":
    main()
