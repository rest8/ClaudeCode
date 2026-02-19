"""
RSS feed aggregation service.
Fetches and parses RSS feeds from configured sources.
Uses stdlib xml.etree.ElementTree (no external dependencies).
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import unescape
from xml.etree import ElementTree

import requests

import config
from services import cache

logger = logging.getLogger(__name__)

_session = requests.Session()
_session.headers.update({
    "User-Agent": "WorldMonitor/1.0 (Python; RSS Aggregator)",
})
REQUEST_TIMEOUT = 15

# Common RSS date formats
_DATE_FORMATS = [
    "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S %Z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S",
    "%a, %d %b %Y %H:%M:%S",
]


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    return text.strip()


def _parse_rss_date(date_str: str) -> str:
    """Parse RSS date string into ISO format."""
    if not date_str:
        return datetime.now(timezone.utc).isoformat()
    date_str = date_str.strip()
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return datetime.now(timezone.utc).isoformat()


def _is_alert(title: str, summary: str) -> bool:
    """Check if the article matches alert keywords."""
    text = (title + " " + summary).lower()
    return any(kw in text for kw in config.ALERT_KEYWORDS)


def _get_text(element, tag: str, namespaces: dict | None = None) -> str:
    """Safely get text from an XML element."""
    child = element.find(tag, namespaces)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def _parse_rss_xml(xml_bytes: bytes, source_name: str) -> list[dict]:
    """Parse RSS/Atom XML into article list."""
    items = []
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return items

    # Detect Atom vs RSS
    # Atom namespace
    atom_ns = {"atom": "http://www.w3.org/2005/Atom"}

    # Try RSS 2.0 first (<rss><channel><item>)
    channel = root.find("channel")
    if channel is not None:
        for entry in channel.findall("item")[:20]:
            title = _strip_html(_get_text(entry, "title"))
            summary = _strip_html(_get_text(entry, "description"))[:500]
            link = _get_text(entry, "link")
            pub_date = _parse_rss_date(
                _get_text(entry, "pubDate") or _get_text(entry, "dc:date")
            )
            items.append({
                "source": source_name,
                "title": title,
                "summary": summary,
                "link": link,
                "published": pub_date,
                "is_alert": _is_alert(title, summary),
            })
        return items

    # Try Atom (<feed><entry>)
    entries = root.findall("atom:entry", atom_ns) or root.findall("entry")
    if not entries:
        # Try without namespace
        entries = root.findall("{http://www.w3.org/2005/Atom}entry")
    for entry in entries[:20]:
        title = _strip_html(
            _get_text(entry, "atom:title", atom_ns) or
            _get_text(entry, "title") or
            _get_text(entry, "{http://www.w3.org/2005/Atom}title")
        )
        summary_text = (
            _get_text(entry, "atom:summary", atom_ns) or
            _get_text(entry, "atom:content", atom_ns) or
            _get_text(entry, "summary") or
            _get_text(entry, "{http://www.w3.org/2005/Atom}summary") or
            ""
        )
        summary = _strip_html(summary_text)[:500]

        # Atom link is usually an attribute
        link = ""
        for link_tag in ["atom:link", "link", "{http://www.w3.org/2005/Atom}link"]:
            link_elem = entry.find(link_tag, atom_ns) if "atom:" in link_tag else entry.find(link_tag)
            if link_elem is not None:
                link = link_elem.get("href", "") or (link_elem.text or "").strip()
                if link:
                    break

        pub_date = _parse_rss_date(
            _get_text(entry, "atom:published", atom_ns) or
            _get_text(entry, "atom:updated", atom_ns) or
            _get_text(entry, "published") or
            _get_text(entry, "updated") or
            _get_text(entry, "{http://www.w3.org/2005/Atom}published") or
            _get_text(entry, "{http://www.w3.org/2005/Atom}updated")
        )
        items.append({
            "source": source_name,
            "title": title,
            "summary": summary,
            "link": link,
            "published": pub_date,
            "is_alert": _is_alert(title, summary),
        })

    # Try RDF/RSS 1.0 (<rdf:RDF><item>)
    if not items:
        rdf_ns = {"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                   "rss": "http://purl.org/rss/1.0/"}
        for entry in root.findall("rss:item", rdf_ns)[:20]:
            title = _strip_html(_get_text(entry, "rss:title", rdf_ns))
            summary = _strip_html(_get_text(entry, "rss:description", rdf_ns))[:500]
            link = _get_text(entry, "rss:link", rdf_ns)
            pub_date = datetime.now(timezone.utc).isoformat()
            items.append({
                "source": source_name,
                "title": title,
                "summary": summary,
                "link": link,
                "published": pub_date,
                "is_alert": _is_alert(title, summary),
            })

    return items


def _fetch_single_feed(name: str, url: str) -> list[dict]:
    """Fetch and parse a single RSS feed."""
    try:
        resp = _session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return _parse_rss_xml(resp.content, name)
    except Exception as e:
        logger.warning("Failed to fetch feed %s: %s", name, e)
        return []


def fetch_all_feeds() -> list[dict]:
    """Fetch all configured RSS feeds in parallel."""
    all_items = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(_fetch_single_feed, name, url): name
            for name, url in config.RSS_FEEDS.items()
        }
        for future in as_completed(futures):
            all_items.extend(future.result())

    # Sort by date (newest first)
    all_items.sort(key=lambda x: x.get("published", ""), reverse=True)
    return all_items


def get_news(force_refresh: bool = False) -> list[dict]:
    """Get news items, using cache when available."""
    if force_refresh:
        items = fetch_all_feeds()
        cache.set("rss_news", items)
        return items
    return cache.get_or_fetch("rss_news", fetch_all_feeds, ttl=config.RSS_REFRESH_INTERVAL)
