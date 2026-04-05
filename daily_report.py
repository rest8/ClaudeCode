"""v5 R20% Lev100x の日次リターン推移レポート"""

import pandas as pd
import numpy as np
from backtest import load_gold_data, run_backtest, BacktestConfig


if __name__ == "__main__":
    df = load_gold_data()

    cfg = BacktestConfig(
        ema_short=10, ema_long=50,
        risk_per_trade=0.20, max_leverage=100,
        long_only=True, use_reentry=True, momentum_period=40,
    )

    result = run_backtest(df, cfg)

    warmup = max(cfg.ema_long, cfg.atr_period) + 1
    dates = df["date"].iloc[warmup:].reset_index(drop=True)
    eq = result.equity_curve[1:]

    eq_df = pd.DataFrame({
        "date": dates[:len(eq)],
        "equity": eq[:len(dates)],
    })
    eq_df["prev_equity"] = eq_df["equity"].shift(1)
    eq_df.loc[eq_df.index[0], "prev_equity"] = cfg.initial_capital
    eq_df["daily_pnl"] = eq_df["equity"] - eq_df["prev_equity"]
    eq_df["daily_return_pct"] = eq_df["daily_pnl"] / eq_df["prev_equity"] * 100
    eq_df["cumulative_pnl"] = eq_df["equity"] - cfg.initial_capital

    # トレード期間のマップ（ポジション有無）
    trade_dates = set()
    for t in result.trades:
        d1 = pd.Timestamp(t.entry_date)
        d2 = pd.Timestamp(t.exit_date)
        cur = d1
        while cur <= d2:
            if cur.weekday() < 5:
                trade_dates.add(cur.normalize())
            cur += pd.Timedelta(days=1)

    eq_df["in_position"] = eq_df["date"].dt.normalize().isin(trade_dates)

    # --- 日次テーブル出力 ---
    print(f"{'='*100}")
    print(f"  v5 R20% Lev100x — 日次リターン推移")
    print(f"{'='*100}")
    print(f"  {'日付':>12}  {'資産額':>12}  {'日次損益':>12}  {'日次%':>8}  {'累計損益':>14}  {'状態':>6}")
    print(f"  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*8}  {'-'*14}  {'-'*6}")

    # 全日出力は多すぎるので、動きがあった日 + 月初・月末を出力
    prev_ym = ""
    for _, row in eq_df.iterrows():
        ym = row["date"].strftime("%Y-%m")
        is_month_boundary = (ym != prev_ym)
        has_pnl = abs(row["daily_pnl"]) >= 1
        prev_ym = ym

        if has_pnl or is_month_boundary:
            status = "TRADE" if row["in_position"] and has_pnl else ""
            print(
                f"  {row['date'].strftime('%Y-%m-%d'):>12}  "
                f"¥{row['equity']:>11,.0f}  "
                f"¥{row['daily_pnl']:>+11,.0f}  "
                f"{row['daily_return_pct']:>+7.2f}%  "
                f"¥{row['cumulative_pnl']:>+13,.0f}  "
                f"{status:>6}"
            )

    # --- 月次サマリー ---
    eq_df["ym"] = eq_df["date"].dt.strftime("%Y-%m")
    monthly = eq_df.groupby("ym").agg(
        month_end=("equity", "last"),
        max_equity=("equity", "max"),
        min_equity=("equity", "min"),
        trade_days=("in_position", "sum"),
        total_days=("equity", "count"),
    )
    monthly["prev_end"] = monthly["month_end"].shift(1)
    monthly.loc[monthly.index[0], "prev_end"] = cfg.initial_capital
    monthly["pnl"] = monthly["month_end"] - monthly["prev_end"]
    monthly["ret_pct"] = monthly["pnl"] / monthly["prev_end"] * 100

    print(f"\n{'='*100}")
    print(f"  月次サマリー")
    print(f"{'='*100}")
    print(f"  {'月':>8}  {'月末資産':>12}  {'月次損益':>14}  {'月次%':>8}  {'月中最高':>12}  {'月中最低':>12}  {'取引日':>5}")
    print(f"  {'-'*8}  {'-'*12}  {'-'*14}  {'-'*8}  {'-'*12}  {'-'*12}  {'-'*5}")
    for ym, row in monthly.iterrows():
        print(
            f"  {ym:>8}  "
            f"¥{row['month_end']:>11,.0f}  "
            f"¥{row['pnl']:>+13,.0f}  "
            f"{row['ret_pct']:>+7.1f}%  "
            f"¥{row['max_equity']:>11,.0f}  "
            f"¥{row['min_equity']:>11,.0f}  "
            f"{int(row['trade_days']):>5}"
        )

    # --- 統計 ---
    active = eq_df[eq_df["daily_pnl"].abs() >= 1]
    print(f"\n{'='*100}")
    print(f"  統計サマリー")
    print(f"{'='*100}")
    print(f"  初期資金           : ¥{cfg.initial_capital:,.0f}")
    print(f"  最終資産           : ¥{eq_df['equity'].iloc[-1]:,.0f}")
    print(f"  総損益             : ¥{eq_df['cumulative_pnl'].iloc[-1]:+,.0f}")
    print(f"  総取引日数         : {len(eq_df)}日")
    print(f"  ポジション保有日数 : {eq_df['in_position'].sum()}日")
    print(f"  損益発生日数       : {len(active)}日")
    print(f"  平均日次損益(全日) : ¥{eq_df['daily_pnl'].mean():+,.0f}")
    print(f"  平均日次損益(稼働日): ¥{active['daily_pnl'].mean():+,.0f}" if len(active) > 0 else "")
    print(f"  日次損益中央値     : ¥{eq_df['daily_pnl'].median():+,.0f}")
    print(f"  日次最大利益       : ¥{eq_df['daily_pnl'].max():+,.0f}")
    print(f"  日次最大損失       : ¥{eq_df['daily_pnl'].min():+,.0f}")
    print(f"  最高資産額         : ¥{eq_df['equity'].max():,.0f}")
    print(f"  最低資産額         : ¥{eq_df['equity'].min():,.0f}")
    win_days = (active["daily_pnl"] > 0).sum()
    lose_days = (active["daily_pnl"] < 0).sum()
    print(f"  プラス日 / マイナス日 : {win_days}日 / {lose_days}日 ({win_days/(win_days+lose_days)*100:.0f}%)" if (win_days+lose_days) > 0 else "")
    print(f"{'='*100}")
