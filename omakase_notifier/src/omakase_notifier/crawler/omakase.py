"""Playwright-based crawler for omakase.in.

IMPORTANT: omakase.in is fronted by Cloudflare. To stay under the bot
threshold we:
  1. Reuse a one-shot manually-bootstrapped session (data/storage_state.json
     produced by setup_session.py). This carries the cf_clearance cookie
     and is good for ~30 days.
  2. Sleep a randomized 5-10s between paginated requests.
  3. Bail out as soon as a Cloudflare interstitial is detected, so we
     don't burn through our reputation.
"""

from __future__ import annotations

import logging
import random
import re
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
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
from .captcha import solve_turnstile

try:
    # Optional dep: tf-playwright-stealth provides ~50 fingerprint patches
    # (TLS-near, canvas, audio, screen, etc.) far beyond our hand-rolled
    # init script. Without it, the fallback _STEALTH_INIT_SCRIPT is used.
    from playwright_stealth import Stealth as _Stealth  # type: ignore
except Exception:  # noqa: BLE001
    _Stealth = None

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

def _profile_dir() -> Path:
    """Persistent Chromium profile path. Stores cookies (cf_clearance),
    local storage, and other browser state across runs."""
    # crawler/omakase.py -> ../../.. = project root (omakase_notifier/)
    return Path(__file__).resolve().parents[3] / "data" / "chrome_profile"


def _is_cloudflare_block(page) -> bool:
    """Detect Cloudflare's block / challenge interstitials so we can
    abort early instead of hammering until the IP is fully banned."""
    try:
        title = (page.title() or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return any(
        s in title
        for s in (
            "just a moment",
            "attention required",
            "cloudflare",
        )
    )


_DEFAULT_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Realistic desktop viewports — picked at random per session to avoid
# the exact-same-pixel-size fingerprint.
_VIEWPORTS = [
    {"width": 1280, "height": 800},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1600, "height": 900},
    {"width": 1920, "height": 1080},
]


def _humanize(page) -> None:
    """Mouse moves + scrolls + small pauses so we don't look like a
    headless bot to behavioral analytics."""
    try:
        viewport = page.viewport_size or {"width": 1280, "height": 800}
        for _ in range(random.randint(2, 4)):
            x = random.randint(80, viewport["width"] - 80)
            y = random.randint(80, viewport["height"] - 80)
            page.mouse.move(x, y, steps=random.randint(8, 22))
            time.sleep(random.uniform(0.15, 0.45))
        for _ in range(random.randint(2, 4)):
            page.mouse.wheel(0, random.randint(180, 700))
            time.sleep(random.uniform(0.3, 0.9))
        # occasional small scroll-back, like a person re-checking
        if random.random() < 0.4:
            page.mouse.wheel(0, -random.randint(80, 250))
            time.sleep(random.uniform(0.2, 0.5))
    except Exception:  # noqa: BLE001
        pass


def _has_turnstile(page) -> bool:
    """True iff a Cloudflare Turnstile challenge widget is on the page."""
    try:
        return page.locator(
            'iframe[src*="challenges.cloudflare.com"], div.cf-turnstile'
        ).count() > 0
    except Exception:  # noqa: BLE001
        return False


