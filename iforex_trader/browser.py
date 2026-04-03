"""Browser automation layer for iFOREX web platform."""

from __future__ import annotations

from playwright.sync_api import sync_playwright, Browser, Page, Playwright
from loguru import logger

from .config import Config


class IForexBrowser:
    """Manages browser lifecycle and provides page access."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page

    def start(self) -> Page:
        """Launch browser and return the main page."""
        logger.info("Launching browser (headless={})", self.config.headless)
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.config.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self._page = context.new_page()
        return self._page

    def stop(self) -> None:
        """Close browser and cleanup."""
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None
        self._page = None
        logger.info("Browser closed.")

    def screenshot(self, path: str = "screenshot.png") -> None:
        """Take a screenshot for debugging."""
        self.page.screenshot(path=path)
        logger.debug("Screenshot saved to {}", path)
