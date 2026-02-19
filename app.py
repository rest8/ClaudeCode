"""
World Monitor - Python Edition
Real-time global intelligence dashboard.
Python-only port of https://github.com/koala73/worldmonitor

Usage:
    pip install -r requirements.txt
    python app.py
"""

import json
import logging
import threading
import time

from flask import Flask, jsonify, render_template, request

import config
from services import cache
from services.rss_service import get_news
from services.earthquake_service import get_earthquakes
from services.gdelt_service import get_gdelt_events, get_gdelt_geo
from services.conflict_service import get_conflict_events
from services.natural_disaster_service import get_natural_disasters

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Background data refresh
# ---------------------------------------------------------------------------
def _background_refresh():
    """Periodically refresh data in the background."""
    while True:
        try:
            logger.info("Background refresh: fetching RSS feeds...")
            get_news(force_refresh=True)
        except Exception as e:
            logger.error("Background RSS refresh failed: %s", e)

        try:
            logger.info("Background refresh: fetching earthquake data...")
            get_earthquakes(force_refresh=True)
        except Exception as e:
            logger.error("Background earthquake refresh failed: %s", e)

        try:
            logger.info("Background refresh: fetching GDELT events...")
            get_gdelt_events(force_refresh=True)
        except Exception as e:
            logger.error("Background GDELT refresh failed: %s", e)

        try:
            logger.info("Background refresh: fetching conflict data...")
            get_conflict_events(force_refresh=True)
        except Exception as e:
            logger.error("Background conflict refresh failed: %s", e)

        try:
            logger.info("Background refresh: fetching natural disasters...")
            get_natural_disasters(force_refresh=True)
        except Exception as e:
            logger.error("Background disaster refresh failed: %s", e)

        logger.info("Background refresh complete. Sleeping %ds...", config.RSS_REFRESH_INTERVAL)
        time.sleep(config.RSS_REFRESH_INTERVAL)


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    """Main dashboard page."""
    return render_template(
        "index.html",
        countries=config.TIER1_COUNTRIES,
        conflict_zones=config.CONFLICT_ZONES,
    )


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------
@app.route("/api/news")
def api_news():
    """Get aggregated RSS news."""
    limit = request.args.get("limit", 100, type=int)
    source = request.args.get("source", "")
    alerts_only = request.args.get("alerts", "false").lower() == "true"

    items = get_news() or []
    if source:
        items = [i for i in items if i["source"].lower() == source.lower()]
    if alerts_only:
        items = [i for i in items if i.get("is_alert")]
    return jsonify(items[:limit])


@app.route("/api/earthquakes")
def api_earthquakes():
    """Get recent significant earthquakes."""
    return jsonify(get_earthquakes() or [])


@app.route("/api/gdelt")
def api_gdelt():
    """Get GDELT intelligence events."""
    return jsonify(get_gdelt_events() or [])


@app.route("/api/conflicts")
def api_conflicts():
    """Get conflict event data."""
    return jsonify(get_conflict_events() or [])


@app.route("/api/disasters")
def api_disasters():
    """Get natural disaster data."""
    return jsonify(get_natural_disasters() or [])


@app.route("/api/layers/conflict-zones")
def api_conflict_zones():
    """Get static conflict zone definitions."""
    return jsonify(config.CONFLICT_ZONES)


@app.route("/api/layers/hotspots")
def api_hotspots():
    """Get intel hotspot locations."""
    return jsonify(config.INTEL_HOTSPOTS)


@app.route("/api/layers/waterways")
def api_waterways():
    """Get strategic waterway locations."""
    return jsonify(config.STRATEGIC_WATERWAYS)


@app.route("/api/layers/military-bases")
def api_military_bases():
    """Get military base locations."""
    return jsonify(config.MILITARY_BASES)


@app.route("/api/layers/nuclear")
def api_nuclear():
    """Get nuclear facility locations."""
    return jsonify(config.NUCLEAR_FACILITIES)


@app.route("/api/layers/cables")
def api_cables():
    """Get undersea cable routes."""
    return jsonify(config.UNDERSEA_CABLES)


@app.route("/api/status")
def api_status():
    """Health check / data freshness."""
    news = cache.get("rss_news", ttl=86400)
    quakes = cache.get("earthquakes", ttl=86400)
    conflicts = cache.get("conflict_events", ttl=86400)
    disasters = cache.get("natural_disasters", ttl=86400)
    return jsonify({
        "status": "ok",
        "data": {
            "news": {"count": len(news) if news else 0, "cached": news is not None},
            "earthquakes": {"count": len(quakes) if quakes else 0, "cached": quakes is not None},
            "conflicts": {"count": len(conflicts) if conflicts else 0, "cached": conflicts is not None},
            "disasters": {"count": len(disasters) if disasters else 0, "cached": disasters is not None},
        },
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Start background data refresh thread
    refresh_thread = threading.Thread(target=_background_refresh, daemon=True)
    refresh_thread.start()

    logger.info("Starting World Monitor on http://%s:%d", config.HOST, config.PORT)
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
