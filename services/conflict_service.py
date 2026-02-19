"""
Conflict and protest data service.
Uses ACLED API (if key is available) or GDELT as fallback.
"""

import logging
from datetime import datetime, timedelta, timezone

import requests

import config
from services import cache

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 20


def _fetch_acled_events() -> list[dict]:
    """Fetch recent conflict/protest events from ACLED API."""
    if not config.ACLED_API_KEY or not config.ACLED_EMAIL:
        return []

    try:
        date_from = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        params = {
            "key": config.ACLED_API_KEY,
            "email": config.ACLED_EMAIL,
            "event_date": f"{date_from}|",
            "event_date_where": ">=",
            "limit": 500,
            "fields": "event_id_cnty|event_date|event_type|sub_event_type|"
                      "country|admin1|latitude|longitude|fatalities|notes",
        }
        resp = requests.get(
            "https://api.acleddata.com/acled/read",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        events = data.get("data", [])
        results = []
        for ev in events:
            results.append({
                "id": ev.get("event_id_cnty", ""),
                "date": ev.get("event_date", ""),
                "type": ev.get("event_type", ""),
                "sub_type": ev.get("sub_event_type", ""),
                "country": ev.get("country", ""),
                "region": ev.get("admin1", ""),
                "lat": float(ev.get("latitude", 0)),
                "lng": float(ev.get("longitude", 0)),
                "fatalities": int(ev.get("fatalities", 0)),
                "notes": (ev.get("notes", "") or "")[:500],
            })
        return results
    except Exception as e:
        logger.error("Failed to fetch ACLED data: %s", e)
        return []


def _fetch_ucdp_events() -> list[dict]:
    """Fetch recent events from UCDP (Uppsala Conflict Data Program) - free, no API key."""
    try:
        current_year = datetime.now(timezone.utc).year
        resp = requests.get(
            "https://ucdpapi.pcr.uu.se/api/gedevents/24.1",
            params={
                "pagesize": 100,
                "page": 0,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        events = data.get("Result", [])
        results = []
        for ev in events:
            results.append({
                "id": str(ev.get("id", "")),
                "date": ev.get("date_start", ""),
                "type": "Battle" if ev.get("type_of_violence", 1) == 1 else "One-sided violence",
                "sub_type": ev.get("side_a", ""),
                "country": ev.get("country", ""),
                "region": ev.get("region", ""),
                "lat": float(ev.get("latitude", 0)),
                "lng": float(ev.get("longitude", 0)),
                "fatalities": int(ev.get("best", 0)),
                "notes": f"{ev.get('side_a', '')} vs {ev.get('side_b', '')}",
                "source": "UCDP",
            })
        return results
    except Exception as e:
        logger.error("Failed to fetch UCDP data: %s", e)
        return []


def get_conflict_events(force_refresh: bool = False) -> list[dict]:
    """Get conflict events - tries ACLED first, falls back to UCDP."""
    cache_key = "conflict_events"
    if force_refresh:
        data = _fetch_acled_events()
        if not data:
            data = _fetch_ucdp_events()
        cache.set(cache_key, data)
        return data

    def _fetch():
        data = _fetch_acled_events()
        if not data:
            data = _fetch_ucdp_events()
        return data

    return cache.get_or_fetch(cache_key, _fetch, ttl=600)
