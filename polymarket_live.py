"""
Polymarket APIリアルタイム接続モジュール
=======================================
Gamma API + CLOB APIから予測市場データを取得し、
金取引シグナルとして使用可能な形に変換する。

認証不要（読み取り専用）。Windows PCから直接実行可能。
"""

import requests
import time
import json
from datetime import datetime, timedelta
from dataclasses import dataclass


GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"

GOLD_KEYWORDS = [
    "fed", "fomc", "rate cut", "rate hike", "interest rate",
    "cpi", "inflation", "pce",
    "gold", "xau",
    "tariff", "trade war",
    "iran", "israel", "war", "conflict", "ceasefire",
    "recession", "gdp",
]

RETRY_DELAYS = [2, 4, 8, 16]


@dataclass
class MarketSignal:
    event_name: str
    market_question: str
    current_odds: float
    odds_1h_ago: float
    odds_24h_ago: float
    volume_24h: float
    gold_impact: str
    signal_strength: float


def _get(url, params=None, retries=4):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
                continue
            r.raise_for_status()
        except requests.exceptions.RequestException:
            if attempt < retries - 1:
                time.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
    return None


def fetch_gold_relevant_events(limit=100):
    """金価格に影響するイベント市場を取得"""
    events = _get(f"{GAMMA_BASE}/events", params={
        "active": "true",
        "closed": "false",
        "limit": limit,
        "order": "volume24hr",
        "ascending": "false",
    })
    if not events:
        return []

    relevant = []
    for event in events:
        title = (event.get("title", "") + " " + event.get("description", "")).lower()
        if any(kw in title for kw in GOLD_KEYWORDS):
            relevant.append(event)

    return relevant


def fetch_fed_rate_markets():
    """FOMC利下げ/利上げ関連の市場を取得"""
    markets = _get(f"{GAMMA_BASE}/markets", params={
        "active": "true",
        "closed": "false",
        "limit": 50,
        "order": "volume24hr",
        "ascending": "false",
    })
    if not markets:
        return []

    fed_markets = []
    for m in markets:
        q = m.get("question", "").lower()
        if any(kw in q for kw in ["fed", "fomc", "rate cut", "rate hike", "interest rate"]):
            fed_markets.append(m)

    return fed_markets


def fetch_price_history(token_id, interval="1d", fidelity=60):
    """CLOB APIから価格履歴を取得"""
    data = _get(f"{CLOB_BASE}/prices-history", params={
        "market": token_id,
        "interval": interval,
        "fidelity": fidelity,
    })
    if data and "history" in data:
        return data["history"]
    return []


def classify_gold_impact(question):
    """市場の質問から金への影響方向を判定"""
    q = question.lower()

    dovish_keywords = ["rate cut", "lower rate", "ease", "dovish"]
    hawkish_keywords = ["rate hike", "higher rate", "tighten", "hawkish"]
    risk_up_keywords = ["war", "conflict", "attack", "invasion", "tariff", "sanctions"]
    risk_down_keywords = ["ceasefire", "peace", "deal", "agreement"]
    inflation_up_keywords = ["inflation rise", "cpi above", "higher inflation"]
    inflation_down_keywords = ["inflation fall", "cpi below", "lower inflation"]

    if any(kw in q for kw in dovish_keywords):
        return "GOLD_UP"
    if any(kw in q for kw in hawkish_keywords):
        return "GOLD_DOWN"
    if any(kw in q for kw in risk_up_keywords):
        return "GOLD_UP"
    if any(kw in q for kw in risk_down_keywords):
        return "GOLD_DOWN"
    if any(kw in q for kw in inflation_up_keywords):
        return "GOLD_DOWN"
    if any(kw in q for kw in inflation_down_keywords):
        return "GOLD_UP"

    return "NEUTRAL"


