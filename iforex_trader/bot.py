"""Main bot orchestrator."""

import time
import signal
import sys

from loguru import logger

from .config import Config
from .browser import IForexBrowser
from .auth import login
from .trader import Trader
from .strategies.base import BaseStrategy, DummyStrategy


class TradingBot:
    """Top-level controller that ties browser, auth, trader, and strategy together."""

    def __init__(self, config: Config | None = None, strategy: BaseStrategy | None = None) -> None:
        self.config = config or Config()
        self.strategy = strategy or DummyStrategy()
        self.browser = IForexBrowser(self.config)
        self.trader: Trader | None = None
        self._running = False

    def start(self) -> None:
        """Start the trading bot."""
        logger.info("=== iFOREX Trading Bot starting ===")

        # Setup graceful shutdown
        signal.signal(signal.SIGINT, self._shutdown_handler)
        signal.signal(signal.SIGTERM, self._shutdown_handler)

        page = self.browser.start()

        if not login(page, self.config):
            logger.error("Login failed. Exiting.")
            self.browser.stop()
            sys.exit(1)

        self.trader = Trader(page)
        self._running = True

        logger.info(
            "Bot running. Evaluating strategy every {} seconds.",
            self.config.trade_interval_seconds,
        )

        try:
            while self._running:
                self._tick()
                time.sleep(self.config.trade_interval_seconds)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _tick(self) -> None:
        """One evaluation cycle."""
        try:
            signal = self.strategy.evaluate(self.trader)
            if signal is not None:
                result = self.trader.place_order(
                    side=signal,
                    instrument="USD/JPY",  # Default — strategies can override
                    lot_size=self.config.default_lot_size,
                )
                logger.info("Order result: {}", result)
            else:
                logger.debug("Strategy returned no signal. Waiting...")
        except Exception as e:
            logger.error("Error during tick: {}", e)
            self.browser.screenshot("tick_error.png")

    def stop(self) -> None:
        """Stop the bot and cleanup."""
        logger.info("Shutting down bot...")
        self._running = False
        self.browser.stop()

    def _shutdown_handler(self, signum, frame) -> None:
        logger.info("Received signal {}. Shutting down...", signum)
        self._running = False
