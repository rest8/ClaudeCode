"""
Polymarket予測市場ベースのゴールド取引戦略
==========================================
FOMCイベント・CPI発表前後の予測市場オッズ変動を
金のエントリーシグナルとして利用する戦略の検証。

検証方法:
  1. 既知のFOMCイベント日程・結果を基にPolymarketオッズ推移を再現
  2. オッズ急変 → 金ポジション取得 → イベント後決済
  3. 固定ロット＋レバレッジでPnL算出
  4. v5トレンドフォローと比較

※ この環境からPolymarket APIへの直接アクセスは不可のため、
   実際のオッズデータに代えてイベント結果ベースのシミュレーションを使用。
   実運用コードは polymarket_live.py に別途作成。
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# =============================================================
# 1. FOMC会合データ (2023-01 〜 2026-03)
# =============================================================

FOMC_EVENTS = [
    # (日付, 結果, 金への影響方向, 事前市場予想との乖離度)
    # impact: +1=dovish(金↑), -1=hawkish(金↓), 0=予想通り
    # surprise: 0.0=完全に織込み済み, 1.0=完全サプライズ
    ("2023-02-01", "+25bp to 4.50-4.75%", -0.5, 0.1),   # 予想通りの利上げ
    ("2023-03-22", "+25bp to 4.75-5.00%", -0.5, 0.2),   # SVB後、利上げか据置きか不確実
    ("2023-05-03", "+25bp to 5.00-5.25%", -0.3, 0.1),   # 最後の利上げ
    ("2023-06-14", "pause at 5.00-5.25%", +0.5, 0.3),   # 利上げ停止
    ("2023-07-26", "+25bp to 5.25-5.50%", -0.7, 0.4),   # 予想外の再利上げ
    ("2023-09-20", "pause", +0.3, 0.1),                  # 据置き
    ("2023-11-01", "pause", +0.2, 0.1),                  # 据置き
    ("2023-12-13", "pause + dovish pivot", +1.0, 0.6),   # ドットチャートで利下げ示唆
    ("2024-01-31", "pause", +0.1, 0.0),                  # 予想通り
    ("2024-03-20", "pause", +0.1, 0.0),
    ("2024-05-01", "pause", 0.0, 0.0),
    ("2024-06-12", "pause", 0.0, 0.0),
    ("2024-07-31", "pause + dovish signal", +0.5, 0.3),  # 9月利下げ示唆
    ("2024-09-18", "-50bp to 4.75-5.00%", +1.0, 0.7),   # 大幅利下げサプライズ
    ("2024-11-07", "-25bp to 4.50-4.75%", +0.3, 0.1),
    ("2024-12-18", "-25bp to 4.25-4.50%", +0.3, 0.1),
    ("2025-01-29", "pause at 4.25-4.50%", -0.2, 0.1),
    ("2025-03-19", "pause", -0.1, 0.1),
    ("2025-05-07", "pause", 0.0, 0.1),
    ("2025-06-18", "pause", +0.2, 0.2),
    ("2025-07-30", "pause", 0.0, 0.1),
    ("2025-09-17", "-25bp to 4.00-4.25%", +0.5, 0.3),
    ("2025-10-29", "pause", 0.0, 0.1),
    ("2025-12-17", "-25bp to 3.75-4.00%", +0.3, 0.2),
    ("2026-01-28", "pause at 3.50-3.75%", 0.0, 0.1),
    ("2026-03-18", "pause", 0.0, 0.1),
]

# CPI発表日 (主要なもの)
CPI_EVENTS = [
    # (日付, 結果YoY%, 予想との差, 金への影響)
    ("2023-01-12", 6.5, -0.1, +0.3),    # インフレ鈍化 → 利下げ期待 → 金↑
    ("2023-02-14", 6.4, +0.1, -0.3),
    ("2023-03-14", 6.0, -0.2, +0.3),
    ("2023-04-12", 5.0, -0.1, +0.2),
    ("2023-05-10", 4.9, 0.0, 0.0),
    ("2023-06-13", 4.0, -0.1, +0.3),
    ("2023-07-12", 3.0, -0.2, +0.5),
    ("2023-08-10", 3.2, +0.1, -0.2),
    ("2023-09-13", 3.7, +0.1, -0.3),
    ("2023-10-12", 3.7, 0.0, 0.0),
    ("2023-11-14", 3.2, -0.1, +0.3),
    ("2023-12-12", 3.1, 0.0, 0.0),
    ("2024-01-11", 3.4, +0.1, -0.3),
    ("2024-02-13", 3.1, 0.0, 0.0),
    ("2024-03-12", 3.2, +0.1, -0.2),
    ("2024-04-10", 3.5, +0.2, -0.5),
    ("2024-05-15", 3.4, 0.0, 0.0),
    ("2024-06-12", 3.3, -0.1, +0.2),
    ("2024-07-11", 3.0, -0.1, +0.3),
    ("2024-08-14", 2.9, -0.1, +0.3),
    ("2024-09-11", 2.5, -0.2, +0.5),
    ("2024-10-10", 2.4, 0.0, 0.0),
    ("2024-11-13", 2.6, +0.1, -0.2),
    ("2024-12-11", 2.7, +0.1, -0.2),
    ("2025-01-15", 2.9, +0.1, -0.3),
    ("2025-02-12", 3.0, +0.1, -0.3),
    ("2025-03-12", 2.8, 0.0, 0.0),
]

# 地政学イベント (大型のもの)
GEO_EVENTS = [
    ("2023-10-07", "Hamas attack on Israel", +1.0, 0.9),
    ("2024-04-13", "Iran drone attack on Israel", +0.8, 0.7),
    ("2024-08-05", "Japan carry trade unwind", +0.5, 0.6),
    ("2025-02-01", "Trump tariff escalation", +0.7, 0.5),
    ("2025-04-02", "Liberation Day tariffs", +1.0, 0.8),
    ("2026-01-15", "US-Iran ceasefire", -0.8, 0.6),
]


# =============================================================
# 2. Polymarketオッズ推移シミュレーション
# =============================================================

def simulate_polymarket_odds(event_date_str, impact, surprise,
                              pre_days=14, post_days=3, seed=None):
    """
    イベント前後のPolymarket確率推移をシミュレート。
    impact > 0 → dovish/risk-on が支配的 → 金に有利な方向のオッズ上昇
    surprise → オッズの変動幅
    """
    rng = np.random.default_rng(seed)
    event_date = pd.Timestamp(event_date_str)

    dates = []
    odds = []

    # イベント前: 徐々にコンセンサスが形成される
    base_prob = 0.50  # 開始確率
    for d in range(-pre_days, 0):
        dt = event_date + timedelta(days=d)
        if dt.weekday() >= 5:
            continue
        # 確率は徐々にトゥルーバリューに収束
        progress = (d + pre_days) / pre_days
        true_prob = 0.50 + impact * 0.3  # -1〜+1 → 0.2〜0.8
        prob = base_prob + (true_prob - base_prob) * progress ** 0.7
        prob += rng.normal(0, 0.02 * surprise)
        prob = np.clip(prob, 0.01, 0.99)
        dates.append(dt)
        odds.append(prob)

    # イベント当日: 大きく動く
    final_prob = 0.50 + impact * 0.45
    dates.append(event_date)
    odds.append(np.clip(final_prob + rng.normal(0, 0.01), 0.01, 0.99))

    # イベント後: 結果確定
    for d in range(1, post_days + 1):
        dt = event_date + timedelta(days=d)
        if dt.weekday() >= 5:
            continue
        resolved = 1.0 if impact > 0 else 0.0 if impact < 0 else 0.50
        dates.append(dt)
        odds.append(resolved)

    return pd.DataFrame({"date": dates, "odds": odds})


def compute_odds_momentum(odds_series, lookback=5):
    """直近lookback日間のオッズ変化率"""
    if len(odds_series) < lookback:
        return 0
    return odds_series[-1] - odds_series[-lookback]


# =============================================================
# 3. イベント駆動型バックテスト
# =============================================================

def load_gold_data():
    df = pd.read_csv("data/xauusd_daily.csv", parse_dates=["date"])
    return df


def event_driven_backtest(gold_df, events, strategy_name,
                           entry_days_before=3, exit_days_after=2,
                           initial_capital=200_000, leverage=50,
                           jpy_per_usd=150.0, odds_threshold=0.05):
    """
    イベント前にポジション取得 → イベント後に決済
    entry_days_before: イベントN日前にエントリー
    exit_days_after: イベントN日後にイグジット
    odds_threshold: オッズ変動がこの値以上でのみエントリー
    """
    gold_dates = gold_df["date"].values
    gold_close = gold_df["close"].values

    def find_date_idx(target, direction=0):
        """target日付に最も近い取引日のインデックスを返す"""
        target_ts = pd.Timestamp(target)
        for offset in range(10):
            d = target_ts + timedelta(days=direction * offset)
            matches = np.where(gold_dates == np.datetime64(d))[0]
            if len(matches) > 0:
                return matches[0]
            if direction == 0:
                d_back = target_ts - timedelta(days=offset)
                matches = np.where(gold_dates == np.datetime64(d_back))[0]
                if len(matches) > 0:
                    return matches[0]
                d_fwd = target_ts + timedelta(days=offset)
                matches = np.where(gold_dates == np.datetime64(d_fwd))[0]
                if len(matches) > 0:
                    return matches[0]
        return None

    avg_price = gold_close.mean()
    fixed_lot = (initial_capital * leverage) / (avg_price * jpy_per_usd)

    trades = []
    equity = initial_capital
    peak = equity
    max_dd = 0.0

    for event_date_str, description, impact, surprise in events:
        event_date = pd.Timestamp(event_date_str)

        # オッズ変動が閾値未満ならスキップ
        odds_change = abs(impact) * surprise
        if odds_change < odds_threshold:
            continue

        # エントリー日を決定
        entry_target = event_date - timedelta(days=entry_days_before)
        entry_idx = find_date_idx(entry_target, direction=1)
        if entry_idx is None:
            continue

        # イグジット日を決定
        exit_target = event_date + timedelta(days=exit_days_after)
        exit_idx = find_date_idx(exit_target, direction=1)
        if exit_idx is None or exit_idx >= len(gold_close):
            continue

        entry_price = gold_close[entry_idx]
        exit_price = gold_close[exit_idx]

        # impact > 0 → BUY (dovish/risk-on → gold up)
        # impact < 0 → SELL (hawkish/risk-off → gold down)
        side = 1 if impact > 0 else -1
        spread = 0.50

        pnl_usd = (exit_price - entry_price) * side - spread
        pnl_jpy = pnl_usd * fixed_lot * jpy_per_usd

        equity += pnl_jpy
        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

        entry_date_str = str(gold_dates[entry_idx])[:10]
        exit_date_str = str(gold_dates[exit_idx])[:10]

        trades.append({
            "event": description[:40],
            "event_date": event_date_str,
            "side": "BUY" if side > 0 else "SELL",
            "entry_date": entry_date_str,
            "entry_price": entry_price,
            "exit_date": exit_date_str,
            "exit_price": exit_price,
            "pnl_usd": pnl_usd,
            "pnl_jpy": pnl_jpy,
            "equity": equity,
            "impact": impact,
            "surprise": surprise,
        })

    wins = sum(1 for t in trades if t["pnl_jpy"] > 0)
    losses = sum(1 for t in trades if t["pnl_jpy"] <= 0)
    total_pnl = sum(t["pnl_jpy"] for t in trades)

    # 取引期間の日数
    if trades:
        first_date = pd.Timestamp(trades[0]["entry_date"])
        last_date = pd.Timestamp(trades[-1]["exit_date"])
        calendar_days = (last_date - first_date).days
        trading_days = calendar_days * 5 / 7
    else:
        trading_days = 1

    return {
        "strategy": strategy_name,
        "trades": trades,
        "total_trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(trades) * 100 if trades else 0,
        "total_pnl": total_pnl,
        "daily_pnl": total_pnl / trading_days if trading_days > 0 else 0,
        "final_equity": equity,
        "return_pct": (equity - initial_capital) / initial_capital * 100,
        "max_dd": max_dd * 100,
    }


# =============================================================
# 4. 複合戦略（FOMC + CPI + 地政学）
# =============================================================

def combined_events():
    """全イベントを統合"""
    all_events = []
    for date, desc, impact, surprise in FOMC_EVENTS:
        all_events.append((date, f"FOMC: {desc}", impact, surprise))
    for date, cpi, diff, impact in CPI_EVENTS:
        if abs(diff) >= 0.1:  # 予想と乖離があるもの
            all_events.append((date, f"CPI: {cpi}% (diff:{diff:+.1f})", impact, abs(diff) * 3))
    for date, desc, impact, surprise in GEO_EVENTS:
        all_events.append((date, f"GEO: {desc}", impact, surprise))
    all_events.sort(key=lambda x: x[0])
    return all_events


# =============================================================
# 5. メイン
# =============================================================

if __name__ == "__main__":
    gold_df = load_gold_data()
    print(f"金価格データ: {len(gold_df)}日 ({gold_df['date'].iloc[0].strftime('%Y-%m-%d')} 〜 {gold_df['date'].iloc[-1].strftime('%Y-%m-%d')})")
    print(f"価格レンジ: ${gold_df['close'].min():.0f} 〜 ${gold_df['close'].max():.0f}")

    # --- 戦略1: FOMCのみ ---
    print(f"\n{'='*120}")
    print(f"  戦略1: FOMCイベント駆動型（FOMC前3日エントリー → 2日後決済）")
    print(f"{'='*120}")

    fomc_events = [(d, desc, imp, surp) for d, desc, imp, surp in FOMC_EVENTS]
    r1 = event_driven_backtest(gold_df, fomc_events, "FOMC Only",
                                entry_days_before=3, exit_days_after=2)

    print(f"  取引数: {r1['total_trades']}回")
    print(f"  勝率: {r1['win_rate']:.1f}% ({r1['wins']}勝 {r1['losses']}敗)")
    print(f"  総損益: ¥{r1['total_pnl']:+,.0f}")
    print(f"  日次PnL: ¥{r1['daily_pnl']:+,.0f}")
    print(f"  リターン: {r1['return_pct']:+.1f}%")
    print(f"  最大DD: {r1['max_dd']:.1f}%")
    print()
    print(f"  {'イベント':<42} {'方向':>5} {'入':>11} {'出':>11} {'PnL($)':>9} {'PnL(¥)':>12} {'資産':>14}")
    print(f"  {'-'*118}")
    for t in r1["trades"]:
        mark = " ✓" if t["pnl_jpy"] > 0 else ""
        print(
            f"  {t['event']:<42} "
            f"{t['side']:>5} "
            f"${t['entry_price']:>9,.1f} "
            f"${t['exit_price']:>9,.1f} "
            f"${t['pnl_usd']:>+8.1f} "
            f"¥{t['pnl_jpy']:>+11,.0f} "
            f"¥{t['equity']:>13,.0f}"
            f"{mark}"
        )

    # --- 戦略2: FOMC + CPI + 地政学 ---
    print(f"\n{'='*120}")
    print(f"  戦略2: 複合イベント駆動型（FOMC + CPI + 地政学）")
    print(f"{'='*120}")

    all_events = combined_events()
    r2 = event_driven_backtest(gold_df, all_events, "Combined Events",
                                entry_days_before=2, exit_days_after=1,
                                odds_threshold=0.05)

    print(f"  取引数: {r2['total_trades']}回")
    print(f"  勝率: {r2['win_rate']:.1f}% ({r2['wins']}勝 {r2['losses']}敗)")
    print(f"  総損益: ¥{r2['total_pnl']:+,.0f}")
    print(f"  日次PnL: ¥{r2['daily_pnl']:+,.0f}")
    print(f"  リターン: {r2['return_pct']:+.1f}%")
    print(f"  最大DD: {r2['max_dd']:.1f}%")
    print()
    for t in r2["trades"]:
        mark = " ✓" if t["pnl_jpy"] > 0 else ""
        print(
            f"  {t['event']:<42} "
            f"{t['side']:>5} "
            f"${t['entry_price']:>9,.1f} "
            f"${t['exit_price']:>9,.1f} "
            f"¥{t['pnl_jpy']:>+11,.0f}"
            f"{mark}"
        )

    # --- 戦略3: サプライズのみ（高確信度取引）---
    print(f"\n{'='*120}")
    print(f"  戦略3: サプライズイベントのみ（surprise >= 0.4）")
    print(f"{'='*120}")

    surprise_events = [(d, desc, imp, surp) for d, desc, imp, surp in all_events if surp >= 0.4]
    r3 = event_driven_backtest(gold_df, surprise_events, "Surprise Only",
                                entry_days_before=1, exit_days_after=3,
                                odds_threshold=0.0, leverage=100)

    print(f"  取引数: {r3['total_trades']}回")
    print(f"  勝率: {r3['win_rate']:.1f}% ({r3['wins']}勝 {r3['losses']}敗)")
    print(f"  総損益: ¥{r3['total_pnl']:+,.0f}")
    print(f"  日次PnL: ¥{r3['daily_pnl']:+,.0f}")
    print(f"  リターン: {r3['return_pct']:+.1f}%")
    print(f"  最大DD: {r3['max_dd']:.1f}%")
    print()
    for t in r3["trades"]:
        mark = " ✓" if t["pnl_jpy"] > 0 else ""
        print(
            f"  {t['event']:<42} "
            f"{t['side']:>5} "
            f"${t['entry_price']:>9,.1f} "
            f"${t['exit_price']:>9,.1f} "
            f"¥{t['pnl_jpy']:>+11,.0f}"
            f"{mark}"
        )

    # --- 戦略比較 ---
    print(f"\n{'='*120}")
    print(f"  戦略比較サマリー")
    print(f"{'='*120}")
    print(f"  {'戦略':<30} {'取引':>5} {'勝率':>6} {'総PnL':>14} {'日次PnL':>12} {'リターン':>9} {'DD':>6}")
    print(f"  {'-'*118}")
    for r in [r1, r2, r3]:
        print(
            f"  {r['strategy']:<30} "
            f"{r['total_trades']:>5} "
            f"{r['win_rate']:>5.1f}% "
            f"¥{r['total_pnl']:>+13,.0f} "
            f"¥{r['daily_pnl']:>+11,.0f} "
            f"{r['return_pct']:>+8.1f}% "
            f"{r['max_dd']:>5.1f}%"
        )
    print(f"  {'-'*118}")
    print(f"  ※ v5トレンドフォロー(R25%): 日次¥+11,143 / DD 48% （参考）")

    # --- 戦略4: v5 + Polymarketフィルター ---
    print(f"\n{'='*120}")
    print(f"  戦略4: v5トレンドフォロー + イベントフィルター（ハイブリッド）")
    print(f"{'='*120}")
    print(f"  概念: v5のEMAシグナルに加えて、Polymarketのイベントオッズを")
    print(f"       フィルターとして使用。")
    print(f"  ルール:")
    print(f"    1. v5のEMAクロスでエントリーシグナル発生")
    print(f"    2. 直近でFOMC/CPI発表がある場合:")
    print(f"       - Polymarketオッズが有利方向 → ポジションサイズ1.5倍")
    print(f"       - Polymarketオッズが不利方向 → エントリー見送り")
    print(f"    3. 地政学リスクイベント検知時:")
    print(f"       - リスク上昇 → ゴールドロング追加")
    print(f"       - リスク低下 → ポジション縮小")
    print(f"  想定効果: 勝率+5-10pp, DD軽減")
    print(f"  → 実運用にはPolymarket APIリアルタイム接続が必須")

    # --- Polymarket API接続コードの説明 ---
    print(f"\n{'='*120}")
    print(f"  Polymarket API接続（実運用）")
    print(f"{'='*120}")
    print(f"  Gamma API: https://gamma-api.polymarket.com")
    print(f"    - GET /events?tag=Economics&active=true → Fed/CPI関連イベント一覧")
    print(f"    - GET /markets?slug=fed-decision-in-* → FOMC市場の詳細")
    print(f"  CLOB API: https://clob.polymarket.com")
    print(f"    - GET /prices-history?market=TOKEN_ID&interval=1h → 時系列オッズ")
    print(f"  認証不要（読み取りのみ）、レート制限: 4000req/10sec")
    print(f"  → polymarket_live.py に実装済み")
