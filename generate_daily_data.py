"""
実際の月次終値からリアルな日足OHLCデータを生成する。

- 月次終値は World Gold Council の実データ（datasets/gold-prices）
- 日足は制約付きブラウンブリッジで月末終値に収束
- 日次ボラティリティはゴールドの実測値（年率~18%）を使用
- 乱数シードを固定して再現性を確保
"""

import numpy as np
import pandas as pd
import calendar
from datetime import datetime, timedelta


MONTHLY_PRICES = {
    "2023-01": 1897.71, "2023-02": 1854.54, "2023-03": 1912.73,
    "2023-04": 1999.77, "2023-05": 1992.13, "2023-06": 1942.90,
    "2023-07": 1951.02, "2023-08": 1918.70, "2023-09": 1915.95,
    "2023-10": 1916.25, "2023-11": 1984.11, "2023-12": 2026.18,
    "2024-01": 2034.04, "2024-02": 2023.24, "2024-03": 2158.01,
    "2024-04": 2331.45, "2024-05": 2351.13, "2024-06": 2326.44,
    "2024-07": 2398.20, "2024-08": 2470.15, "2024-09": 2570.55,
    "2024-10": 2690.08, "2024-11": 2651.13, "2024-12": 2648.01,
    "2025-01": 2709.69, "2025-02": 2894.73, "2025-03": 2983.25,
    "2025-04": 3217.64, "2025-05": 3309.49, "2025-06": 3352.66,
    "2025-07": 3340.15, "2025-08": 3368.03, "2025-09": 3667.68,
    "2025-10": 4058.33, "2025-11": 4087.19, "2025-12": 4309.23,
    "2026-01": 4752.75, "2026-02": 5019.97, "2026-03": 4855.54,
}

# 前月分（開始価格として必要）
PREV_CLOSE = {"2022-12": 1797.55}


def get_trading_days(year: int, month: int) -> list:
    """月の営業日（月〜金）のリストを返す"""
    _, last_day = calendar.monthrange(year, month)
    days = []
    for d in range(1, last_day + 1):
        dt = datetime(year, month, d)
        if dt.weekday() < 5:  # Mon-Fri
            days.append(dt)
    return days


def generate_month(start_price: float, end_price: float,
                   trading_days: list, rng: np.random.Generator,
                   annual_vol: float = 0.18) -> pd.DataFrame:
    """ブラウンブリッジで1ヶ月分の日足OHLCを生成"""
    n = len(trading_days)
    if n == 0:
        return pd.DataFrame()

    daily_vol = annual_vol / np.sqrt(252)

    # ブラウンブリッジ: 始点=start_price, 終点=end_price
    log_start = np.log(start_price)
    log_end = np.log(end_price)
    drift = (log_end - log_start) / n

    closes = [start_price]
    for i in range(1, n):
        remaining = n - i
        # ブリッジ: 目標に向かう成分 + ランダム成分
        target_pull = (log_end - np.log(closes[-1])) / (remaining + 1)
        noise = rng.normal(0, daily_vol)
        log_price = np.log(closes[-1]) + target_pull + noise * np.sqrt(remaining / (remaining + 1))
        closes.append(np.exp(log_price))

    # 最終日を月末終値に強制
    closes[-1] = end_price

    rows = []
    prev_close = start_price
    for i, day in enumerate(trading_days):
        close = closes[i]

        # Open: 前日終値の近傍（ギャップ）
        gap = rng.normal(0, daily_vol * 0.3)
        open_price = prev_close * np.exp(gap)

        # High/Low: close/openの範囲を拡張
        day_range = abs(close - open_price)
        base_range = prev_close * daily_vol
        extra_range = max(day_range * 0.2, base_range * abs(rng.normal(0, 0.5)))

        high = max(open_price, close) + abs(extra_range * abs(rng.normal(0, 1)))
        low = min(open_price, close) - abs(extra_range * abs(rng.normal(0, 1)))

        # 最低限のスプレッド確保
        if high - low < prev_close * 0.002:
            mid = (high + low) / 2
            high = mid + prev_close * 0.001
            low = mid - prev_close * 0.001

        rows.append({
            "date": day,
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
        })
        prev_close = close

    return pd.DataFrame(rows)


def generate_full_dataset(seed: int = 42) -> pd.DataFrame:
    """2023年1月〜2026年3月のゴールド日足OHLCデータを生成"""
    rng = np.random.default_rng(seed)

    all_dfs = []
    sorted_months = sorted(MONTHLY_PRICES.keys())

    for i, month_key in enumerate(sorted_months):
        year, month = int(month_key[:4]), int(month_key[5:7])
        end_price = MONTHLY_PRICES[month_key]

        # 前月の終値を開始価格とする
        if i == 0:
            start_price = PREV_CLOSE.get("2022-12", end_price * 0.95)
        else:
            prev_key = sorted_months[i - 1]
            start_price = MONTHLY_PRICES[prev_key]

        trading_days = get_trading_days(year, month)
        df = generate_month(start_price, end_price, trading_days, rng)
        all_dfs.append(df)

    result = pd.concat(all_dfs, ignore_index=True)

    # Volume（ゴールドの典型的な出来高レンジ）
    result["volume"] = (rng.lognormal(10, 0.5, len(result))).astype(int)

    return result


if __name__ == "__main__":
    df = generate_full_dataset()
    output_path = "data/xauusd_daily.csv"

    import os
    os.makedirs("data", exist_ok=True)
    df.to_csv(output_path, index=False)

    print(f"生成完了: {len(df)}営業日分")
    print(f"期間: {df['date'].iloc[0].date()} 〜 {df['date'].iloc[-1].date()}")
    print(f"価格レンジ: ${df['close'].min():.2f} 〜 ${df['close'].max():.2f}")
    print(f"\n月次終値のサンプル確認:")
    # 各月末の終値を表示して、実データと一致するか確認
    df["ym"] = df["date"].dt.strftime("%Y-%m")
    monthly_check = df.groupby("ym")["close"].last()
    for ym, price in monthly_check.items():
        actual = MONTHLY_PRICES.get(ym, None)
        if actual:
            diff = abs(price - actual) / actual * 100
            mark = "OK" if diff < 0.01 else f"DIFF {diff:.2f}%"
            print(f"  {ym}: generated=${price:.2f}  actual=${actual:.2f}  [{mark}]")
    print(f"\n保存先: {output_path}")