def _maybe_solve_turnstile(
    page, provider: str, api_key: str, timeout: int
) -> bool:
    """Detect a Turnstile widget and solve it via the configured 3rd-party
    provider. Returns True if solved, False otherwise."""
    if not (provider and api_key) or not _has_turnstile(page):
        return False
    try:
        sitekey = page.evaluate(
            """() => {
                const f = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
                if (f) {
                    const m = f.src.match(/turnstile\\/.*?\\?.*?[?&]k=([^&]+)/);
                    if (m) return decodeURIComponent(m[1]);
                }
                const d = document.querySelector('[data-sitekey]');
                return d ? d.getAttribute('data-sitekey') : null;
            }"""
        )
        if not sitekey:
            log.warning("Turnstile present but sitekey not found; skipping solver")
            return False
        log.info("Turnstile detected; submitting to %s solver...", provider)
        token = solve_turnstile(provider, api_key, sitekey, page.url, timeout)
        page.evaluate(
            """(t) => {
                const inp = document.querySelector('input[name="cf-turnstile-response"]');
                if (inp) { inp.value = t; }
                if (window.turnstile && typeof window.turnstile.setResponse === 'function') {
                    window.turnstile.setResponse(t);
                }
            }""",
            token,
        )
        # Trigger any onSuccess callback by submitting the surrounding form
        # if there is one; otherwise just wait for navigation.
        try:
            page.evaluate(
                """() => {
                    const f = document.querySelector('form');
                    if (f) f.submit();
                }"""
            )
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_load_state("networkidle", timeout=30_000)
        log.info("Turnstile token injected.")
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Turnstile solve failed: %s", exc)
        return False