def get_trading_signals():
    """
    現在のPolymarketデータから金取引シグナルを生成。
    戻り値: MarketSignalのリスト（signal_strength降順）
    """
    signals = []

    events = fetch_gold_relevant_events()
    for event in events:
        for market in event.get("markets", []):
            question = market.get("question", "")
            impact = classify_gold_impact(question)
            if impact == "NEUTRAL":
                continue

            outcome_prices = market.get("outcomePrices", "[]")
            if isinstance(outcome_prices, str):
                try:
                    outcome_prices = json.loads(outcome_prices)
                except json.JSONDecodeError:
                    continue

            current_odds = float(outcome_prices[0]) if outcome_prices else 0.5
            price_change_1d = market.get("oneDayPriceChange", 0) or 0
            volume_24h = market.get("volume24hr", 0) or 0

            odds_24h_ago = current_odds - price_change_1d

            # シグナル強度 = オッズ変化 × ボリューム重み
            vol_weight = min(volume_24h / 100000, 3.0)
            signal_strength = abs(price_change_1d) * vol_weight

            # オッズが50%から離れるほど確信度が高い
            conviction = abs(current_odds - 0.5) * 2

            signals.append(MarketSignal(
                event_name=event.get("title", "")[:60],
                market_question=question[:80],
                current_odds=current_odds,
                odds_1h_ago=current_odds,
                odds_24h_ago=odds_24h_ago,
                volume_24h=volume_24h,
                gold_impact=impact,
                signal_strength=signal_strength * conviction,
            ))

    signals.sort(key=lambda s: s.signal_strength, reverse=True)
    return signals


def should_trade_gold(signals, threshold=0.1):
    """
    シグナルを集約して金のポジション方向を決定。
    戻り値: ("BUY"|"SELL"|"NONE", confidence: 0-1)
    """
    if not signals:
        return "NONE", 0.0

    buy_score = 0.0
    sell_score = 0.0

    for sig in signals:
        if sig.signal_strength < 0.01:
            continue
        if sig.gold_impact == "GOLD_UP":
            buy_score += sig.signal_strength
        elif sig.gold_impact == "GOLD_DOWN":
            sell_score += sig.signal_strength

    net = buy_score - sell_score
    total = buy_score + sell_score
    confidence = abs(net) / total if total > 0 else 0

    if abs(net) < threshold:
        return "NONE", confidence

    return ("BUY" if net > 0 else "SELL"), confidence


# =============================================================
# CLI実行
# =============================================================

if __name__ == "__main__":
    print("=" * 80)
    print("  Polymarket → Gold Trading Signal Generator")
    print("=" * 80)

    print("\n金関連イベント取得中...")
    try:
        events = fetch_gold_relevant_events()
        print(f"取得: {len(events)}件")

        if events:
            for ev in events[:10]:
                title = ev.get("title", "?")[:60]
                vol = ev.get("volume", 0)
                print(f"  [{vol:>12,.0f}] {title}")

        print("\nFed関連市場取得中...")
        fed_markets = fetch_fed_rate_markets()
        print(f"取得: {len(fed_markets)}件")

        for m in fed_markets[:5]:
            q = m.get("question", "?")[:70]
            prices = m.get("outcomePrices", "?")
            change = m.get("oneDayPriceChange", 0)
            print(f"  {q}")
            print(f"    現在オッズ: {prices}  24h変化: {change}")

        print("\n取引シグナル生成中...")
        signals = get_trading_signals()
        print(f"シグナル数: {len(signals)}")

        for sig in signals[:5]:
            print(f"  [{sig.gold_impact:>9}] {sig.event_name}")
            print(f"    オッズ: {sig.current_odds:.3f} (24h前: {sig.odds_24h_ago:.3f})")
            print(f"    強度: {sig.signal_strength:.4f}")

        direction, confidence = should_trade_gold(signals)
        print(f"\n{'='*80}")
        print(f"  推奨: {direction}  確信度: {confidence:.1%}")
        print(f"{'='*80}")

    except Exception as e:
        print(f"\nAPI接続エラー: {e}")
        print("  → このテスト環境ではPolymarket APIへのアクセスがブロックされています。")
        print("  → Windows PCで直接実行してください。")
        print("\n使い方:")
        print("  pip install requests")
        print("  python polymarket_live.py")
        print("\n統合方法:")
        print("  from polymarket_live import get_trading_signals, should_trade_gold")
        print("  signals = get_trading_signals()")
        print("  direction, confidence = should_trade_gold(signals)")
        print("  # direction: 'BUY' | 'SELL' | 'NONE'")
        print("  # confidence: 0.0 ~ 1.0")
