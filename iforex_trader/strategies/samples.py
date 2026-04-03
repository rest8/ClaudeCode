"""Sample strategies for demonstration.

These are placeholder strategies to show the framework structure.
Replace the logic in evaluate() with your actual trading algorithms.
"""

from __future__ import annotations

from loguru import logger
from .base import BaseStrategy
from ..trader import Trader, Side


class MovingAverageCross(BaseStrategy):
    """Moving average crossover strategy (placeholder).

    Tracks recent prices and generates signals when short-term
    average crosses above/below long-term average.
    """

    name = "移動平均クロス"
    description = "短期・長期の移動平均線の交差でエントリー"

    def __init__(self, short_window: int = 5, long_window: int = 20) -> None:
        self.short_window = short_window
        self.long_window = long_window
        self._prices: list[float] = []

    def evaluate(self, trader: Trader) -> Side | None:
        prices = trader.get_current_price()
        bid = prices.get("bid")
        if bid is None:
            return None

        self._prices.append(bid)
        if len(self._prices) > self.long_window:
            self._prices = self._prices[-self.long_window:]

        if len(self._prices) < self.long_window:
            logger.debug("Collecting prices: {}/{}", len(self._prices), self.long_window)
            return None

        short_avg = sum(self._prices[-self.short_window:]) / self.short_window
        long_avg = sum(self._prices) / self.long_window

        logger.debug("MA short={:.4f} long={:.4f}", short_avg, long_avg)

        if short_avg > long_avg:
            return Side.BUY
        elif short_avg < long_avg:
            return Side.SELL
        return None


class RSIStrategy(BaseStrategy):
    """RSI-based strategy (placeholder).

    Buys when RSI drops below oversold threshold,
    sells when RSI rises above overbought threshold.
    """

    name = "RSI反転"
    description = "RSIの買われすぎ・売られすぎで逆張りエントリー"

    def __init__(self, period: int = 14, oversold: float = 30, overbought: float = 70) -> None:
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self._prices: list[float] = []

    def evaluate(self, trader: Trader) -> Side | None:
        prices = trader.get_current_price()
        bid = prices.get("bid")
        if bid is None:
            return None

        self._prices.append(bid)
        if len(self._prices) > self.period + 1:
            self._prices = self._prices[-(self.period + 1):]

        if len(self._prices) <= self.period:
            logger.debug("Collecting prices: {}/{}", len(self._prices), self.period + 1)
            return None

        gains, losses = [], []
        for i in range(1, len(self._prices)):
            change = self._prices[i] - self._prices[i - 1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))

        avg_gain = sum(gains) / self.period
        avg_loss = sum(losses) / self.period

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        logger.debug("RSI={:.2f}", rsi)

        if rsi < self.oversold:
            return Side.BUY
        elif rsi > self.overbought:
            return Side.SELL
        return None


class BreakoutStrategy(BaseStrategy):
    """Price breakout strategy (placeholder).

    Buys on breakout above recent high, sells on breakdown below recent low.
    """

    name = "ブレイクアウト"
    description = "直近の高値・安値を突破した方向にエントリー"

    def __init__(self, lookback: int = 20) -> None:
        self.lookback = lookback
        self._prices: list[float] = []

    def evaluate(self, trader: Trader) -> Side | None:
        prices = trader.get_current_price()
        bid = prices.get("bid")
        if bid is None:
            return None

        self._prices.append(bid)
        if len(self._prices) > self.lookback + 1:
            self._prices = self._prices[-(self.lookback + 1):]

        if len(self._prices) <= self.lookback:
            logger.debug("Collecting prices: {}/{}", len(self._prices), self.lookback + 1)
            return None

        window = self._prices[:-1]
        high = max(window)
        low = min(window)
        current = self._prices[-1]

        logger.debug("Breakout check: low={:.4f} current={:.4f} high={:.4f}", low, current, high)

        if current > high:
            return Side.BUY
        elif current < low:
            return Side.SELL
        return None