# Injected before any page script runs. Hides the standard
# "this is a bot" tells that omakase.in checks for.
_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', {
  get: () => [
    { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
    { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
    { name: 'Native Client', filename: 'internal-nacl-plugin' },
  ],
});
Object.defineProperty(navigator, 'languages', {
  get: () => ['ja-JP', 'ja', 'en-US', 'en'],
});
window.chrome = window.chrome || {
  runtime: {}, loadTimes: function () {}, csi: function () {},
  app: {}
};
const _origPermQuery = navigator.permissions && navigator.permissions.query;
if (_origPermQuery) {
  navigator.permissions.query = function (parameters) {
    return parameters.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission })
      : _origPermQuery(parameters);
  };
}
// WebGL vendor / renderer
const _getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function (parameter) {
  if (parameter === 37445) return 'Intel Inc.';      // UNMASKED_VENDOR_WEBGL
  if (parameter === 37446) return 'Intel Iris OpenGL Engine'; // UNMASKED_RENDERER_WEBGL
  return _getParameter.call(this, parameter);
};
"""

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
        captcha_provider: str = "",
        captcha_api_key: str = "",
        captcha_timeout: int = 180,
        use_cdp: bool = False,
        cdp_url: str = "http://localhost:9222",
    ):
        self.headless = headless
        self.user_agent = user_agent
        self.request_timeout_ms = request_timeout_ms
        self.captcha_provider = captcha_provider
        self.captcha_api_key = captcha_api_key
        self.captcha_timeout = captcha_timeout
        self.use_cdp = use_cdp
        self.cdp_url = cdp_url

    @contextmanager
    def _browser(self) -> Iterator[tuple[Playwright, Optional[Browser], BrowserContext]]:
        """Open a Chromium for crawling. Two modes:

        - CDP attach (use_cdp=True): connect to the user's already-running
          real Chrome at cdp_url. Bypasses Cloudflare because the browser
          is genuinely the user's normal Chrome session, not Playwright's
          bundled Chromium.
        - Persistent profile (default): launch our own Chromium with
          data/chrome_profile/ as the user data dir + tf-playwright-stealth.
        """
        if self.use_cdp:
            with sync_playwright() as pw:
                try:
                    browser = pw.chromium.connect_over_cdp(self.cdp_url)
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(
                        f"CDP connect to {self.cdp_url} failed: {exc}. "
                        "Run scripts\\start_chrome_for_omakase.bat first "
                        "to launch Chrome with --remote-debugging-port=9222."
                    ) from exc
                # Use the existing default context if Chrome already has
                # one (which it always does on first launch).
                if browser.contexts:
                    context = browser.contexts[0]
                else:
                    context = browser.new_context(
                        locale="ja-JP", timezone_id="Asia/Tokyo"
                    )
                context.set_default_timeout(self.request_timeout_ms)
                try:
                    yield pw, browser, context
                finally:
                    # Disconnect (does NOT close the user's Chrome).
                    try:
                        browser.close()
                    except Exception:  # noqa: BLE001
                        pass
            return

        with sync_playwright() as pw:
            profile = _profile_dir()
            profile.mkdir(parents=True, exist_ok=True)
            ua = self.user_agent or ""
            if (
                "Mozilla" not in ua
                or "HeadlessChrome" in ua
                or "OmakaseNotifier" in ua
            ):
                ua = _DEFAULT_BROWSER_UA
            # Random viewport in a realistic range — frozen-viewport is
            # a fingerprinting tell.
            viewport = random.choice(_VIEWPORTS)
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--lang=ja-JP",
                ],
                user_agent=ua,
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
                geolocation={"longitude": 139.6917, "latitude": 35.6895},
                permissions=["geolocation"],
                viewport=viewport,
                screen=viewport,
                color_scheme="light",
            )
            # Apply tf-playwright-stealth's comprehensive patches if the
            # package is installed; otherwise fall back to our hand-rolled
            # init script. Stealth() covers ~50 fingerprint vectors that
            # the manual script does not.
            if _Stealth is not None:
                try:
                    _Stealth().apply_stealth_sync(context)
                except Exception as exc:  # noqa: BLE001
                    log.debug("tf-playwright-stealth failed (%s); using fallback init", exc)
                    context.add_init_script(_STEALTH_INIT_SCRIPT)
            else:
                context.add_init_script(_STEALTH_INIT_SCRIPT)
            context.set_default_timeout(self.request_timeout_ms)
            try:
                # launch_persistent_context returns the context directly;
                # there's no separate Browser handle. Yield None for it
                # so the (_pw, _b, ctx) unpacking elsewhere keeps working.
                yield pw, None, context
            finally:
                context.close()

    # -------- Cookie warm-up --------
    def warmup(self) -> None:
        """Visit omakase.in briefly to keep cf_clearance fresh. Run on
        a slow schedule (every several hours) so Cloudflare sees regular
        human-like activity from the persistent profile."""
        log.info("Warming up Cloudflare session...")
        try:
            with self._browser() as (_pw, _b, ctx):
                page = ctx.new_page()
                try:
                    page.goto(f"{BASE_URL}/r", wait_until="domcontentloaded")
                    page.wait_for_load_state(
                        "networkidle", timeout=self.request_timeout_ms
                    )
                    if _is_cloudflare_block(page):
                        log.warning(
                            "Warmup hit Cloudflare block. The persistent "
                            "profile may need to be re-bootstrapped via "
                            "setup_session.py."
                        )
                    else:
                        # Linger a bit so it looks like real reading time.
                        time.sleep(random.uniform(20, 35))
                        log.info("Warmup OK.")
                finally:
                    page.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("Warmup failed: %s", exc)

    # -------- Restaurant list (daily) --------
    def fetch_restaurant_list(
        self, max_pages: int = 50
    ) -> list[RestaurantInfo]:
        """Fetch the master list of restaurants currently published on
        omakase.in.

        Strategy: walk /r pagination first (gets nice card text with
        name/genre/area for ~660 popular cards), then probe sitemap.xml
        and visit any /r/<id> pages we haven't seen yet (catches the
        long tail). Results are deduplicated by omakase_id.

        Each pagination request is opened in a *fresh* page (tab). This
        matches the calibrate.py path that demonstrably gets distinct
        content per page; reusing the SPA-resident page after the
        initial /r load tends to leave omakase rendering page 1.
        """
        results: dict[str, RestaurantInfo] = {}
        with self._browser() as (_pw, _b, ctx):
            # 1) Page 1 — also reads the pagination link to find max N.
            page = ctx.new_page()
            for url in LIST_URL_CANDIDATES:
                try:
                    log.info("Fetching restaurant list from %s", url)
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_load_state(
                        "networkidle", timeout=self.request_timeout_ms
                    )
                    if _maybe_solve_turnstile(
                        page,
                        self.captcha_provider,
                        self.captcha_api_key,
                        self.captcha_timeout,
                    ):
                        page.wait_for_load_state(
                            "networkidle", timeout=self.request_timeout_ms
                        )
                    _humanize(page)
                    _scroll_to_bottom(page)
                    before = len(results)
                    self._collect_items(page, results)
                    if results:
                        log.info(
                            "Page 1 (%s): %d items", page.url, len(results) - before
                        )
                        break
                except Exception as exc:  # noqa: BLE001
                    log.warning("List URL failed %s: %s", url, exc)
            max_page = _find_max_page(page)
            log.info("Pagination: max page = %d", max_page)
            page.close()

            # 2) Pages 2..N — open each in a fresh tab so the SPA can't
            #    reuse cached state. Sleep 5-10s between requests and
            #    bail out at the first Cloudflare block to avoid
            #    triggering a longer ban.
            cf_blocked = False
            for n in range(2, min(max_page, max_pages) + 1):
                # Random pacing — this is the single most important
                # thing for staying under CF's bot threshold.
                time.sleep(random.uniform(5.0, 10.0))
                np = ctx.new_page()
                url = f"{BASE_URL}/r/page/{n}"
                try:
                    np.goto(url, wait_until="domcontentloaded")
                    np.wait_for_load_state(
                        "networkidle", timeout=self.request_timeout_ms
                    )
                    # Try to clear Turnstile if it appeared and a solver
                    # is configured.
                    if _maybe_solve_turnstile(
                        np,
                        self.captcha_provider,
                        self.captcha_api_key,
                        self.captcha_timeout,
                    ):
                        np.wait_for_load_state(
                            "networkidle", timeout=self.request_timeout_ms
                        )
                    if _is_cloudflare_block(np):
                        log.error(
                            "Page %d: Cloudflare block detected (title=%r). "
                            "Stopping bulk crawl. Re-run setup_session.py "
                            "to refresh the cf_clearance cookie, then wait "
                            "an hour or so before retrying.",
                            n,
                            np.title(),
                        )
                        cf_blocked = True
                        break
                    _humanize(np)
                    _scroll_to_bottom(np)
                    before = len(results)
                    self._collect_items(np, results)
                    log.info(
                        "Page %d (%s): %d new (total %d)",
                        n,
                        np.url,
                        len(results) - before,
                        len(results),
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("Page %d failed: %s", n, exc)
                finally:
                    np.close()

            log.info(
                "After pagination: %d restaurants%s",
                len(results),
                " (truncated by Cloudflare)" if cf_blocked else "",
            )

            if cf_blocked:
                # Don't pile on — sitemap and detail-fetch will get
                # blocked too and may extend the ban.
                return list(results.values())

            # 3) Sitemap fallback — discover IDs the listing didn't show.
            try:
                helper = ctx.new_page()
                try:
                    helper.goto(BASE_URL, wait_until="domcontentloaded")
                    sitemap_ids = self._discover_via_sitemap(helper)
                    missing = sorted(sitemap_ids - set(results.keys()))
                    if missing:
                        log.info(
                            "Sitemap discovered %d additional restaurant id(s); "
                            "fetching their pages...",
                            len(missing),
                        )
                        for i, rid in enumerate(missing, 1):
                            time.sleep(random.uniform(3.0, 6.0))
                            info = self._fetch_one_restaurant(helper, rid)
                            if _is_cloudflare_block(helper):
                                log.error(
                                    "Detail fetch hit Cloudflare at #%d/%d; "
                                    "stopping. Remaining IDs registered with "
                                    "placeholder names.",
                                    i,
                                    len(missing),
                                )
                                for rrid in missing[i - 1 :]:
                                    if rrid not in results:
                                        results[rrid] = RestaurantInfo(
                                            omakase_id=rrid,
                                            name=rrid,
                                            url=f"{BASE_URL}/r/{rrid}",
                                        )
                                break
                            if info is not None:
                                results[rid] = info
                            else:
                                results[rid] = RestaurantInfo(
                                    omakase_id=rid,
                                    name=rid,
                                    url=f"{BASE_URL}/r/{rid}",
                                )
                            if i % 25 == 0:
                                log.info(
                                    "Detail fetch progress: %d / %d",
                                    i,
                                    len(missing),
                                )
                    else:
                        log.info("Sitemap added no new restaurants.")
                finally:
                    helper.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("Sitemap discovery failed: %s", exc)

        return list(results.values())

    def _discover_via_sitemap(self, page: Page) -> set[str]:
        """Walk sitemap.xml (and any nested <sitemap> entries) to find
        every /r/<id> URL that omakase.in publishes."""
        seen_sitemaps: set[str] = set()
        ids: set[str] = set()
        queue = [
            f"{BASE_URL}/sitemap.xml",
            f"{BASE_URL}/sitemap_index.xml",
            f"{BASE_URL}/sitemaps/restaurants.xml",
        ]
        while queue:
            sm_url = queue.pop(0)
            if sm_url in seen_sitemaps:
                continue
            seen_sitemaps.add(sm_url)
            text = self._fetch_text(page, sm_url)
            if not text:
                continue
            for m in re.finditer(r"<loc>\s*([^<\s]+)\s*</loc>", text):
                loc = m.group(1)
                if loc.endswith(".xml"):
                    queue.append(loc)
                    continue
                rid = _extract_restaurant_id(loc)
                if rid:
                    ids.add(rid)
        return ids

    def _fetch_text(self, page: Page, url: str) -> Optional[str]:
        """Use the page's authenticated fetch() to retrieve a URL as
        text. Returns None on any error (404, network, blocked, etc.)."""
        try:
            return page.evaluate(
                """async (u) => {
                    try {
                        const r = await fetch(u, { credentials: 'include' });
                        if (!r.ok) return null;
                        return await r.text();
                    } catch (e) { return null; }
                }""",
                url,
            )
        except Exception:  # noqa: BLE001
            return None

    def _fetch_one_restaurant(
        self, page: Page, rid: str
    ) -> Optional[RestaurantInfo]:
        """Visit a single restaurant page to extract name/genre/area
        metadata. Used for IDs we discovered via sitemap but not in /r."""
        url = f"{BASE_URL}/r/{rid}"
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_load_state(
                "networkidle", timeout=self.request_timeout_ms
            )
            data = page.evaluate(
                """() => {
                    const og = document.querySelector('meta[property="og:title"]');
                    const t  = (og && og.content)
                            || (document.querySelector('h1') && document.querySelector('h1').innerText)
                            || document.title || '';
                    // Genre / area sometimes appear in breadcrumbs or list items.
                    const breadcrumbs = Array.from(
                        document.querySelectorAll('nav.breadcrumb a, .breadcrumb a, ol.breadcrumb a')
                    ).map(a => a.innerText.trim()).filter(Boolean);
                    return { title: t.trim(), breadcrumbs };
                }"""
            )
            title = (data.get("title") if isinstance(data, dict) else "") or rid
            crumbs = data.get("breadcrumbs", []) if isinstance(data, dict) else []
            area = next(
                (c for c in crumbs if c.endswith("都") or c.endswith("府") or c.endswith("県") or c.endswith("道")),
                None,
            )
            genre = None
            if crumbs:
                # last non-area crumb is often the genre
                rest = [c for c in crumbs if c != area]
                if rest:
                    genre = rest[-1]
            return RestaurantInfo(
                omakase_id=rid, name=title, url=url, area=area, genre=genre
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("fetch_one_restaurant(%s) failed: %s", rid, exc)
            return None

    def _collect_items(
        self, page: Page, results: dict[str, RestaurantInfo]
    ) -> None:
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


_LIST_PAGE_RE = re.compile(r"/r/page/(\d+)")


def _find_max_page(page) -> int:
    """Return the highest /r/page/<N> number visible on the page,
    or 1 if no pagination is present."""
    pages = [1]
    for a in page.query_selector_all('a[href*="/r/page/"]'):
        href = a.get_attribute("href") or ""
        m = _LIST_PAGE_RE.search(href)
        if m:
            pages.append(int(m.group(1)))
    return max(pages)


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
