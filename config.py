"""
World Monitor - Configuration
Python-only port of https://github.com/koala73/worldmonitor
"""

import os

# --- Server ---
HOST = os.environ.get("WM_HOST", "0.0.0.0")
PORT = int(os.environ.get("WM_PORT", "5000"))
DEBUG = os.environ.get("WM_DEBUG", "true").lower() == "true"

# --- Cache ---
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
CACHE_TTL_SECONDS = int(os.environ.get("WM_CACHE_TTL", "300"))  # 5 min

# --- Data refresh intervals (seconds) ---
RSS_REFRESH_INTERVAL = 180       # 3 min
EARTHQUAKE_REFRESH_INTERVAL = 300  # 5 min
GDELT_REFRESH_INTERVAL = 600      # 10 min

# --- API Keys (optional, for enhanced data) ---
ACLED_API_KEY = os.environ.get("ACLED_API_KEY", "")
ACLED_EMAIL = os.environ.get("ACLED_EMAIL", "")

# --- Tier-1 Monitored Countries (22) ---
TIER1_COUNTRIES = {
    "US": "United States",
    "RU": "Russia",
    "CN": "China",
    "IN": "India",
    "DE": "Germany",
    "FR": "France",
    "GB": "United Kingdom",
    "BR": "Brazil",
    "IR": "Iran",
    "IL": "Israel",
    "SA": "Saudi Arabia",
    "AE": "United Arab Emirates",
    "SY": "Syria",
    "YE": "Yemen",
    "TR": "Turkey",
    "TW": "Taiwan",
    "KP": "North Korea",
    "MM": "Myanmar",
    "UA": "Ukraine",
    "PL": "Poland",
    "PK": "Pakistan",
    "VE": "Venezuela",
}

# --- RSS Feed Sources (Tiered) ---
RSS_FEEDS = {
    # Tier 1: Wire services / official
    "Reuters": "https://news.google.com/rss/search?q=site:reuters.com+world&hl=en",
    "AP News": "https://news.google.com/rss/search?q=site:apnews.com+world&hl=en",
    "BBC World": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "France 24": "https://www.france24.com/en/rss",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    # Tier 2: Major outlets
    "The Guardian": "https://www.theguardian.com/world/rss",
    "NPR": "https://feeds.npr.org/1004/rss.xml",
    "DW News": "https://rss.dw.com/rdf/rss-en-world",
    "NHK World": "https://www3.nhk.or.jp/rss/news/cat0.xml",
    "EuroNews": "https://www.euronews.com/rss?level=theme&name=news",
    # Tier 3: Specialty / analysis
    "CSIS": "https://www.csis.org/analysis/feed",
    "War on the Rocks": "https://warontherocks.com/feed/",
    "The Diplomat": "https://thediplomat.com/feed/",
    "Defense One": "https://www.defenseone.com/rss/",
    "Brookings": "https://www.brookings.edu/feed/",
    # Tier 4: Aggregators
    "Hacker News": "https://hnrss.org/frontpage",
}

# --- Alert Keywords (triggers highlighting) ---
ALERT_KEYWORDS = [
    "war", "invasion", "nuclear", "sanctions", "missile",
    "coup", "terror attack", "martial law", "ceasefire",
    "escalation", "troops", "airstrike", "drone strike",
    "explosion", "emergency", "evacuation", "chemical",
    "biological", "cyber attack", "blackout",
]

# --- Conflict Zones ---
CONFLICT_ZONES = [
    {
        "name": "Ukraine",
        "lat": 48.5,
        "lng": 36.0,
        "radius": 400000,
        "color": "#ff4444",
        "status": "Active War",
        "description": "Russia-Ukraine conflict since February 2022",
    },
    {
        "name": "Gaza",
        "lat": 31.4,
        "lng": 34.4,
        "radius": 50000,
        "color": "#ff4444",
        "status": "Active Conflict",
        "description": "Israel-Hamas conflict",
    },
    {
        "name": "Sudan",
        "lat": 15.5,
        "lng": 32.5,
        "radius": 500000,
        "color": "#ff6644",
        "status": "Civil War",
        "description": "SAF vs RSF conflict since April 2023",
    },
    {
        "name": "Myanmar",
        "lat": 19.8,
        "lng": 96.2,
        "radius": 400000,
        "color": "#ff6644",
        "status": "Civil War",
        "description": "Military junta vs resistance forces",
    },
    {
        "name": "Red Sea / Yemen",
        "lat": 14.0,
        "lng": 43.0,
        "radius": 300000,
        "color": "#ff8844",
        "status": "Active Conflict",
        "description": "Houthi attacks on shipping / coalition strikes",
    },
    {
        "name": "Sahel Region",
        "lat": 14.0,
        "lng": 0.0,
        "radius": 800000,
        "color": "#ff8844",
        "status": "Insurgency",
        "description": "Jihadist insurgency across Mali, Burkina Faso, Niger",
    },
]

