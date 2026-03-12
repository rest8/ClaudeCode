"""Google Calendar integration - read free slots, fetch events, create bookings."""

import logging
from datetime import datetime, timedelta, time, date

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import Config

logger = logging.getLogger(__name__)

# Read + write scope so we can also insert booked events
SCOPES = ["https://www.googleapis.com/auth/calendar"]


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


def _build_service(config: Config):
    """Build the Google Calendar API service."""
    creds = _get_credentials(config)
    return build("calendar", "v3", credentials=creds)


def get_events_for_range(
    config: Config,
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Fetch all calendar events in a date range.

    Returns:
        List of event dicts with keys: summary, start, end, all_day.
    """
    service = _build_service(config)

    time_min = datetime.combine(start_date, time(0, 0)).isoformat() + "+09:00"
    time_max = datetime.combine(end_date + timedelta(days=1), time(0, 0)).isoformat() + "+09:00"

    events_result = (
        service.events()
        .list(
            calendarId=config.calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = []
    for item in events_result.get("items", []):
        start_str = item["start"].get("dateTime", item["start"].get("date"))
        end_str = item["end"].get("dateTime", item["end"].get("date"))
        all_day = "date" in item["start"] and "dateTime" not in item["start"]

        if all_day:
            ev_start = datetime.strptime(start_str, "%Y-%m-%d")
            ev_end = datetime.strptime(end_str, "%Y-%m-%d")
        else:
            ev_start = datetime.fromisoformat(start_str).replace(tzinfo=None)
            ev_end = datetime.fromisoformat(end_str).replace(tzinfo=None)

        events.append({
            "summary": item.get("summary", "(no title)"),
            "start": ev_start,
            "end": ev_end,
            "all_day": all_day,
            "id": item.get("id"),
        })

    return events


def get_free_slots(
    config: Config,
    target_date: datetime,
    dining_hours: tuple[time, time] = (time(11, 0), time(21, 0)),
) -> list[tuple[datetime, datetime]]:
    """Find free time slots on a given date within dining hours."""
    service = _build_service(config)

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
        start = datetime.fromisoformat(start_str).replace(tzinfo=None)
        end = datetime.fromisoformat(end_str).replace(tzinfo=None)
        busy_periods.append((start, end))

    busy_periods.sort(key=lambda x: x[0])

    free_slots = []
    current = day_start

    for busy_start, busy_end in busy_periods:
        if current < busy_start:
            gap = (busy_start - current).total_seconds() / 3600
            if gap >= config.min_free_hours:
                free_slots.append((current, busy_start))
        current = max(current, busy_end)

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
    """Get dates with free slots matching preferred dining times."""
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
                pref_end = pref_dt + timedelta(hours=config.min_free_hours)
                if slot_start <= pref_dt and pref_end <= slot_end:
                    matching_times.append(pref_time_str)
                    break

        if matching_times:
            available.append((target, matching_times))

    logger.info("Found %d available dates across %d months", len(available), config.booking_months_ahead)
    return available


def create_booking_event(
    config: Config,
    restaurant_name: str,
    booking_date: str,
    booking_time: str,
    party_size: int,
    duration_hours: float = 2.0,
) -> str | None:
    """Create a Google Calendar event for a confirmed booking.

    Args:
        config: Application config.
        restaurant_name: Name of the restaurant.
        booking_date: Date string (YYYY-MM-DD).
        booking_time: Time string (HH:MM).
        party_size: Number of guests.
        duration_hours: Duration of the meal.

    Returns:
        Created event ID, or None on failure.
    """
    service = _build_service(config)

    hour, minute = map(int, booking_time.split(":"))
    dt = datetime.strptime(booking_date, "%Y-%m-%d")
    start_dt = dt.replace(hour=hour, minute=minute)
    end_dt = start_dt + timedelta(hours=duration_hours)

    event_body = {
        "summary": f"{restaurant_name} ({party_size}名)",
        "description": (
            f"Omakase Auto-Booker で予約済み\n"
            f"レストラン: {restaurant_name}\n"
            f"人数: {party_size}名\n"
            f"※写真付き身分証明書を持参してください"
        ),
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": "Asia/Tokyo",
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": "Asia/Tokyo",
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 1440},  # 1 day before
                {"method": "popup", "minutes": 120},    # 2 hours before
            ],
        },
    }

    try:
        created = service.events().insert(
            calendarId=config.calendar_id,
            body=event_body,
        ).execute()
        event_id = created.get("id")
        logger.info(
            "Calendar event created: %s on %s at %s (ID: %s)",
            restaurant_name, booking_date, booking_time, event_id,
        )
        return event_id
    except Exception:
        logger.exception("Failed to create calendar event")
        return None
