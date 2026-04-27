"""
ハイブリッド戦略: v5トレンドフォロー + Polymarketイベントフィルター
====================================================================
v5 EMAクロス戦略をベースに、イベントカレンダーで
ポジションサイズを動的調整。
"""

import numpy as np
import pandas as pd
from backtest import load_gold_data, run_backtest, BacktestConfig
from polymarket_strategy import FOMC_EVENTS, CPI_EVENTS, GEO_EVENTS


def build_event_calendar(gold_df):
    """全イベントを日付→影響度マップに変換"""
    event_map = {}

    for date_str, _, impact, surprise in FOMC_EVENTS:
        dt = pd.Timestamp(date_str)
        score = impact * surprise
        for offset in range(-5, 4):
            d = dt + pd.Timedelta(days=offset)
            if d in event_map:
                event_map[d] = max(event_map[d], abs(score)) * np.sign(event_map[d] + score)
            else:
                weight = 1.0 if offset >= 0 else 0.5
                event_map[d] = score * weight

    for date_str, _, diff, impact in CPI_EVENTS:
        if abs(diff) < 0.1:
            continue
        dt = pd.Timestamp(date_str)
        score = impact * abs(diff) * 2
        for offset in range(-2, 3):
            d = dt + pd.Timedelta(days=offset)
            weight = 1.0 if offset >= 0 else 0.3
            event_map.setdefault(d, 0)
            event_map[d] += score * weight

    for date_str, _, impact, surprise in GEO_EVENTS:
        dt = pd.Timestamp(date_str)
        score = impact * surprise
        for offset in range(0, 5):
            d = dt + pd.Timedelta(days=offset)
            weight = 1.0 / (1 + offset)
            event_map.setdefault(d, 0)
            event_map[d] += score * weight

    return event_map


def hybrid_backtest(gold_df, base_cfg, event_map,
                     boost_factor=1.5, block_threshold=-0.3):
    """
    v5をベースに、イベントスコアでポジションサイズを調整:
      score > 0 (dovish/risk-on)  → サイズ×boost_factor
      score < block_threshold     → エントリー見送り
    """
    base_result = run_backtest(gold_df, base_cfg)
    warmup = max(base_cfg.ema_long, base_cfg.atr_period) + 1
    dates = gold_df["date"].iloc[warmup:].reset_index(drop=True)
    closes = gold_df["close"].iloc[warmup:].values

    initial_capital = base_cfg.initial_capital
    equity = initial_capital
    peak = equity
    max_dd = 0.0
    equity_curve = [equity]

    base_eq = base_result.equity_curve
    base_daily_pnl = np.diff(base_eq)

    trades_taken = 0
    trades_blocked = 0
    trades_boosted = 0

    for i, pnl in enumerate(base_daily_pnl):
        if i >= len(dates):
            break

        date = dates.iloc[i] if hasattr(dates, 'iloc') else dates[i]
        date_norm = pd.Timestamp(date).normalize()

        # 前後2日を検索してイベントスコアを取得
        event_score = 0.0
        for offset in range(-2, 3):
            d = date_norm + pd.Timedelta(days=offset)
            event_score += event_map.get(d, 0) * (1.0 / (1 + abs(offset)))

        if event_score < block_threshold and pnl != 0:
            adjusted_pnl = 0
            trades_blocked += 1
        elif event_score > 0.15 and pnl != 0:
            adjusted_pnl = pnl * boost_factor
            trades_boosted += 1
            trades_taken += 1
        else:
            adjusted_pnl = pnl
            if pnl != 0:
                trades_taken += 1

        equity += adjusted_pnl
        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
        equity_curve.append(equity)

    total_pnl = equity - initial_capital
    trading_days = len(base_daily_pnl)

    return {
        "final_equity": equity,
        "total_pnl": total_pnl,
        "daily_pnl": total_pnl / trading_days,
        "return_pct": (equity - initial_capital) / initial_capital * 100,
        "max_dd": max_dd * 100,
        "trades_taken": trades_taken,
        "trades_blocked": trades_blocked,
        "trades_boosted": trades_boosted,
        "equity_curve": equity_curve,
    }


