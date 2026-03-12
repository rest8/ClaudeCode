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

import logging
import re
from datetime import datetime

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from .config import Config, RestaurantTarget

logger = logging.getLogger(__name__)

OMAKASE_BASE_URL = "https://omakase.in"
LOGIN_URL = f"{OMAKASE_BASE_URL}/users/sign_in"


class OmakaseBookingError(Exception):
    """Raised when booking fails."""


class OmakaseClient:
    """Automated client for Omakase.in reservations."""

    def __init__(self, config: Config):
        self.config = config
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def start(self):
        """Launch browser and log in."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
        )
        self._context = await self._browser.new_context(
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.config.browser_timeout_ms)
        await self._login()

    async def close(self):
        """Clean up browser resources."""
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

        Returns:
            True if payment succeeded.
        """
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
