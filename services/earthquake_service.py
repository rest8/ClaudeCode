"""
USGS Earthquake data service.
Fetches significant earthquake data from the USGS GeoJSON feed.
"""

import logging

import requests

from services import cache
import config

logger = logging.getLogger(__name__)

USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"
REQUEST_TIMEOUT = 15


def _fetch_earthquakes() -> list[dict]:
    """Fetch earthquake data from USGS."""
    try:
        resp = requests.get(USGS_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            coords = feature.get("geometry", {}).get("coordinates", [0, 0, 0])
            results.append({
                "id": feature.get("id", ""),
                "magnitude": props.get("mag", 0),
                "place": props.get("place", "Unknown"),
                "time": props.get("time", 0),
                "url": props.get("url", ""),
                "tsunami": props.get("tsunami", 0),
                "lat": coords[1],
                "lng": coords[0],
                "depth": coords[2],
                "alert": props.get("alert"),
                "felt": props.get("felt", 0),
            })
        results.sort(key=lambda x: x["magnitude"], reverse=True)
        return results
    except Exception as e:
        logger.error("Failed to fetch earthquake data: %s", e)
        return []


def get_earthquakes(force_refresh: bool = False) -> list[dict]:
    """Get earthquake data, using cache when available."""
    if force_refresh:
        data = _fetch_earthquakes()
        cache.set("earthquakes", data)
        return data
    return cache.get_or_fetch(
        "earthquakes", _fetch_earthquakes, ttl=config.EARTHQUAKE_REFRESH_INTERVAL
    )