# --- Intel Hotspots ---
INTEL_HOTSPOTS = [
    {"name": "Taiwan Strait", "lat": 24.0, "lng": 119.5, "level": "high",
     "description": "US-China strategic flashpoint"},
    {"name": "Korean Peninsula", "lat": 38.0, "lng": 127.0, "level": "high",
     "description": "North Korea nuclear/missile threat"},
    {"name": "South China Sea", "lat": 12.0, "lng": 114.0, "level": "high",
     "description": "Territorial disputes, military buildup"},
    {"name": "Iran Nuclear", "lat": 32.4, "lng": 53.7, "level": "high",
     "description": "Nuclear program tensions"},
    {"name": "Baltic States", "lat": 57.0, "lng": 24.0, "level": "medium",
     "description": "NATO-Russia border tensions"},
    {"name": "Horn of Africa", "lat": 8.0, "lng": 45.0, "level": "medium",
     "description": "Somalia, Ethiopia instability"},
    {"name": "Haiti", "lat": 19.0, "lng": -72.3, "level": "medium",
     "description": "Gang violence, state collapse"},
    {"name": "Venezuela-Guyana", "lat": 6.0, "lng": -61.0, "level": "medium",
     "description": "Essequibo territorial dispute"},
    {"name": "Kashmir", "lat": 34.0, "lng": 75.0, "level": "medium",
     "description": "India-Pakistan territorial dispute"},
    {"name": "Transnistria", "lat": 47.0, "lng": 29.5, "level": "low",
     "description": "Frozen conflict, Russian troops"},
    {"name": "Nagorno-Karabakh", "lat": 39.8, "lng": 46.8, "level": "low",
     "description": "Post-conflict monitoring"},
    {"name": "Arctic", "lat": 75.0, "lng": 40.0, "level": "low",
     "description": "Resource competition, militarization"},
]

# --- Strategic Waterways ---
STRATEGIC_WATERWAYS = [
    {"name": "Strait of Hormuz", "lat": 26.5, "lng": 56.3,
     "traffic": "~21M bbl/day oil", "controlled_by": "Iran/Oman"},
    {"name": "Strait of Malacca", "lat": 2.5, "lng": 101.5,
     "traffic": "~25% global trade", "controlled_by": "Malaysia/Indonesia/Singapore"},
    {"name": "Suez Canal", "lat": 30.5, "lng": 32.3,
     "traffic": "~12% global trade", "controlled_by": "Egypt"},
    {"name": "Panama Canal", "lat": 9.1, "lng": -79.7,
     "traffic": "~5% global trade", "controlled_by": "Panama"},
    {"name": "Taiwan Strait", "lat": 24.3, "lng": 119.5,
     "traffic": "~88% of largest container ships", "controlled_by": "Disputed"},
    {"name": "Bosphorus", "lat": 41.1, "lng": 29.1,
     "traffic": "~3M bbl/day oil", "controlled_by": "Turkey"},
    {"name": "Bab el-Mandeb", "lat": 12.6, "lng": 43.3,
     "traffic": "~6M bbl/day oil", "controlled_by": "Yemen/Djibouti/Eritrea"},
    {"name": "Danish Straits", "lat": 55.7, "lng": 12.6,
     "traffic": "Baltic Sea access", "controlled_by": "Denmark"},
    {"name": "Lombok Strait", "lat": -8.5, "lng": 115.7,
     "traffic": "Alternative to Malacca", "controlled_by": "Indonesia"},
]

