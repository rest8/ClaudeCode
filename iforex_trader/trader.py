"""Core trading operations on the iFOREX web platform."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from playwright.sync_api import Page
from loguru import logger


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class OrderResult:
    success: bool
    side: Side
    instrument: str
    lot_size: int
    message: str = ""


class Trader:
    """Executes trades on the iFOREX web platform via browser automation.

    NOTE: The CSS selectors below are placeholders. After running the bot
    once with HEADLESS=false, inspect the actual iFOREX trading UI and
    update the selectors accordingly.
    """

    def __init__(self, page: Page) -> None:
        self.page = page

    def select_instrument(self, instrument: str) -> None:
        """Search and select a trading instrument (e.g. 'USD/JPY')."""
        logger.info("Selecting instrument: {}", instrument)
        # Click the instrument search box and type
        search = self.page.locator('[data-testid="instrument-search"], .instrument-search, input[placeholder*="Search"]').first
        search.click()
        search.fill(instrument)
        self.page.wait_for_timeout(1000)
        # Click the matching result
        self.page.locator(f'text="{instrument}"').first.click()
        self.page.wait_for_timeout(500)

    def get_current_price(self) -> dict[str, float | None]:
        """Read bid/ask prices from the UI. Returns {'bid': ..., 'ask': ...}."""
        try:
            bid_el = self.page.locator('.bid-price, [data-testid="bid"]').first
            ask_el = self.page.locator('.ask-price, [data-testid="ask"]').first
            bid = float(bid_el.inner_text().replace(",", ""))
            ask = float(ask_el.inner_text().replace(",", ""))
            return {"bid": bid, "ask": ask}
        except Exception as e:
            logger.warning("Could not read prices: {}", e)
            return {"bid": None, "ask": None}

    def place_order(self, side: Side, instrument: str, lot_size: int) -> OrderResult:
        """Place a market order."""
        logger.info("Placing {} order: {} x {}", side.value, instrument, lot_size)
        try:
            self.select_instrument(instrument)

            # Set lot size
            lot_input = self.page.locator('.lot-size-input, [data-testid="amount"], input[name="amount"]').first
            lot_input.fill("")
            lot_input.fill(str(lot_size))

            # Click buy or sell
            if side == Side.BUY:
                btn = self.page.locator('.buy-button, [data-testid="buy"], button:has-text("Buy")').first
            else:
                btn = self.page.locator('.sell-button, [data-testid="sell"], button:has-text("Sell")').first
            btn.click()

            # Confirm if a confirmation dialog appears
            try:
                confirm = self.page.locator('button:has-text("Confirm"), button:has-text("OK")').first
                confirm.click(timeout=3000)
            except Exception:
                pass  # No confirmation dialog

            self.page.wait_for_timeout(1000)
            logger.info("Order placed successfully.")
            return OrderResult(success=True, side=side, instrument=instrument, lot_size=lot_size)

        except Exception as e:
            logger.error("Order failed: {}", e)
            self.page.screenshot(path="order_error.png")
            return OrderResult(
                success=False, side=side, instrument=instrument,
                lot_size=lot_size, message=str(e),
            )

    def close_position(self, instrument: str) -> bool:
        """Attempt to close an open position for the given instrument."""
        logger.info("Closing position for {}", instrument)
        try:
            # Navigate to open positions
            positions_tab = self.page.locator('text="Open Positions", text="Positions", [data-testid="positions"]').first
            positions_tab.click()
            self.page.wait_for_timeout(1000)

            # Find and close the position row
            row = self.page.locator(f'tr:has-text("{instrument}"), .position-row:has-text("{instrument}")').first
            close_btn = row.locator('button:has-text("Close"), .close-position').first
            close_btn.click()

            # Confirm
            try:
                confirm = self.page.locator('button:has-text("Confirm"), button:has-text("OK")').first
                confirm.click(timeout=3000)
            except Exception:
                pass

            logger.info("Position closed for {}", instrument)
            return True
        except Exception as e:
            logger.error("Failed to close position: {}", e)
            return False
