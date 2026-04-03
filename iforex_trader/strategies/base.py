"""Base strategy interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from ..trader import Trader, Side


class BaseStrategy(ABC):
    """All trading strategies must implement this interface."""

    @abstractmethod
    def evaluate(self, trader: Trader) -> Side | None:
        """Evaluate the current market and return BUY, SELL, or None (do nothing)."""
        ...


class DummyStrategy(BaseStrategy):
    """A no-op strategy that never trades. Use as a template."""

    def evaluate(self, trader: Trader) -> Side | None:
        prices = trader.get_current_price()
        if prices["bid"] is not None:
            from loguru import logger
            logger.debug("Current prices — bid: {}, ask: {}", prices["bid"], prices["ask"])
        return None  # Never trades — replace with real logic
