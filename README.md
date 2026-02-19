# World Monitor - Python Edition

Python-only port of [koala73/worldmonitor](https://github.com/koala73/worldmonitor).

Real-time global intelligence dashboard with interactive map, live news aggregation, and geopolitical monitoring.

## Features

- **Interactive World Map** - Dark-themed Leaflet map with multiple data layers
- **Live News Feed** - RSS aggregation from 16+ international sources (BBC, Reuters, AP, Al Jazeera, etc.)
- **Earthquake Monitoring** - Real-time USGS data for M4.5+ events
- **Conflict Tracking** - ACLED / UCDP conflict event data
- **GDELT Intelligence** - Global event analysis from GDELT Project
- **Natural Disasters** - NASA EONET + GDACS active events
- **Map Layers**: Conflict zones, intel hotspots, military bases, nuclear facilities, strategic waterways, undersea cables
- **Alert System** - Keyword-based alert highlighting for critical events
- **Auto-refresh** - Background data fetching every 3 minutes
- **22 Monitored Countries** - Tier-1 geopolitical focus areas

## Quick Start

```bash
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000 in your browser.

## Environment Variables (Optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `WM_HOST` | Bind address | `0.0.0.0` |
| `WM_PORT` | Port number | `5000` |
| `WM_DEBUG` | Debug mode | `true` |
| `WM_CACHE_TTL` | Cache TTL (seconds) | `300` |
| `ACLED_API_KEY` | ACLED API key (for conflict data) | - |
| `ACLED_EMAIL` | ACLED registered email | - |

## Project Structure

```
.
├── app.py                  # Flask application (entry point)
├── config.py               # Configuration and static data
├── requirements.txt        # Python dependencies
├── services/
│   ├── cache.py            # File-based caching
│   ├── rss_service.py      # RSS feed aggregation
│   ├── earthquake_service.py   # USGS earthquake data
│   ├── gdelt_service.py    # GDELT event intelligence
│   ├── conflict_service.py # ACLED / UCDP conflict data
│   └── natural_disaster_service.py  # NASA EONET + GDACS
├── templates/
│   └── index.html          # Dashboard HTML template
├── static/
│   ├── css/style.css       # Dashboard styles
│   └── js/
│       ├── map.js          # Leaflet map + layers
│       └── dashboard.js    # UI logic + data loading
└── cache/                  # Auto-generated cache directory
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/news` | Aggregated RSS news (params: `limit`, `source`, `alerts`) |
| `GET /api/earthquakes` | USGS earthquake data (M4.5+ last 24h) |
| `GET /api/gdelt` | GDELT intelligence events |
| `GET /api/conflicts` | Conflict event data (ACLED/UCDP) |
| `GET /api/disasters` | Natural disaster data (EONET/GDACS) |
| `GET /api/layers/conflict-zones` | Conflict zone definitions |
| `GET /api/layers/hotspots` | Intel hotspot locations |
| `GET /api/layers/military-bases` | Military base locations |
| `GET /api/layers/nuclear` | Nuclear facility locations |
| `GET /api/layers/waterways` | Strategic waterway locations |
| `GET /api/layers/cables` | Undersea cable routes |
| `GET /api/status` | Health check and data freshness |

## Data Sources

- **RSS**: BBC, Reuters, AP, Guardian, Al Jazeera, France 24, NPR, DW, NHK, EuroNews, CSIS, Brookings, etc.
- **Earthquakes**: [USGS GeoJSON Feed](https://earthquake.usgs.gov/earthquakes/feed/)
- **Conflicts**: [ACLED](https://acleddata.com/) (API key required) / [UCDP](https://ucdp.uu.se/) (free)
- **Events**: [GDELT Project](https://www.gdeltproject.org/)
- **Disasters**: [NASA EONET](https://eonet.gsfc.nasa.gov/) + [GDACS](https://www.gdacs.org/)

## Credits

Original project: [koala73/worldmonitor](https://github.com/koala73/worldmonitor) (TypeScript/React/Node.js)
