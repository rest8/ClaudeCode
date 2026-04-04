"""v5 LO+Reentry+Mom EMA10/50 R2% の月次収益レポート"""

import pandas as pd
import numpy as np
from backtest import load_gold_data, run_backtest, BacktestConfig, analyze


def monthly_report(df, cfg, label=""):
    result = run_backtest(df, cfg)

    # equity_curveとdfの日付を対応付ける
    warmup = max(cfg.ema_long, cfg.atr_period) + 1
    dates = df["date"].iloc[warmup:].reset_index(drop=True)
    eq = result.equity_curve[1:]  # 最初の1つは初期資金

    eq_df = pd.DataFrame({"date": dates[:len(eq)], "equity": eq[:len(dates)]})
    eq_df["ym"] = eq_df["date"].dt.strftime("%Y-%m")

    # 月末の資産額を取得
    monthly = eq_df.groupby("ym").agg(
        month_end_equity=("equity", "last"),
        month_end_date=("date", "last"),
    )

    # 月次リターン計算
    monthly["prev_equity"] = monthly["month_end_equity"].shift(1)
    monthly.loc[monthly.index[0], "prev_equity"] = cfg.initial_capital
    monthly["monthly_pnl"] = monthly["month_end_equity"] - monthly["prev_equity"]
    monthly["monthly_return_pct"] = monthly["monthly_pnl"] / monthly["prev_equity"] * 100

    # 月ごとの取引数
    trades_by_month = {}
    for t in result.trades:
        ym = t.entry_date[:7]
        if ym not in trades_by_month:
            trades_by_month[ym] = {"count": 0, "wins": 0, "pnl": 0}
        trades_by_month[ym]["count"] += 1
        trades_by_month[ym]["pnl"] += t.pnl
        if t.pnl > 0:
            trades_by_month[ym]["wins"] += 1

    print(f"\n{'='*90}")
    print(f"  {label} — 月次収益レポート")
    print(f"{'='*90}")
    print(f"  {'月':>8}  {'月末資産':>12}  {'月次損益':>12}  {'月次リターン':>10}  {'取引数':>5}  {'勝率':>6}")
    print(f"  {'-'*8}  {'-'*12}  {'-'*12}  {'-'*10}  {'-'*5}  {'-'*6}")

    for ym, row in monthly.iterrows():
        tm = trades_by_month.get(ym, {"count": 0, "wins": 0})
        wr = f"{tm['wins']/tm['count']*100:.0f}%" if tm["count"] > 0 else "-"
        print(
            f"  {ym:>8}  "
            f"¥{row['month_end_equity']:>11,.0f}  "
            f"¥{row['monthly_pnl']:>+11,.0f}  "
            f"{row['monthly_return_pct']:>+9.1f}%  "
            f"{tm['count']:>5}  "
            f"{wr:>6}"
        )

    # サマリー
    pos_months = (monthly["monthly_pnl"] > 0).sum()
    neg_months = (monthly["monthly_pnl"] <= 0).sum()
    avg_return = monthly["monthly_return_pct"].mean()
    best = monthly.loc[monthly["monthly_return_pct"].idxmax()]
    worst = monthly.loc[monthly["monthly_return_pct"].idxmin()]

    print(f"\n  --- サマリー ---")
    print(f"  期間             : {monthly.index[0]} 〜 {monthly.index[-1]} ({len(monthly)}ヶ月)")
    print(f"  勝ち月/負け月    : {pos_months}勝 / {neg_months}敗 ({pos_months/len(monthly)*100:.0f}%)")
    print(f"  平均月次リターン : {avg_return:+.2f}%")
    print(f"  最高月           : {best.name} ({best['monthly_return_pct']:+.1f}%  ¥{best['monthly_pnl']:+,.0f})")
    print(f"  最低月           : {worst.name} ({worst['monthly_return_pct']:+.1f}%  ¥{worst['monthly_pnl']:+,.0f})")
    print(f"  初期資金         : ¥{cfg.initial_capital:,.0f}")
    print(f"  最終資産         : ¥{monthly['month_end_equity'].iloc[-1]:,.0f}")
    print(f"  年率換算リターン : {avg_return * 12:+.1f}%")
    print(f"{'='*90}")

    return monthly


if __name__ == "__main__":
    df = load_gold_data()

    cfg = BacktestConfig(
        ema_short=10, ema_long=50,
        risk_per_trade=0.02, long_only=True,
        use_reentry=True, momentum_period=40,
    )

    analyze(run_backtest(df, cfg), "v5 LO+Reentry+Mom EMA10/50 R2%")
    monthly_report(df, cfg, "v5 LO+Reentry+Mom EMA10/50 R2%")
