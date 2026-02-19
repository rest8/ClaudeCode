"""
Natural disaster data from NASA EONET and GDACS.
"""

import logging

import requests

from services import cache

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

# NASA EONET (Earth Observatory Natural Event Tracker)
EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"
# GDACS (Global Disaster Alert and Coordination System)
GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"


def _fetch_eonet_events() -> list[dict]:
    """Fetch active natural events from NASA EONET."""
    try:
        resp = requests.get(
            EONET_URL,
            params={"status": "open", "limit": 50},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for event in data.get("events", []):
            geom = event.get("geometry", [{}])
            coords = geom[-1].get("coordinates", [0, 0]) if geom else [0, 0]
            category = event.get("categories", [{}])[0].get("title", "Unknown") if event.get("categories") else "Unknown"
            results.append({
                "id": event.get("id", ""),
                "title": event.get("title", ""),
                "category": category,
                "lat": coords[1] if len(coords) >= 2 else 0,
                "lng": coords[0] if len(coords) >= 2 else 0,
                "date": geom[-1].get("date", "") if geom else "",
                "source": "NASA EONET",
            })
        return results
    except Exception as e:
        logger.error("Failed to fetch EONET data: %s", e)
        return []


def _fetch_gdacs_events() -> list[dict]:
    """Fetch active disasters from GDACS."""
    try:
        resp = requests.get(
            GDACS_URL,
            params={"alertlevel": "Green;Orange;Red", "eventlist": ""},
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features", [])
        results = []
        for f in features[:50]:
            props = f.get("properties", {})
            geom = f.get("geometry", {})
            coords = geom.get("coordinates", [0, 0])
            results.append({
                "id": str(props.get("eventid", "")),
                "title": props.get("name", props.get("eventname", "")),
                "category": props.get("eventtype", ""),
                "alert_level": props.get("alertlevel", ""),
                "lat": coords[1] if len(coords) >= 2 else 0,
                "lng": coords[0] if len(coords) >= 2 else 0,
                "date": props.get("fromdate", ""),
                "severity": props.get("severity", {}).get("severity_value", ""),
                "source": "GDACS",
            })
        return results
    except Exception as e:
        logger.error("Failed to fetch GDACS data: %s", e)
        return []


def get_natural_disasters(force_refresh: bool = False) -> list[dict]:
    """Get combined natural disaster data."""
    cache_key = "natural_disasters"
    if force_refresh:
        data = _fetch_eonet_events() + _fetch_gdacs_events()
        cache.set(cache_key, data)
        return data
    return cache.get_or_fetch(
        cache_key,
        lambda: _fetch_eonet_events() + _fetch_gdacs_events(),
        ttl=300,
    )
