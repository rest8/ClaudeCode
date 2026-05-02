"""Playwright-based crawler for omakase.in.

IMPORTANT: omakase.in is a third-party reservation site. The selectors and
URL patterns below are educated guesses based on common patterns for
restaurant booking sites. Before relying on this in production you MUST:

  1. Verify the site's Terms of Service permits this access pattern.
  2. Run `python -m omakase_notifier.crawler.calibrate` (provided) against
     a real listing page and a real restaurant page, and update the
     selectors in `LIST_SELECTORS` / `AVAILABILITY_SELECTORS` to match.

The crawler is deliberately defensive: if a selector fails to match it
returns an empty result rather than crashing the scheduler.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Optional
from urllib.parse import urljoin

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)

from ..models import AvailabilitySlot
from .base import RestaurantInfo

log = logging.getLogger(__name__)

BASE_URL = "https://omakase.in"
LIST_URL_CANDIDATES = [
    "https://omakase.in/r",          # canonical full listing
    "https://omakase.in/ja",
    "https://omakase.in/ja/restaurants",
    "https://omakase.in/",
]

# These selectors are starting points. Run the calibrate script to verify
# them against the live site.
LIST_SELECTORS = {
    # Restaurant detail pages on omakase.in are /r/<lowercase letters + digits>
    # — exclude category links like /r/takeaway?...
    "restaurant_link": 'a[href*="/r/"]',
    "restaurant_name": "h1, h2, .restaurant-name, [data-testid='restaurant-name']",
    "next_page": 'a[rel="next"], a.pagination-next',
}

AVAILABILITY_SELECTORS = {
    # Calendar / slot containers commonly use data-date or aria-label.
    "available_slot": (
        '[data-availability="available"], '
        '.calendar-cell.is-available, '
        'button[data-status="open"]'
    ),
    "slot_datetime_attr": "data-datetime",
    "slot_price_attr": "data-price",
    "party_size_input": 'select[name="party_size"], input[name="party_size"]',
    "cancellation_policy": ".cancellation-policy, [data-testid='cancellation']",
}


class OmakaseCrawler:
    def __init__(
        self,
        headless: bool = True,
        user_agent: str = "OmakaseNotifier/0.1",
        request_timeout_ms: int = 30_000,
    ):
        self.headless = headless
        self.user_agent = user_agent
        self.request_timeout_ms = request_timeout_ms

    @contextmanager
    def _browser(self) -> Iterator[tuple[Playwright, Browser, BrowserContext]]:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless)
            context = browser.new_context(
                user_agent=self.user_agent,
                locale="ja-JP",
                viewport={"width": 1280, "height": 900},
            )
            context.set_default_timeout(self.request_timeout_ms)
            try:
                yield pw, browser, context
            finally:
                context.close()
                browser.close()

    # -------- Restaurant list (daily) --------
    def fetch_restaurant_list(
        self, max_pages: int = 50
    ) -> list[RestaurantInfo]:
        """Fetch the master list of restaurants currently published on
        omakase.in.

        We try a few candidate listing URLs, since the public route may
        change. The result is deduplicated by omakase_id.
        """
        results: dict[str, RestaurantInfo] = {}
        with self._browser() as (_pw, _b, ctx):
            page = ctx.new_page()
            for url in LIST_URL_CANDIDATES:
                try:
                    log.info("Fetching restaurant list from %s", url)
                    page.goto(url, wait_until="domcontentloaded")
                    self._scrape_list_page(page, results, max_pages)
                    if results:
                        break
                except Exception as exc:  # noqa: BLE001
                    log.warning("List URL failed %s: %s", url, exc)
        return list(results.values())

    def _scrape_list_page(
        self, page: Page, results: dict[str, RestaurantInfo], max_pages: int
    ) -> None:
        page.wait_for_load_state("networkidle", timeout=self.request_timeout_ms)
        # omakase.in uses infinite scroll, so scroll to the bottom to
        # force lazy-loaded restaurants into the DOM.
        _scroll_to_bottom(page)
        for _ in range(max_pages):
            anchors = page.query_selector_all(LIST_SELECTORS["restaurant_link"])
            for a in anchors:
                href = a.get_attribute("href")
                if not href:
                    continue
                full_url = urljoin(BASE_URL, href.split("?")[0])
                rid = _extract_restaurant_id(full_url)
                if not rid or rid in results:
                    continue
                text = (a.inner_text() or "").strip()
                name, genre, area = _parse_link_text(text)
                if not name:
                    continue
                results[rid] = RestaurantInfo(
                    omakase_id=rid,
                    name=name,
                    url=full_url,
                    genre=genre,
                    area=area,
                )
            # If a "next page" link is present, follow it (some sub-views).
            next_btn = page.query_selector(LIST_SELECTORS["next_page"])
            if not next_btn:
                return
            try:
                next_btn.click()
                page.wait_for_load_state("networkidle", timeout=self.request_timeout_ms)
                _scroll_to_bottom(page)
            except Exception:  # noqa: BLE001
                return

    # -------- Availability check (per restaurant, per poll) --------
    def check_availability(
        self, restaurant_url: str, party_size: int = 2
    ) -> list[AvailabilitySlot]:
        """Return all currently-available slots for the given restaurant.

        The shape of the calendar UI varies, so this method:
          1. Loads the restaurant page.
          2. Sets the party size if a selector is present.
          3. Reads any element matching AVAILABILITY_SELECTORS["available_slot"].
        """
        slots: list[AvailabilitySlot] = []
        with self._browser() as (_pw, _b, ctx):
            page = ctx.new_page()
            try:
                page.goto(restaurant_url, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle", timeout=self.request_timeout_ms)

                # Try to set party size if the page exposes a selector.
                ps_el = page.query_selector(AVAILABILITY_SELECTORS["party_size_input"])
                if ps_el:
                    try:
                        ps_el.select_option(str(party_size))
                        page.wait_for_load_state("networkidle")
                    except Exception:  # noqa: BLE001
                        pass

                cancellation = _text_or_none(
                    page.query_selector(AVAILABILITY_SELECTORS["cancellation_policy"])
                )

                for el in page.query_selector_all(
                    AVAILABILITY_SELECTORS["available_slot"]
                ):
                    dt_str = el.get_attribute(
                        AVAILABILITY_SELECTORS["slot_datetime_attr"]
                    ) or el.get_attribute("data-date")
                    price_str = el.get_attribute(
                        AVAILABILITY_SELECTORS["slot_price_attr"]
                    )
                    slot_dt = _parse_datetime(dt_str)
                    if not slot_dt:
                        continue
                    slots.append(
                        AvailabilitySlot(
                            slot_datetime=slot_dt,
                            party_size=party_size,
                            price_jpy=_parse_int(price_str),
                            cancellation_policy=cancellation,
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("Availability check failed for %s: %s", restaurant_url, exc)
        return slots


# -------- Helpers --------

# omakase.in restaurant ids look like "qk294214" — letters then digits.
# This deliberately excludes routes like /r/takeaway?togo_type=...
_RESTAURANT_ID_RE = re.compile(r"/r/([a-z]+\d+)(?:[/?#]|$)")
_NAME_PATTERN = re.compile(
    r"^(?P<name>[^\n]+)\n(?P<genre>[^/]+?)\s*/\s*(?P<area>.+?)\s*$",
    re.DOTALL,
)


def _extract_restaurant_id(url: str) -> Optional[str]:
    m = _RESTAURANT_ID_RE.search(url)
    return m.group(1) if m else None


def _parse_link_text(text: str) -> tuple[str, Optional[str], Optional[str]]:
    """Parse omakase.in's anchor text:
        '<店舗名>\\n<ジャンル>  /  <都道府県>'
    Returns (name, genre, area). genre/area may be None if the text is
    just a single line.
    """
    if not text:
        return "", None, None
    text = text.strip()
    m = _NAME_PATTERN.match(text)
    if m:
        return (
            m.group("name").strip(),
            m.group("genre").strip() or None,
            m.group("area").strip() or None,
        )
    return text.split("\n", 1)[0].strip(), None, None


def _scroll_to_bottom(page) -> None:
    """Force omakase.in's infinite-scroll list to fully load."""
    last_count = -1
    for _ in range(40):  # safety cap; ~40 viewports is typically enough
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(700)
        try:
            count = page.evaluate(
                "document.querySelectorAll('a[href*=\"/r/\"]').length"
            )
        except Exception:  # noqa: BLE001
            return
        if count == last_count:
            return
        last_count = count


def _text_or_none(el) -> Optional[str]:
    if el is None:
        return None
    try:
        text = el.inner_text()
    except Exception:  # noqa: BLE001
        return None
    return text.strip() or None


def _parse_datetime(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _parse_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None