# --- Major Military Bases (sample) ---
MILITARY_BASES = [
    # US/NATO
    {"name": "Ramstein AB", "lat": 49.44, "lng": 7.60, "operator": "US/NATO", "type": "Air Base"},
    {"name": "Camp Humphreys", "lat": 36.97, "lng": 127.03, "operator": "US", "type": "Army Base"},
    {"name": "Yokosuka Naval Base", "lat": 35.29, "lng": 139.67, "operator": "US", "type": "Naval Base"},
    {"name": "Diego Garcia", "lat": -7.32, "lng": 72.42, "operator": "US/UK", "type": "Naval/Air"},
    {"name": "Al Udeid AB", "lat": 25.12, "lng": 51.31, "operator": "US", "type": "Air Base"},
    {"name": "Incirlik AB", "lat": 37.00, "lng": 35.43, "operator": "US/NATO", "type": "Air Base"},
    {"name": "Guantanamo Bay", "lat": 19.91, "lng": -75.10, "operator": "US", "type": "Naval Base"},
    {"name": "Djibouti (Camp Lemonnier)", "lat": 11.55, "lng": 43.15, "operator": "US", "type": "Expeditionary"},
    {"name": "Thule AB (Pituffik)", "lat": 76.53, "lng": -68.70, "operator": "US", "type": "Space/Radar"},
    # Russia
    {"name": "Kaliningrad", "lat": 54.71, "lng": 20.51, "operator": "Russia", "type": "Naval/Missile"},
    {"name": "Sevastopol", "lat": 44.62, "lng": 33.53, "operator": "Russia", "type": "Naval Base"},
    {"name": "Tartus", "lat": 34.89, "lng": 35.89, "operator": "Russia", "type": "Naval Base"},
    {"name": "Khmeimim AB", "lat": 35.41, "lng": 35.95, "operator": "Russia", "type": "Air Base"},
    {"name": "Vladivostok", "lat": 43.12, "lng": 131.88, "operator": "Russia", "type": "Pacific Fleet"},
    # China
    {"name": "Djibouti (PLA)", "lat": 11.59, "lng": 43.05, "operator": "China", "type": "Support Base"},
    {"name": "Fiery Cross Reef", "lat": 9.55, "lng": 112.89, "operator": "China", "type": "Artificial Island"},
    {"name": "Mischief Reef", "lat": 9.90, "lng": 115.53, "operator": "China", "type": "Artificial Island"},
    {"name": "Ream Naval Base", "lat": 10.51, "lng": 103.63, "operator": "China", "type": "Naval Base"},
    # Others
    {"name": "Djibouti (France)", "lat": 11.54, "lng": 43.16, "operator": "France", "type": "Military Base"},
    {"name": "Reunion Island", "lat": -20.89, "lng": 55.52, "operator": "France", "type": "Military Base"},
]

# --- Nuclear Facilities (sample) ---
NUCLEAR_FACILITIES = [
    {"name": "Natanz", "lat": 33.72, "lng": 51.73, "country": "Iran", "type": "Enrichment"},
    {"name": "Fordow", "lat": 34.88, "lng": 51.59, "country": "Iran", "type": "Enrichment"},
    {"name": "Yongbyon", "lat": 39.80, "lng": 125.75, "country": "North Korea", "type": "Reactor/Reprocessing"},
    {"name": "Dimona", "lat": 31.00, "lng": 35.15, "country": "Israel", "type": "Reactor"},
    {"name": "Kahuta", "lat": 33.59, "lng": 73.39, "country": "Pakistan", "type": "Enrichment"},
    {"name": "Zaporizhzhia NPP", "lat": 47.51, "lng": 34.59, "country": "Ukraine", "type": "Power (Occupied)"},
    {"name": "La Hague", "lat": 49.68, "lng": -1.88, "country": "France", "type": "Reprocessing"},
    {"name": "Sellafield", "lat": 54.42, "lng": -3.50, "country": "UK", "type": "Reprocessing"},
    {"name": "Rokkasho", "lat": 40.96, "lng": 141.33, "country": "Japan", "type": "Reprocessing"},
    {"name": "Barakah NPP", "lat": 23.96, "lng": 52.26, "country": "UAE", "type": "Power"},
]

# --- Undersea Cables (sample routes) ---
UNDERSEA_CABLES = [
    {"name": "TAT-14", "points": [[40.8, -73.9], [50.4, -4.5]],
     "capacity": "3.2 Tbps", "route": "US-UK"},
    {"name": "AEConnect-1", "points": [[53.3, -6.3], [40.8, -73.9]],
     "capacity": "52 Tbps", "route": "Ireland-US"},
    {"name": "SEA-ME-WE 6", "points": [[1.3, 103.8], [31.2, 29.9], [43.3, -2.9]],
     "capacity": "126 Tbps", "route": "Singapore-Egypt-France"},
    {"name": "PEACE Cable", "points": [[39.0, 117.7], [25.0, 55.3], [43.3, -2.9]],
     "capacity": "96 Tbps", "route": "China-UAE-France"},
    {"name": "2Africa", "points": [[-33.9, 18.4], [6.5, 3.4], [51.5, -0.1]],
     "capacity": "180 Tbps", "route": "Africa circumnavigation"},
    {"name": "JUPITER", "points": [[35.7, 139.7], [37.6, -122.4]],
     "capacity": "60 Tbps", "route": "Japan-US"},
]
