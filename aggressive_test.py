"""日次¥5,000以上を目指す攻撃的パラメータの検証"""

import numpy as np
import pandas as pd
from backtest import load_gold_data, run_backtest, BacktestConfig, analyze


def detailed_report(df, cfg, label):
    result = run_backtest(df, cfg)
    stats = analyze(result, label)
    if not stats or not result.trades:
        return stats

    eq = result.equity_curve
    warmup = max(cfg.ema_long, cfg.atr_period) + 1
    dates = df["date"].iloc[warmup:].reset_index(drop=True)
    eq_vals = eq[1:]

    # 日次PnL
    daily_pnls = []
    for i in range(1, len(eq_vals)):
        daily_pnls.append(eq_vals[i] - eq_vals[i-1])

    daily_pnls = np.array(daily_pnls)
    trading_days = len(daily_pnls)
    total_pnl = eq[-1] - cfg.initial_capital

    print(f"  --- 日次収益詳細 ---")
    print(f"  総取引日数       : {trading_days}日")
    print(f"  平均日次損益     : ¥{total_pnl/trading_days:+,.0f}")
    print(f"  日次損益中央値   : ¥{np.median(daily_pnls):+,.0f}")
    print(f"  日次損益標準偏差 : ¥{np.std(daily_pnls):,.0f}")
    print(f"  最大日次利益     : ¥{np.max(daily_pnls):+,.0f}")
    print(f"  最大日次損失     : ¥{np.min(daily_pnls):+,.0f}")

    # 破産リスク（資金が50%以下になったか）
    min_eq = min(eq)
    print(f"  最低資産額       : ¥{min_eq:,.0f} ({(min_eq/cfg.initial_capital-1)*100:+.1f}%)")
    print(f"  ¥5,000/日達成    : {'YES' if total_pnl/trading_days >= 5000 else 'NO'} (実績: ¥{total_pnl/trading_days:,.0f}/日)")

    # 月次ブレークダウン
    eq_df = pd.DataFrame({"date": dates[:len(eq_vals)], "equity": eq_vals[:len(dates)]})
    eq_df["ym"] = eq_df["date"].dt.strftime("%Y-%m")
    monthly = eq_df.groupby("ym")["equity"].last()
    prev = cfg.initial_capital
    neg_months = 0
    worst_month_pct = 0
    for ym, val in monthly.items():
        ret = (val - prev) / prev * 100
        if ret < worst_month_pct:
            worst_month_pct = ret
        if ret < 0:
            neg_months += 1
        prev = val
    print(f"  負け月数         : {neg_months}/{len(monthly)}ヶ月")
    print(f"  最悪月リターン   : {worst_month_pct:+.1f}%")
    print(f"{'='*60}")

    return stats


if __name__ == "__main__":
    df = load_gold_data()
    trading_days = len(df) - max(50, 14) - 1  # warmup除外

    print(f"目標: 日次 ¥5,000 以上")
    print(f"取引日数: 約{trading_days}日")
    print(f"目標総利益: ¥{5000 * trading_days:,.0f}")
    print()

    configs = [
        # リスク%を段階的に上げる（ベストロジック v5 LO+Reentry+Mom）
        ("v5 R5% Lev50x",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.05,
                        long_only=True, use_reentry=True, momentum_period=40, max_leverage=50)),
        ("v5 R8% Lev50x",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.08,
                        long_only=True, use_reentry=True, momentum_period=40, max_leverage=50)),
        ("v5 R10% Lev50x",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.10,
                        long_only=True, use_reentry=True, momentum_period=40, max_leverage=50)),
        ("v5 R10% Lev80x",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.10,
                        long_only=True, use_reentry=True, momentum_period=40, max_leverage=80)),
        ("v5 R15% Lev80x",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.15,
                        long_only=True, use_reentry=True, momentum_period=40, max_leverage=80)),
        ("v5 R15% Lev100x",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.15,
                        long_only=True, use_reentry=True, momentum_period=40, max_leverage=100)),
        ("v5 R20% Lev100x",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.20,
                        long_only=True, use_reentry=True, momentum_period=40, max_leverage=100)),
        ("v5 R20% Lev150x",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.20,
                        long_only=True, use_reentry=True, momentum_period=40, max_leverage=150)),

        # ストップを広げてより長く保有（利益を伸ばす）
        ("v5 R10% Lev80x ATR3.0/2.5",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.10,
                        atr_stop_multiplier=3.0, atr_trail_multiplier=2.5,
                        long_only=True, use_reentry=True, momentum_period=40, max_leverage=80)),
        ("v5 R15% Lev80x ATR3.0/2.5",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.15,
                        atr_stop_multiplier=3.0, atr_trail_multiplier=2.5,
                        long_only=True, use_reentry=True, momentum_period=40, max_leverage=80)),

        # 高速EMAでより頻繁に取引
        ("v5 EMA5/30 R10% Lev80x",
         BacktestConfig(ema_short=5, ema_long=30, risk_per_trade=0.10,
                        long_only=True, use_reentry=True, momentum_period=40, max_leverage=80)),
        ("v5 EMA5/30 R15% Lev80x",
         BacktestConfig(ema_short=5, ema_long=30, risk_per_trade=0.15,
                        long_only=True, use_reentry=True, momentum_period=40, max_leverage=80)),
    ]

    all_stats = []
    for label, cfg in configs:
        stats = detailed_report(df, cfg, label)
        if stats:
            all_stats.append(stats)

    # 比較表
    print(f"\n{'='*110}")
    print("  攻撃的パラメータ比較表")
    print(f"{'='*110}")
    print(f"  {'設定':<38} {'リターン':>9} {'DD':>7} {'Sharpe':>7} {'PF':>6} {'勝率':>6} {'取引':>4} {'日次PnL':>10}")
    print(f"  {'-'*108}")
    for s in sorted(all_stats, key=lambda x: x["return_pct"], reverse=True):
        daily_avg = s["total_pnl_jpy"] / trading_days
        mark = " ***" if daily_avg >= 5000 else ""
        print(
            f"  {s['label']:<38} "
            f"{s['return_pct']:>+8.1f}% "
            f"{s['max_drawdown_pct']:>6.1f}% "
            f"{s['sharpe_ratio']:>7.2f} "
            f"{s['profit_factor']:>6.2f} "
            f"{s['win_rate']:>5.1f}% "
            f"{s['total_trades']:>4} "
            f"¥{daily_avg:>+9,.0f}{mark}"
        )
    print(f"{'='*110}")
    print(f"  *** = 日次¥5,000以上達成")