if __name__ == "__main__":
    gold_df = load_gold_data()
    print(f"金データ: {len(gold_df)}日")

    event_map = build_event_calendar(gold_df)
    event_days = sum(1 for v in event_map.values() if abs(v) > 0.01)
    print(f"イベント影響日数: {event_days}日")

    # ベースライン: v5 R25% Lev100x
    base_cfg = BacktestConfig(
        ema_short=10, ema_long=50,
        risk_per_trade=0.25, max_leverage=100,
        long_only=True, use_reentry=True, momentum_period=40,
    )

    print(f"\n{'='*100}")
    print(f"  ハイブリッド戦略テスト")
    print(f"  ベース: v5 EMA10/50 R25% Lev100x + Polymarketイベントフィルター")
    print(f"{'='*100}")

    # パラメータグリッド
    configs = [
        ("ベースライン(v5のみ)", 1.0, -999),
        ("Boost1.3x / Block-0.3", 1.3, -0.3),
        ("Boost1.5x / Block-0.3", 1.5, -0.3),
        ("Boost1.5x / Block-0.2", 1.5, -0.2),
        ("Boost2.0x / Block-0.3", 2.0, -0.3),
        ("Boost2.0x / Block-0.2", 2.0, -0.2),
        ("Boost2.0x / Block-0.1", 2.0, -0.1),
    ]

    print(f"\n  {'設定':<30} {'最終資産':>14} {'日次PnL':>12} {'リターン':>10} {'DD':>7} {'ブースト':>7} {'ブロック':>7}")
    print(f"  {'-'*98}")

    for label, boost, block in configs:
        if label.startswith("ベースライン"):
            # 純粋なv5
            base_result = run_backtest(gold_df, base_cfg)
            eq = base_result.equity_curve
            final = eq[-1]
            total_pnl = final - base_cfg.initial_capital
            warmup = max(base_cfg.ema_long, base_cfg.atr_period) + 1
            trading_days = len(gold_df) - warmup
            daily_pnl = total_pnl / trading_days

            peak_v = eq[0]
            max_dd_v = 0
            for v in eq:
                if v > peak_v:
                    peak_v = v
                dd = (peak_v - v) / peak_v if peak_v > 0 else 0
                max_dd_v = max(max_dd_v, dd)

            print(
                f"  {label:<30} "
                f"¥{final:>13,.0f} "
                f"¥{daily_pnl:>+11,.0f} "
                f"{(final - base_cfg.initial_capital) / base_cfg.initial_capital * 100:>+9.0f}% "
                f"{max_dd_v * 100:>6.1f}% "
                f"{'---':>7} "
                f"{'---':>7}"
            )
        else:
            r = hybrid_backtest(gold_df, base_cfg, event_map,
                                 boost_factor=boost, block_threshold=block)
            print(
                f"  {label:<30} "
                f"¥{r['final_equity']:>13,.0f} "
                f"¥{r['daily_pnl']:>+11,.0f} "
                f"{r['return_pct']:>+9.0f}% "
                f"{r['max_dd']:>6.1f}% "
                f"{r['trades_boosted']:>7} "
                f"{r['trades_blocked']:>7}"
            )

    print(f"\n  ブースト: イベント有利時にサイズ倍増した回数")
    print(f"  ブロック: イベント不利時にエントリー見送りした回数")

    # 最終推奨
    best = hybrid_backtest(gold_df, base_cfg, event_map,
                            boost_factor=1.5, block_threshold=-0.3)
    print(f"\n{'='*100}")
    print(f"  最終推奨戦略: v5 R25% + Polymarket Boost1.5x/Block-0.3")
    print(f"{'='*100}")
    print(f"  最終資産: ¥{best['final_equity']:,.0f}")
    print(f"  日次PnL: ¥{best['daily_pnl']:+,.0f}")
    print(f"  リターン: {best['return_pct']:+.1f}%")
    print(f"  最大DD: {best['max_dd']:.1f}%")
    print(f"  ブースト取引: {best['trades_boosted']}回")
    print(f"  ブロック取引: {best['trades_blocked']}回")
    print(f"\n  運用方法:")
    print(f"    1. v5のEMA10/50クロスでエントリーシグナル検知")
    print(f"    2. polymarket_live.py でPolymarketオッズを確認")
    print(f"    3. オッズが有利 → ポジション1.5倍 / 不利 → エントリー見送り")
    print(f"    4. iFOREXで自動執行（iforex_trader/）")
