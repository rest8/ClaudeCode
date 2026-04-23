"""日次¥10,000以上を達成するパラメータ探索"""

import numpy as np
from backtest import load_gold_data, run_backtest, BacktestConfig


if __name__ == "__main__":
    df = load_gold_data()
    warmup = 51
    trading_days = len(df) - warmup

    configs = [
        ("R20% Lev100x", 0.20, 100),
        ("R25% Lev100x", 0.25, 100),
        ("R25% Lev150x", 0.25, 150),
        ("R30% Lev100x", 0.30, 100),
        ("R30% Lev150x", 0.30, 150),
        ("R35% Lev100x", 0.35, 100),
        ("R35% Lev150x", 0.35, 150),
        ("R40% Lev150x", 0.40, 150),
        ("R40% Lev200x", 0.40, 200),
    ]

    print(f"{'='*110}")
    print(f"  v5 LO+Reentry+Mom EMA10/50 — リスク段階別シミュレーション")
    print(f"  取引日数: {trading_days}日  目標: 日次¥10,000以上")
    print(f"{'='*110}")
    print(f"  {'設定':<22} {'最終資産':>14} {'総損益':>14} {'日次PnL':>10} {'リターン':>10} {'最大DD':>8} {'最低資産':>12} {'Sharpe':>7}")
    print(f"  {'-'*108}")

    for label, risk, lev in configs:
        cfg = BacktestConfig(
            ema_short=10, ema_long=50,
            risk_per_trade=risk, max_leverage=lev,
            long_only=True, use_reentry=True, momentum_period=40,
        )
        result = run_backtest(df, cfg)
        eq = result.equity_curve
        final = eq[-1]
        total_pnl = final - cfg.initial_capital
        daily_pnl = total_pnl / trading_days

        peak = eq[0]
        max_dd = 0
        min_eq = eq[0]
        for v in eq:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
            min_eq = min(min_eq, v)

        daily_ret = np.array([(eq[i] - eq[i-1]) / eq[i-1] for i in range(1, len(eq)) if eq[i-1] > 0])
        sharpe = np.mean(daily_ret) / np.std(daily_ret) * np.sqrt(252) if np.std(daily_ret) > 0 else 0

        ret_pct = (final - cfg.initial_capital) / cfg.initial_capital * 100
        mark = " <<<" if daily_pnl >= 10000 else ""

        print(
            f"  {label:<22} "
            f"¥{final:>13,.0f} "
            f"¥{total_pnl:>+13,.0f} "
            f"¥{daily_pnl:>+9,.0f} "
            f"{ret_pct:>+9.0f}% "
            f"{max_dd*100:>7.1f}% "
            f"¥{min_eq:>11,.0f} "
            f"{sharpe:>6.2f}"
            f"{mark}"
        )

    print(f"  {'-'*108}")
    print(f"  <<< = 日次¥10,000以上達成")
    print(f"{'='*110}")

    # 最低資産が0以下（破産）のケースを警告
    print(f"\n  ※ 最低資産 = バックテスト期間中に資産が最も減った時点の額")
    print(f"  ※ iFOREXではロスカット水準に達すると強制決済される点に注意")
