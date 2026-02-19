"""
GDELT (Global Database of Events, Language, and Tone) service.
Fetches recent geopolitical events from the GDELT DOC API.
"""

import logging
from datetime import datetime, timezone

import requests

from services import cache
import config

logger = logging.getLogger(__name__)

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
REQUEST_TIMEOUT = 20


def _fetch_gdelt_events(query: str = "conflict OR crisis OR military") -> list[dict]:
    """Fetch events from the GDELT DOC 2.0 API."""
    try:
        params = {
            "query": query,
            "mode": "artlist",
            "maxrecords": 50,
            "format": "json",
            "sort": "datedesc",
            "timespan": "24h",
        }
        resp = requests.get(GDELT_DOC_API, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        articles = data.get("articles", [])
        results = []
        for art in articles:
            results.append({
                "title": art.get("title", ""),
                "url": art.get("url", ""),
                "source": art.get("domain", ""),
                "language": art.get("language", ""),
                "seendate": art.get("seendate", ""),
                "socialimage": art.get("socialimage", ""),
                "tone": art.get("tone", 0),
            })
        return results
    except Exception as e:
        logger.error("Failed to fetch GDELT events: %s", e)
        return []


def _fetch_gdelt_geo(query: str = "conflict OR crisis") -> list[dict]:
    """Fetch geolocated events from GDELT for map overlay."""
    try:
        params = {
            "query": query,
            "mode": "pointdata",
            "maxrecords": 200,
            "format": "json",
            "timespan": "24h",
        }
        resp = requests.get(GDELT_DOC_API, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        text = resp.text
        # GDELT point data returns a simple format
        # Try parsing as JSON first
        try:
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception:
            return []
    except Exception as e:
        logger.error("Failed to fetch GDELT geo data: %s", e)
        return []


def get_gdelt_events(force_refresh: bool = False) -> list[dict]:
    """Get GDELT events with caching."""
    if force_refresh:
        data = _fetch_gdelt_events()
        cache.set("gdelt_events", data)
        return data
    return cache.get_or_fetch(
        "gdelt_events", _fetch_gdelt_events, ttl=config.GDELT_REFRESH_INTERVAL
    )


def get_gdelt_geo(force_refresh: bool = False) -> list[dict]:
    """Get GDELT geolocated data with caching."""
    if force_refresh:
        data = _fetch_gdelt_geo()
        cache.set("gdelt_geo", data)
        return data
    return cache.get_or_fetch(
        "gdelt_geo", _fetch_gdelt_geo, ttl=config.GDELT_REFRESH_INTERVAL
    )
