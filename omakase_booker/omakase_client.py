"""Omakase.in browser automation for reservation booking.

Uses Playwright for browser automation since Omakase does not provide a public API.

IMPORTANT: Omakase (omakase.in) の利用規約ではボットや自動操作が禁止されています。
本ツールは学習・個人利用目的で作成されています。利用は自己責任で行ってください。
アカウント停止等のリスクがあることをご理解の上ご使用ください。

The flow:
  1. Log in to omakase.in
  2. Navigate to the target restaurant page
  3. Detect reservation open time from restaurant page
  4. Check available dates/times (or enter lottery for lottery-based restaurants)
  5. Select matching slot, confirm booking, and complete payment
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page, Browser, BrowserContext

from .config import Config, RestaurantInfo, RestaurantTarget

logger = logging.getLogger(__name__)

OMAKASE_BASE_URL = "https://omakase.in"
LOGIN_URL = f"{OMAKASE_BASE_URL}/users/sign_in"


class OmakaseBookingError(Exception):
    """Raised when booking fails."""


class OmakaseClient:
    """Automated client for Omakase.in reservations."""

    # Resource types to block for faster page loads
    BLOCKED_RESOURCE_TYPES = {"image", "font", "media"}
    # URL patterns to block (analytics, tracking, ads)
    BLOCKED_URL_PATTERNS = [
        "google-analytics.com", "googletagmanager.com",
        "facebook.net", "doubleclick.net", "ads",
        "analytics", "tracking", ".woff", ".woff2",
    ]

    def __init__(self, config: Config):
        self.config = config
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._extra_contexts: list[BrowserContext] = []

    async def start(self):
        """Launch browser and log in."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
        )
        self._context = await self._new_context()
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.config.browser_timeout_ms)
        await self._login()

    async def _new_context(self) -> BrowserContext:
        """Create a new browser context with shared settings and optional resource blocking."""
        context = await self._browser.new_context(
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        if self.config.block_unnecessary_resources:
            await context.route("**/*", self._block_unnecessary)
        return context

    @staticmethod
    async def _block_unnecessary(route):
        """Abort requests for images, fonts, and tracking scripts."""
        req = route.request
        if req.resource_type in OmakaseClient.BLOCKED_RESOURCE_TYPES:
            await route.abort()
            return
        url = req.url.lower()
        for pattern in OmakaseClient.BLOCKED_URL_PATTERNS:
            if pattern in url:
                await route.abort()
                return
        await route.continue_()

    async def create_parallel_page(self) -> Page:
        """Create an isolated page (in a new context) for parallel operations.

        The page shares the same browser instance and login cookies.
        Caller should close the returned page when done via close_parallel_page().
        """
        ctx = await self._new_context()
        # Copy cookies from main context so the parallel page is logged in
        cookies = await self._context.cookies()
        await ctx.add_cookies(cookies)
        self._extra_contexts.append(ctx)
        page = await ctx.new_page()
        page.set_default_timeout(self.config.browser_timeout_ms)
        return page

    async def close_parallel_page(self, page: Page):
        """Close a parallel page and its context."""
        ctx = page.context
        await ctx.close()
        if ctx in self._extra_contexts:
            self._extra_contexts.remove(ctx)

    async def close(self):
        """Clean up browser resources."""
        for ctx in self._extra_contexts:
            try:
                await ctx.close()
            except Exception:
                pass
        self._extra_contexts.clear()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _login(self):
        """Log in to Omakase."""
        page = self._page
        logger.info("Logging in to Omakase...")

        await page.goto(LOGIN_URL)
        await page.wait_for_load_state("networkidle")

        # Fill login form
        email_input = page.locator('input[type="email"], input[name="email"]')
        if await email_input.count() == 0:
            email_input = page.locator('input[type="text"]').first
        await email_input.fill(self.config.omakase_email)

        password_input = page.locator('input[type="password"]')
        await password_input.fill(self.config.omakase_password)

        # Submit
        submit_btn = page.locator(
            'button[type="submit"], input[type="submit"]'
        )
        if await submit_btn.count() == 0:
            submit_btn = page.locator("button").filter(has_text=re.compile(r"ログイン|Sign in|Login", re.IGNORECASE))
        await submit_btn.first.click()
        await page.wait_for_load_state("networkidle")

        # Verify login succeeded
        if "sign_in" in page.url.lower() or "login" in page.url.lower():
            raise OmakaseBookingError(
                "Login failed. Check your email and password in config."
            )
        logger.info("Login successful.")

    async def detect_reservation_open_time(
        self,
        restaurant: RestaurantTarget,
    ) -> str | None:
        """Detect the reservation open time from a restaurant's page.

        Omakase restaurant pages typically display when reservations open,
        e.g. "予約開始: 2026-04-01 10:00" or "Reservations open at 10:00".

        Returns:
            ISO datetime string (YYYY-MM-DDTHH:MM) if detected, None otherwise.
        """
        page = self._page
        logger.info("Detecting reservation open time for: %s", restaurant.name)

        await page.goto(restaurant.omakase_url)
        await page.wait_for_load_state("networkidle")

        body_text = await page.locator("body").text_content()
        if not body_text:
            return None

        # Pattern 1: "予約開始 YYYY年M月D日 HH:MM" or "予約開始 YYYY/MM/DD HH:MM"
        patterns = [
            r"予約開始[:\s]*(\d{4})[年/\-](\d{1,2})[月/\-](\d{1,2})[日]?\s*(\d{1,2}):(\d{2})",
            r"Reservations?\s+open[:\s]*(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})\s+(\d{1,2}):(\d{2})",
            r"受付開始[:\s]*(\d{4})[年/\-](\d{1,2})[月/\-](\d{1,2})[日]?\s*(\d{1,2}):(\d{2})",
        ]

        for pattern in patterns:
            m = re.search(pattern, body_text)
            if m:
                y, mo, d, h, mi = m.groups()
                open_time = f"{y}-{int(mo):02d}-{int(d):02d}T{int(h):02d}:{int(mi):02d}"
                logger.info("Detected reservation open time: %s", open_time)
                return open_time

        # Pattern 2: Just time, e.g. "10:00 予約開始" or "10:00に予約受付開始"
        time_patterns = [
            r"(\d{1,2}):(\d{2})\s*(?:に)?(?:予約|受付)(?:開始|受付開始)",
            r"(?:予約|受付)(?:開始|受付開始)[:\s]*(\d{1,2}):(\d{2})",
        ]
        for pattern in time_patterns:
            m = re.search(pattern, body_text)
            if m:
                h, mi = m.groups()
                # Return time-only (caller decides the date)
                time_str = f"{int(h):02d}:{int(mi):02d}"
                logger.info("Detected reservation open time (time only): %s", time_str)
                return time_str

        logger.info("Could not detect reservation open time for %s", restaurant.name)
        return None

    async def scrape_cancellation_policy(
        self,
        restaurant: RestaurantTarget,
    ) -> str:
        """Scrape the cancellation policy from a restaurant's page.

        Returns:
            Cancellation policy text, or a default message if not found.
        """
        page = self._page
        logger.info("Scraping cancellation policy for: %s", restaurant.name)

        # Navigate only if we're not already on the restaurant page
        if restaurant.omakase_url not in page.url:
            await page.goto(restaurant.omakase_url)
            await page.wait_for_load_state("networkidle")

        # Try known selectors for cancellation policy sections
        policy_selectors = [
            '[class*="cancel"]',
            '[class*="policy"]',
            '[id*="cancel"]',
            '[id*="policy"]',
            'section:has-text("キャンセル")',
            'div:has-text("キャンセルポリシー")',
        ]

        for selector in policy_selectors:
            el = page.locator(selector)
            if await el.count() > 0:
                text = await el.first.text_content()
                if text and "キャンセル" in text:
                    policy = text.strip()
                    # Trim to reasonable length
                    if len(policy) > 500:
                        policy = policy[:500] + "..."
                    logger.info("Found cancellation policy for %s", restaurant.name)
                    return policy

        # Fallback: search full page text for cancellation-related content
        body_text = await page.locator("body").text_content() or ""

        # Extract cancellation policy section from body text
        cancel_patterns = [
            # "キャンセルポリシー" section
            r"(キャンセルポリシー[ー：:\s]*[^\n]*(?:\n[^\n]*){0,5})",
            # "キャンセル料" details
            r"(キャンセル料[^。]*。(?:[^。]*キャンセル[^。]*。)*)",
            # "Cancel" in English
            r"(Cancellation\s+Policy[:\s]*[^\n]*(?:\n[^\n]*){0,5})",
            # Specific fee patterns like "前日50% 当日100%"
            r"((?:前日|当日|(\d+)日前)[^。\n]*(?:キャンセル|%|円|fee)[^。\n]*)",
        ]

        for pattern in cancel_patterns:
            m = re.search(pattern, body_text)
            if m:
                policy = m.group(1).strip()
                if len(policy) > 500:
                    policy = policy[:500] + "..."
                logger.info("Found cancellation policy (regex) for %s", restaurant.name)
                return policy

        logger.info("No cancellation policy found for %s", restaurant.name)
        return "キャンセルポリシー情報を取得できませんでした。Omakase のレストランページをご確認ください。"

    # ── Restaurant Browsing / Discovery ──────────────────────

    async def discover_browse_urls(self) -> dict[str, list[dict[str, str]]]:
        """Discover available region and genre browsing URLs from the Omakase site.

        Returns:
            Dict with keys "areas" and "genres", each a list of {name, url} dicts.
        """
        page = self._page
        logger.info("Discovering browse URLs from Omakase top page...")

        await page.goto(OMAKASE_BASE_URL)
        await page.wait_for_load_state("networkidle")

        result: dict[str, list[dict[str, str]]] = {"areas": [], "genres": []}

        # Find all links in the page
        all_links = page.locator("a[href]")
        count = await all_links.count()

        for i in range(count):
            el = all_links.nth(i)
            href = await el.get_attribute("href") or ""
            text = (await el.text_content() or "").strip()
            if not text or not href:
                continue

            # Normalize URL
            if href.startswith("/"):
                href = f"{OMAKASE_BASE_URL}{href}"

            # Area links: /ja/area/*, /area/*, or links with area-like patterns
            if "/area/" in href or "/region/" in href or "/エリア/" in href:
                result["areas"].append({"name": text, "url": href})
            # Genre links: /ja/genre/*, /genre/*, /cuisine/*
            elif "/genre/" in href or "/cuisine/" in href or "/ジャンル/" in href:
                result["genres"].append({"name": text, "url": href})

        # Fallback: try to find navigation/category sections
        if not result["areas"] and not result["genres"]:
            nav_links = page.locator(
                'nav a[href], [class*="category"] a[href], '
                '[class*="area"] a[href], [class*="genre"] a[href], '
                '[class*="nav"] a[href]'
            )
            nav_count = await nav_links.count()
            for i in range(nav_count):
                el = nav_links.nth(i)
                href = await el.get_attribute("href") or ""
                text = (await el.text_content() or "").strip()
                if not text or not href:
                    continue
                if href.startswith("/"):
                    href = f"{OMAKASE_BASE_URL}{href}"
                # Heuristic: Japanese region names
                area_keywords = ["東京", "大阪", "京都", "名古屋", "福岡", "北海道", "神戸",
                                 "横浜", "銀座", "六本木", "渋谷", "新宿", "赤坂", "恵比寿",
                                 "麻布", "青山", "西麻布", "表参道", "広尾"]
                genre_keywords = ["鮨", "寿司", "天ぷら", "天麩羅", "懐石", "割烹", "焼鳥",
                                  "焼肉", "フレンチ", "イタリアン", "中華", "和食", "鉄板焼",
                                  "うなぎ", "蕎麦", "日本料理", "Sushi", "Tempura"]
                if any(k in text for k in area_keywords):
                    result["areas"].append({"name": text, "url": href})
                elif any(k in text for k in genre_keywords):
                    result["genres"].append({"name": text, "url": href})

        # Deduplicate
        for key in ("areas", "genres"):
            seen = set()
            deduped = []
            for item in result[key]:
                if item["url"] not in seen:
                    seen.add(item["url"])
                    deduped.append(item)
            result[key] = deduped

        logger.info("Found %d areas, %d genres", len(result["areas"]), len(result["genres"]))
        return result

    async def browse_restaurants(self, listing_url: str) -> list[RestaurantInfo]:
        """Browse a restaurant listing page and extract restaurant info.

        Args:
            listing_url: URL of the listing page (area or genre page).

        Returns:
            List of RestaurantInfo for restaurants found on the page.
        """
        page = self._page
        logger.info("Browsing restaurants at: %s", listing_url)

        await page.goto(listing_url)
        await page.wait_for_load_state("networkidle")

        restaurants: list[RestaurantInfo] = []

        # Strategy 1: Look for restaurant cards/links with /r/ pattern
        restaurant_links = page.locator('a[href*="/r/"]')
        count = await restaurant_links.count()
        logger.info("Found %d restaurant links", count)

        seen_urls: set[str] = set()
        for i in range(count):
            el = restaurant_links.nth(i)
            href = await el.get_attribute("href") or ""
            if not href:
                continue
            if href.startswith("/"):
                href = f"{OMAKASE_BASE_URL}{href}"
            # Only include actual restaurant pages
            if "/r/" not in href:
                continue
            # Deduplicate by URL
            base_url = href.split("?")[0].rstrip("/")
            if base_url in seen_urls:
                continue
            seen_urls.add(base_url)

            # Try to extract info from the card/surrounding context
            name = ""
            # First try: the link text itself
            link_text = (await el.text_content() or "").strip()

            # Try to find the parent card element
            parent = el
            card = None
            for _ in range(4):  # Walk up the DOM tree
                parent = parent.locator("..")
                parent_class = await parent.get_attribute("class") or ""
                parent_tag = await parent.evaluate("el => el.tagName.toLowerCase()")
                if any(kw in parent_class.lower() for kw in ("card", "item", "restaurant", "shop", "store")):
                    card = parent
                    break
                if parent_tag in ("li", "article"):
                    card = parent
                    break

            if card:
                # Extract name from heading inside card
                heading = card.locator("h1, h2, h3, h4, h5, h6, [class*='name'], [class*='title']")
                if await heading.count() > 0:
                    name = (await heading.first.text_content() or "").strip()

                # Extract price
                price_el = card.locator("[class*='price'], :has-text('¥'), :has-text('円')")
                price = ""
                if await price_el.count() > 0:
                    price = (await price_el.first.text_content() or "").strip()

                # Extract area/genre from card metadata
                meta_el = card.locator("[class*='area'], [class*='region'], [class*='genre'], [class*='category'], [class*='tag']")
                area = ""
                genre = ""
                for j in range(min(await meta_el.count(), 5)):
                    meta_text = (await meta_el.nth(j).text_content() or "").strip()
                    meta_class = (await meta_el.nth(j).get_attribute("class") or "").lower()
                    if "area" in meta_class or "region" in meta_class:
                        area = meta_text
                    elif "genre" in meta_class or "category" in meta_class:
                        genre = meta_text

                # Extract image
                img_el = card.locator("img")
                image_url = ""
                if await img_el.count() > 0:
                    image_url = await img_el.first.get_attribute("src") or ""
                    if image_url.startswith("/"):
                        image_url = f"{OMAKASE_BASE_URL}{image_url}"

                # Extract description
                desc_el = card.locator("[class*='desc'], [class*='text'], p")
                description = ""
                if await desc_el.count() > 0:
                    description = (await desc_el.first.text_content() or "").strip()[:200]

                restaurants.append(RestaurantInfo(
                    name=name or link_text or base_url.split("/r/")[-1],
                    url=base_url,
                    area=area,
                    genre=genre,
                    price_range=price,
                    image_url=image_url,
                    description=description,
                ))
            else:
                # Minimal info from just the link
                restaurants.append(RestaurantInfo(
                    name=link_text or base_url.split("/r/")[-1],
                    url=base_url,
                ))

        # If no /r/ links found, try broader approach
        if not restaurants:
            logger.info("No /r/ links found, trying broader search...")
            cards = page.locator(
                '[class*="restaurant"], [class*="shop"], [class*="store"], '
                '[class*="card"], article, [class*="item"]'
            )
            card_count = await cards.count()
            for i in range(min(card_count, 50)):
                card = cards.nth(i)
                link = card.locator("a[href]").first
                if await link.count() == 0:
                    continue
                href = await link.get_attribute("href") or ""
                if href.startswith("/"):
                    href = f"{OMAKASE_BASE_URL}{href}"
                if href in seen_urls:
                    continue
                seen_urls.add(href)

                heading = card.locator("h1, h2, h3, h4, h5, h6")
                name = ""
                if await heading.count() > 0:
                    name = (await heading.first.text_content() or "").strip()

                if name:
                    restaurants.append(RestaurantInfo(name=name, url=href))

        # Handle pagination - try to load more
        next_page = page.locator(
            'a:has-text("次"), a:has-text("次へ"), a:has-text("Next"), '
            '[class*="next"], [rel="next"]'
        )
        has_more = await next_page.count() > 0

        logger.info(
            "Found %d restaurants on page (has_more=%s)",
            len(restaurants), has_more,
        )
        return restaurants

    async def browse_restaurants_all_pages(
        self, listing_url: str, max_pages: int = 10
    ) -> list[RestaurantInfo]:
        """Browse all pages of a restaurant listing.

        Args:
            listing_url: Starting URL of the listing.
            max_pages: Maximum number of pages to fetch.

        Returns:
            All restaurants found across pages.
        """
        all_restaurants: list[RestaurantInfo] = []
        current_url = listing_url
        seen_urls: set[str] = set()

        for page_num in range(max_pages):
            page = self._page
            logger.info("Browsing page %d: %s", page_num + 1, current_url)

            restaurants = await self.browse_restaurants(current_url)
            new_count = 0
            for r in restaurants:
                if r.url not in seen_urls:
                    seen_urls.add(r.url)
                    all_restaurants.append(r)
                    new_count += 1

            if new_count == 0:
                break

            # Try to find next page link
            next_link = page.locator(
                'a:has-text("次"), a:has-text("次へ"), a:has-text("Next"), '
                '[class*="next"]:not([class*="disabled"]), [rel="next"]'
            )
            if await next_link.count() == 0:
                break

            next_href = await next_link.first.get_attribute("href")
            if not next_href:
                break
            if next_href.startswith("/"):
                next_href = f"{OMAKASE_BASE_URL}{next_href}"
            current_url = next_href

        logger.info("Total restaurants found: %d across %d pages", len(all_restaurants), page_num + 1)
        return all_restaurants

    async def search_restaurants(self, query: str) -> list[RestaurantInfo]:
        """Search for restaurants on Omakase by keyword.

        Args:
            query: Search keyword (restaurant name, area, cuisine, etc.)

        Returns:
            List of matching restaurants.
        """
        page = self._page
        logger.info("Searching restaurants for: %s", query)

        await page.goto(OMAKASE_BASE_URL)
        await page.wait_for_load_state("networkidle")

        # Try to find and use search input
        search_input = page.locator(
            'input[type="search"], input[name*="search"], input[name*="q"], '
            'input[placeholder*="検索"], input[placeholder*="Search"], '
            'input[class*="search"]'
        )

        if await search_input.count() > 0:
            await search_input.first.fill(query)
            # Submit search
            await search_input.first.press("Enter")
            await page.wait_for_load_state("networkidle")
            return await self.browse_restaurants(page.url)

        # Fallback: try URL-based search
        search_urls = [
            f"{OMAKASE_BASE_URL}/search?q={query}",
            f"{OMAKASE_BASE_URL}/ja/search?q={query}",
            f"{OMAKASE_BASE_URL}/restaurants?q={query}",
        ]
        for url in search_urls:
            await page.goto(url)
            await page.wait_for_load_state("networkidle")
            results = await self.browse_restaurants(page.url)
            if results:
                return results

        logger.info("No search results found for: %s", query)
        return []

    async def check_availability(
        self,
        restaurant: RestaurantTarget,
    ) -> list[dict]:
        """Check available reservation slots for a restaurant.

        Returns:
            List of dicts with keys: date, time, course (if any), element_index
        """
        page = self._page
        logger.info("Checking availability for: %s", restaurant.name)

        await page.goto(restaurant.omakase_url)
        await page.wait_for_load_state("networkidle")

        available_slots = []

        # Look for available date/time slots on the page
        date_elements = page.locator(
            '[class*="available"], [class*="open"], '
            'a[href*="reserve"], button:not([disabled])'
        ).filter(has_text=re.compile(r"\d{1,2}月\d{1,2}日|\d{4}[-/]\d{2}[-/]\d{2}"))

        count = await date_elements.count()
        logger.info("Found %d potential date elements", count)

        for i in range(count):
            el = date_elements.nth(i)
            text = await el.text_content()
            if text:
                slot_info = self._parse_slot_text(text.strip())
                if slot_info:
                    slot_info["element_index"] = i
                    available_slots.append(slot_info)

        # Also check for time-based slot listings
        time_slots = page.locator(
            '[class*="time-slot"], [class*="slot"], [class*="reservation"]'
        )
        time_count = await time_slots.count()

        for i in range(time_count):
            el = time_slots.nth(i)
            text = await el.text_content()
            if text:
                slot_info = self._parse_slot_text(text.strip())
                if slot_info and slot_info not in available_slots:
                    slot_info["element_index"] = count + i
                    available_slots.append(slot_info)

        logger.info(
            "Restaurant %s: %d available slots found",
            restaurant.name,
            len(available_slots),
        )
        return available_slots

    def _parse_slot_text(self, text: str) -> dict | None:
        """Parse date/time information from slot text."""
        result = {}

        # Try to extract date: 2024年3月15日 or 3月15日 or 2024-03-15 or 3/15
        date_patterns = [
            r"(\d{4})年(\d{1,2})月(\d{1,2})日",
            r"(\d{1,2})月(\d{1,2})日",
            r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})",
        ]
        for pattern in date_patterns:
            m = re.search(pattern, text)
            if m:
                groups = m.groups()
                if len(groups) == 3:
                    result["date"] = f"{groups[0]}-{int(groups[1]):02d}-{int(groups[2]):02d}"
                elif len(groups) == 2:
                    year = datetime.now().year
                    result["date"] = f"{year}-{int(groups[0]):02d}-{int(groups[1]):02d}"
                break

        # Try to extract time: 18:00, 18時
        time_match = re.search(r"(\d{1,2}):(\d{2})", text)
        if not time_match:
            time_match = re.search(r"(\d{1,2})時(\d{0,2})", text)
        if time_match:
            hour = time_match.group(1)
            minute = time_match.group(2) if time_match.group(2) else "00"
            result["time"] = f"{int(hour):02d}:{int(minute):02d}"

        if "date" in result or "time" in result:
            result.setdefault("course", None)
            return result
        return None

    async def reserve_slot(
        self,
        restaurant: RestaurantTarget,
        target_date: str,
        target_time: str,
    ) -> bool:
        """Reserve a slot (confirm booking) WITHOUT completing payment.

        This selects the slot and confirms the reservation up to the payment step.
        Call complete_payment() separately after approval is obtained.

        Args:
            restaurant: Target restaurant config.
            target_date: Date string (YYYY-MM-DD).
            target_time: Time string (HH:MM).

        Returns:
            True if reservation was confirmed (ready for payment).
        """
        page = self._page
        logger.info(
            "Reserving %s on %s at %s (party: %d)",
            restaurant.name,
            target_date,
            target_time,
            restaurant.party_size,
        )

        await page.goto(restaurant.omakase_url)
        await page.wait_for_load_state("networkidle")

        # Step 1: Select party size if available
        party_selector = page.locator(
            'select[name*="party"], select[name*="person"], '
            'select[name*="guest"], select[name*="人数"]'
        )
        if await party_selector.count() > 0:
            await party_selector.first.select_option(str(restaurant.party_size))
            logger.info("Selected party size: %d", restaurant.party_size)

        # Step 2: Navigate to the target date
        await self._navigate_to_date(target_date)

        # Step 3: Select the target time slot
        time_selected = await self._select_time_slot(target_time)
        if not time_selected:
            logger.warning("Could not find time slot %s", target_time)
            return False

        # Step 4: Select course if specified
        if restaurant.course_keyword:
            await self._select_course(restaurant.course_keyword)

        # Step 5: Confirm the reservation (but do NOT pay yet)
        confirmed = await self._confirm_booking()
        if not confirmed:
            return False

        logger.info("Slot reserved, awaiting payment approval...")
        return True

    async def complete_payment(self) -> bool:
        """Complete the payment step for an already-reserved slot.

        Should be called after reserve_slot() and after user approval.
        In dry-run mode, logs the action but does not actually pay.

        Returns:
            True if payment succeeded (or dry-run).
        """
        if self.config.dry_run:
            logger.info("[DRY RUN] Payment skipped (would have charged ¥%d/person).",
                        self.config.approval_fee_per_person if hasattr(self.config, 'approval_fee_per_person') else 390)
            return True

        paid = await self._complete_payment()
        if not paid:
            logger.warning("Payment may have failed. Check your account.")
        return paid

    async def book_slot(
        self,
        restaurant: RestaurantTarget,
        target_date: str,
        target_time: str,
    ) -> bool:
        """Reserve a slot and complete payment in one step (no approval gate).

        For backward compatibility with flows that don't use approval.
        """
        reserved = await self.reserve_slot(restaurant, target_date, target_time)
        if not reserved:
            return False
        return await self.complete_payment()

    async def _navigate_to_date(self, target_date: str):
        """Navigate the calendar to the target date."""
        page = self._page
        target = datetime.strptime(target_date, "%Y-%m-%d")

        day = target.day
        month = target.month

        # Approach 1: Direct date link/button
        date_btn = page.locator(f'[data-date="{target_date}"]')
        if await date_btn.count() > 0:
            await date_btn.first.click()
            await page.wait_for_load_state("networkidle")
            return

        # Approach 2: Navigate months then click day
        for _ in range(6):
            month_header = page.locator(
                '[class*="month"], [class*="calendar-header"]'
            )
            if await month_header.count() > 0:
                month_text = await month_header.first.text_content()
                if month_text and (f"{month}月" in month_text or f"{target.strftime('%B')}" in month_text):
                    break
            next_btn = page.locator(
                '[class*="next"], button:has-text("次"), button:has-text(">")'
            )
            if await next_btn.count() > 0:
                await next_btn.first.click()
                await page.wait_for_timeout(1000)

        # Click the day
        day_cell = page.locator(
            f'td:has-text("{day}"), a:has-text("{day}"), '
            f'button:has-text("{day}")'
        ).filter(has_text=re.compile(rf"^{day}$"))
        if await day_cell.count() > 0:
            await day_cell.first.click()
            await page.wait_for_load_state("networkidle")

    async def _select_time_slot(self, target_time: str) -> bool:
        """Select a specific time slot."""
        page = self._page

        time_elements = page.locator(
            f'button:has-text("{target_time}"), '
            f'a:has-text("{target_time}"), '
            f'[class*="time"]:has-text("{target_time}"), '
            f'label:has-text("{target_time}")'
        )

        if await time_elements.count() > 0:
            await time_elements.first.click()
            await page.wait_for_load_state("networkidle")
            logger.info("Selected time: %s", target_time)
            return True

        # Try hour-only match (e.g., "18時")
        hour = target_time.split(":")[0]
        hour_elements = page.locator(
            f'button:has-text("{hour}時"), a:has-text("{hour}時")'
        )
        if await hour_elements.count() > 0:
            await hour_elements.first.click()
            await page.wait_for_load_state("networkidle")
            logger.info("Selected time (hour match): %s時", hour)
            return True

        return False

    async def _select_course(self, course_keyword: str):
        """Select a course by keyword match."""
        page = self._page
        course_elements = page.locator(
            '[class*="course"], [class*="menu"], [class*="plan"]'
        ).filter(has_text=re.compile(course_keyword, re.IGNORECASE))

        if await course_elements.count() > 0:
            clickable = course_elements.first.locator(
                'input[type="radio"], input[type="checkbox"], button, a'
            )
            if await clickable.count() > 0:
                await clickable.first.click()
            else:
                await course_elements.first.click()
            logger.info("Selected course matching: %s", course_keyword)

    async def _confirm_booking(self) -> bool:
        """Complete the booking confirmation flow (before payment)."""
        page = self._page

        # Step 1: Click the reservation/confirm button
        confirm_btn = page.locator(
            'button:has-text("予約"), button:has-text("確認"), '
            'button:has-text("Confirm"), button:has-text("Reserve"), '
            'input[type="submit"][value*="予約"], '
            'a:has-text("予約する")'
        )
        if await confirm_btn.count() == 0:
            logger.error("Could not find confirmation button")
            return False

        await confirm_btn.first.click()
        await page.wait_for_load_state("networkidle")

        # Step 2: Handle two-step confirmation page
        final_confirm = page.locator(
            'button:has-text("確定"), button:has-text("送信"), '
            'button:has-text("Complete"), button:has-text("最終確認")'
        )
        if await final_confirm.count() > 0:
            await final_confirm.first.click()
            await page.wait_for_load_state("networkidle")

        # Check for errors before proceeding to payment
        error_indicators = page.locator(
            ':has-text("満席"), :has-text("予約できません"), '
            ':has-text("エラー"), :has-text("sold out")'
        )
        if await error_indicators.count() > 0:
            error_text = await error_indicators.first.text_content()
            logger.warning("Booking failed: %s", error_text)
            return False

        logger.info("Booking confirmation step passed.")
        return True

    async def _complete_payment(self) -> bool:
        """Complete the payment step (seat reservation fee).

        Omakase charges a seat reservation fee (typically ¥390/person)
        via credit card. The card is usually saved on the account.
        """
        page = self._page
        logger.info("Completing payment...")

        # Check if there's a payment/checkout page
        # Look for payment-related elements: credit card form, pay button, fee display
        payment_btn = page.locator(
            'button:has-text("支払"), button:has-text("決済"), '
            'button:has-text("Pay"), button:has-text("お支払い"), '
            'button:has-text("購入"), button:has-text("確定"), '
            'input[type="submit"][value*="支払"], '
            'input[type="submit"][value*="決済"]'
        )

        if await payment_btn.count() > 0:
            # Log the fee amount if visible
            fee_text = page.locator(
                ':has-text("¥"), :has-text("円"), :has-text("JPY")'
            )
            if await fee_text.count() > 0:
                fee_content = await fee_text.first.text_content()
                logger.info("Payment fee: %s", fee_content.strip() if fee_content else "unknown")

            await payment_btn.first.click()
            await page.wait_for_load_state("networkidle")

            # Verify payment success
            success = page.locator(
                ':has-text("予約が完了"), :has-text("予約を承りました"), '
                ':has-text("お支払いが完了"), :has-text("決済が完了"), '
                ':has-text("Reservation confirmed"), :has-text("Payment complete"), '
                ':has-text("ありがとうございます")'
            )
            if await success.count() > 0:
                logger.info("Payment completed successfully!")
                return True

            # Check for payment errors
            pay_error = page.locator(
                ':has-text("決済エラー"), :has-text("カードエラー"), '
                ':has-text("Payment failed"), :has-text("お支払いに失敗")'
            )
            if await pay_error.count() > 0:
                error_text = await pay_error.first.text_content()
                logger.error("Payment failed: %s", error_text)
                return False

            await page.screenshot(path="payment_result.png")
            logger.warning("Payment result unclear. Screenshot saved to payment_result.png")
            return False

        # No payment button found - some bookings might confirm without separate payment step
        # Check if we're already on a success page
        success = page.locator(
            ':has-text("予約が完了"), :has-text("予約を承りました"), '
            ':has-text("Reservation confirmed"), :has-text("ありがとうございます")'
        )
        if await success.count() > 0:
            logger.info("Booking confirmed (payment may have been automatic).")
            return True

        await page.screenshot(path="booking_result.png")
        logger.warning("Booking result unclear. Screenshot saved to booking_result.png")
        return False

    async def enter_lottery(self, restaurant: RestaurantTarget) -> bool:
        """Enter the lottery (raffle) for a restaurant.

        Some popular restaurants use a lottery system instead of first-come-first-served.
        Users can enter once every 24 hours; more entries increase chances.

        Returns:
            True if lottery entry was successful.
        """
        page = self._page
        logger.info("Entering lottery for: %s", restaurant.name)

        await page.goto(restaurant.omakase_url)
        await page.wait_for_load_state("networkidle")

        # Look for lottery/raffle entry button
        lottery_btn = page.locator(
            'button:has-text("抽選"), button:has-text("エントリー"), '
            'a:has-text("抽選"), a:has-text("raffle"), '
            'button:has-text("Raffle"), a:has-text("Entry"), '
            '[class*="raffle"], [class*="lottery"]'
        )

        if await lottery_btn.count() == 0:
            logger.info("No lottery button found for %s (may be first-come-first-served)", restaurant.name)
            return False

        await lottery_btn.first.click()
        await page.wait_for_load_state("networkidle")

        # Select party size if available
        party_selector = page.locator(
            'select[name*="party"], select[name*="person"], '
            'select[name*="guest"], select[name*="人数"]'
        )
        if await party_selector.count() > 0:
            await party_selector.first.select_option(str(restaurant.party_size))

        # Confirm lottery entry
        confirm_btn = page.locator(
            'button:has-text("応募"), button:has-text("エントリー"), '
            'button:has-text("Enter"), button[type="submit"]'
        )
        if await confirm_btn.count() > 0:
            await confirm_btn.first.click()
            await page.wait_for_load_state("networkidle")

        # Verify entry success
        success = page.locator(
            ':has-text("エントリー完了"), :has-text("応募しました"), '
            ':has-text("Entry complete"), :has-text("entered")'
        )
        already_entered = page.locator(
            ':has-text("エントリー済"), :has-text("応募済"), '
            ':has-text("Already entered")'
        )

        if await success.count() > 0:
            logger.info("Lottery entry successful for %s!", restaurant.name)
            return True
        elif await already_entered.count() > 0:
            logger.info("Already entered lottery for %s", restaurant.name)
            return True
        else:
            await page.screenshot(path=f"lottery_{restaurant.name}.png")
            logger.warning("Lottery entry result unclear for %s", restaurant.name)
            return False

    async def check_lottery_result(self, restaurant: RestaurantTarget) -> str | None:
        """Check if we won a lottery and have a booking window.

        Returns:
            The booking URL if won, None otherwise.
        """
        page = self._page
        logger.info("Checking lottery result for: %s", restaurant.name)

        await page.goto(restaurant.omakase_url)
        await page.wait_for_load_state("networkidle")

        # Look for winner notification or booking window
        winner_link = page.locator(
            'a:has-text("当選"), a:has-text("予約する"), '
            'a:has-text("Winner"), [class*="winner"]'
        )

        if await winner_link.count() > 0:
            href = await winner_link.first.get_attribute("href")
            logger.info("Lottery won for %s! Booking link: %s", restaurant.name, href)
            if href and not href.startswith("http"):
                href = f"{OMAKASE_BASE_URL}{href}"
            return href

        logger.info("No lottery win detected for %s", restaurant.name)
        return None
