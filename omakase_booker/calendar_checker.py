"""Google Calendar integration to find free time slots."""

import logging
from datetime import datetime, timedelta, time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import Config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _get_credentials(config: Config) -> Credentials:
    """Get or refresh Google Calendar API credentials."""
    creds = None

    try:
        creds = Credentials.from_authorized_user_file(config.google_token_path, SCOPES)
    except (FileNotFoundError, ValueError):
        pass

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            config.google_credentials_path, SCOPES
        )
        creds = flow.run_local_server(port=0)
        with open(config.google_token_path, "w") as token_file:
            token_file.write(creds.to_json())

    return creds


def get_free_slots(
    config: Config,
    target_date: datetime,
    dining_hours: tuple[time, time] = (time(11, 0), time(21, 0)),
) -> list[tuple[datetime, datetime]]:
    """Find free time slots on a given date within dining hours.

    Args:
        config: Application config.
        target_date: The date to check.
        dining_hours: Tuple of (earliest_start, latest_start) for dining.

    Returns:
        List of (start, end) tuples representing free slots.
    """
    creds = _get_credentials(config)
    service = build("calendar", "v3", credentials=creds)

    day_start = datetime.combine(target_date.date(), dining_hours[0])
    day_end = datetime.combine(target_date.date(), dining_hours[1])

    events_result = (
        service.events()
        .list(
            calendarId=config.calendar_id,
            timeMin=day_start.isoformat() + "+09:00",
            timeMax=day_end.isoformat() + "+09:00",
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = events_result.get("items", [])
    busy_periods = []
    for event in events:
        start_str = event["start"].get("dateTime", event["start"].get("date"))
        end_str = event["end"].get("dateTime", event["end"].get("date"))
        start = datetime.fromisoformat(start_str)
        end = datetime.fromisoformat(end_str)
        # Normalize to naive datetime for comparison
        start = start.replace(tzinfo=None)
        end = end.replace(tzinfo=None)
        busy_periods.append((start, end))

    # Sort by start time
    busy_periods.sort(key=lambda x: x[0])

    # Find free gaps
    free_slots = []
    current = day_start

    for busy_start, busy_end in busy_periods:
        if current < busy_start:
            gap = (busy_start - current).total_seconds() / 3600
            if gap >= config.min_free_hours:
                free_slots.append((current, busy_start))
        current = max(current, busy_end)

    # Check remaining time after last event
    if current < day_end:
        gap = (day_end - current).total_seconds() / 3600
        if gap >= config.min_free_hours:
            free_slots.append((current, day_end))

    logger.info(
        "Date %s: %d events found, %d free slots",
        target_date.date(),
        len(events),
        len(free_slots),
    )
    return free_slots


def get_available_dates(
    config: Config,
    preferred_times: list[str],
) -> list[tuple[datetime, list[str]]]:
    """Get dates with free slots matching preferred dining times.

    Returns:
        List of (date, matching_times) where matching_times are HH:MM strings
        that fall within a free slot.
    """
    available = []
    today = datetime.now()

    for days_ahead in range(1, config.booking_months_ahead * 30 + 1):
        target = today + timedelta(days=days_ahead)
        try:
            free_slots = get_free_slots(config, target)
        except Exception:
            logger.exception("Failed to check calendar for %s", target.date())
            continue

        matching_times = []
        for pref_time_str in preferred_times:
            hour, minute = map(int, pref_time_str.split(":"))
            pref_dt = datetime.combine(target.date(), time(hour, minute))

            for slot_start, slot_end in free_slots:
                # Check if preferred time + min_free_hours fits in the free slot
                pref_end = pref_dt + timedelta(hours=config.min_free_hours)
                if slot_start <= pref_dt and pref_end <= slot_end:
                    matching_times.append(pref_time_str)
                    break

        if matching_times:
            available.append((target, matching_times))

    logger.info("Found %d available dates across %d months", len(available), config.booking_months_ahead)
    return available
