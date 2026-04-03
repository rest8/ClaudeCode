"""Strategy registry — central place to list all available strategies."""

from __future__ import annotations

from .base import BaseStrategy, DummyStrategy
from .samples import MovingAverageCross, RSIStrategy, BreakoutStrategy

STRATEGY_REGISTRY: list[dict] = [
    {
        "name": "移動平均クロス",
        "description": "短期・長期の移動平均線の交差でエントリー",
        "factory": MovingAverageCross,
    },
    {
        "name": "RSI反転",
        "description": "RSIの買われすぎ・売られすぎで逆張りエントリー",
        "factory": RSIStrategy,
    },
    {
        "name": "ブレイクアウト",
        "description": "直近の高値・安値を突破した方向にエントリー",
        "factory": BreakoutStrategy,
    },
    {
        "name": "ダミー（取引なし）",
        "description": "何もしない。テスト・動作確認用",
        "factory": DummyStrategy,
    },
]


def get_strategy_by_name(name: str) -> BaseStrategy:
    for entry in STRATEGY_REGISTRY:
        if entry["name"] == name:
            return entry["factory"]()
    raise ValueError(f"Unknown strategy: {name}")
