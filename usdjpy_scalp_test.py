"""
USD/JPY vs XAU/USD スキャルピング比較テスト
==========================================
スプレッド対ボラティリティ比率が鍵。
"""

import numpy as np
import pandas as pd
from scalp_backtest import (
    gen_bb_signals, gen_rsi_signals, gen_vwap_signals, gen_ema_signals,
    vectorized_backtest, ScalpConfig,
)

# =============================================================
# 1. USD/JPY 月次実データ
# =============================================================
USDJPY_MONTHLY = {
    "2023-01": 130.1, "2023-02": 136.2, "2023-03": 132.8,
    "2023-04": 136.3, "2023-05": 139.3, "2023-06": 144.3,
    "2023-07": 142.3, "2023-08": 145.5, "2023-09": 149.4,
    "2023-10": 151.7, "2023-11": 148.2, "2023-12": 141.0,
    "2024-01": 146.9, "2024-02": 150.1, "2024-03": 151.3,
    "2024-04": 157.8, "2024-05": 157.3, "2024-06": 160.9,
    "2024-07": 153.0, "2024-08": 146.2, "2024-09": 143.6,
    "2024-10": 153.4, "2024-11": 150.3, "2024-12": 157.3,
    "2025-01": 155.2, "2025-02": 149.8, "2025-03": 149.2,
    "2025-04": 142.4, "2025-05": 145.0, "2025-06": 148.5,
    "2025-07": 152.0, "2025-08": 149.0, "2025-09": 146.5,
    "2025-10": 150.0, "2025-11": 153.0, "2025-12": 156.0,
    "2026-01": 158.0, "2026-02": 160.0, "2026-03": 157.0,
}
USDJPY_PREV = {"2022-12": 131.1}


# =============================================================
# 2. 5分足生成（USD/JPYの日次ボラに合わせる）
# =============================================================

import calendar
from datetime import datetime

def get_trading_days(year, month):
    _, last_day = calendar.monthrange(year, month)
    days = []
    for d in range(1, last_day + 1):
        dt = datetime(year, month, d)
        if dt.weekday() < 5:
            days.append(dt)
    return days


def generate_usdjpy_5min(seed=42):
    """USD/JPY 5分足データ生成（年率vol ≈ 10%）"""
    rng = np.random.default_rng(seed)
    bars_per_day = 264
    annual_vol = 0.10  # USD/JPYは金より低ボラ
    daily_vol = annual_vol / np.sqrt(252)

    sorted_months = sorted(USDJPY_MONTHLY.keys())
    all_rows = []

    for i, mk in enumerate(sorted_months):
        year, month = int(mk[:4]), int(mk[5:7])
        end_price = USDJPY_MONTHLY[mk]
        if i == 0:
            start_price = USDJPY_PREV["2022-12"]
        else:
            start_price = USDJPY_MONTHLY[sorted_months[i - 1]]

        tdays = get_trading_days(year, month)
        n_days = len(tdays)
        if n_days == 0:
            continue

        # 日足のクローズパスを生成（ブラウンブリッジ）
        log_start = np.log(start_price)
        log_end = np.log(end_price)
        daily_closes = [start_price]
        for d in range(1, n_days):
            remaining = n_days - d
            target_pull = (log_end - np.log(daily_closes[-1])) / (remaining + 1)
            noise = rng.normal(0, daily_vol) * np.sqrt(remaining / (remaining + 1))
            daily_closes.append(np.exp(np.log(daily_closes[-1]) + target_pull + noise))
        daily_closes[-1] = end_price

        # 各日 → 5分足に展開
        for d_idx, day_date in enumerate(tdays):
            day_close = daily_closes[d_idx]
            day_open = daily_closes[d_idx - 1] if d_idx > 0 else start_price

            # 日中レンジ（USD/JPY: 平均0.5-1.0円）
            day_range = abs(day_close - day_open) + abs(rng.normal(0, daily_vol * day_open))
            day_high = max(day_open, day_close) + abs(rng.normal(0, 1)) * day_range * 0.3
            day_low = min(day_open, day_close) - abs(rng.normal(0, 1)) * day_range * 0.3

            n = bars_per_day
            raw = rng.normal(0, 1, n)
            cumsum = np.cumsum(raw)
            bridge = cumsum - np.arange(1, n+1) / n * cumsum[-1]
            drift = np.arange(1, n+1) / n * (np.log(day_close) - np.log(day_open))
            sp = np.max(bridge) - np.min(bridge)
            if sp > 1e-10:
                log_path = np.log(day_open) + bridge * (np.log(day_high) - np.log(day_low)) / sp * 0.4 + drift
            else:
                log_path = np.full(n, np.log(day_open)) + drift
            path = np.exp(log_path)

            raw_max, raw_min = np.max(path), np.min(path)
            if raw_max - raw_min > 1e-10:
                path = day_low + (path - raw_min) / (raw_max - raw_min) * (day_high - day_low)
                path[0] = day_open
                path[-1] = day_close

            for bi in range(n):
                ts = pd.Timestamp(day_date) + pd.Timedelta(minutes=5 * bi)
                c = round(path[bi], 3)
                o = round(path[bi-1], 3) if bi > 0 else round(day_open, 3)
                noise = abs(rng.normal(0, 1)) * (day_high - day_low) / n * 0.3
                h = round(max(o, c) + noise, 3)
                l = round(min(o, c) - noise, 3)
                all_rows.append({"datetime": ts, "open": o, "high": h, "low": l, "close": c})

    return pd.DataFrame(all_rows)


# =============================================================
# 3. メイン比較テスト
# =============================================================

if __name__ == "__main__":
    # --- まずスプレッド対ボラティリティの数理比較 ---
    print("=" * 80)
    print("  スプレッド vs ボラティリティ 数理比較")
    print("=" * 80)

    instruments = [
        ("XAU/USD (ゴールド)", 3000, 0.50, 0.18, 30),    # 価格, spread$, 年率vol, 日中レンジ$
        ("USD/JPY",            150,  0.02, 0.10, 0.80),   # 価格, spread円, 年率vol, 日中レンジ円
    ]

    for name, price, spread, vol, day_range in instruments:
        vol_5min = day_range / np.sqrt(264)  # 5分のtyp変動
        vol_30min = day_range / np.sqrt(264/6)
        vol_1h = day_range / np.sqrt(264/12)

        print(f"\n  {name}")
        print(f"    価格: {price}, スプレッド: {spread}, 年率Vol: {vol*100}%")
        print(f"    日中レンジ: {day_range}")
        print(f"    5分間の典型変動   : {vol_5min:.3f}  スプレッド比: {spread/vol_5min*100:.1f}%")
        print(f"    30分間の典型変動  : {vol_30min:.3f}  スプレッド比: {spread/vol_30min*100:.1f}%")
        print(f"    1時間の典型変動   : {vol_1h:.3f}  スプレッド比: {spread/vol_1h*100:.1f}%")

        for tp_mult in [2, 3, 5, 8]:
            tp = vol_30min * tp_mult
            for sl_mult in [2, 3]:
                sl = tp * sl_mult
                net_win = tp - spread
                net_loss = sl + spread
                be_wr = net_loss / (net_win + net_loss) * 100
                print(f"    TP={tp:.2f} SL={sl:.2f} → 損益分岐勝率: {be_wr:.1f}%")

    # --- USD/JPY 5分足バックテスト ---
    print(f"\n\n{'='*80}")
    print("  USD/JPY スキャルピングバックテスト")
    print(f"{'='*80}")

    print("\n5分足データ生成中...")
    df5 = generate_usdjpy_5min()
    total_days = df5["datetime"].dt.date.nunique()
    print(f"完了: {len(df5):,}本 ({total_days}日)")
    print(f"価格レンジ: {df5['close'].min():.3f} ~ {df5['close'].max():.3f}")

    # USD/JPY: spread = 0.02円 (2pips)
    cfg = ScalpConfig(spread=0.02, jpy_per_usd=1.0)
    # jpy_per_usd=1.0: USD/JPYの場合、1ロットの1pip変動 = 1円の損益（直接円建て）

    # TP/SLはpip単位で設定（1pip = 0.01円だが、ここでは値幅そのものを指定）
    test_cases = []

    for per, std_n in [(10, 2.0), (10, 1.5), (20, 2.0), (20, 1.5)]:
        sig = gen_bb_signals(df5, per, std_n)
        for tp, sl in [(0.05, 0.15), (0.08, 0.24), (0.10, 0.30), (0.10, 0.20),
                        (0.15, 0.30), (0.15, 0.45), (0.20, 0.40), (0.20, 0.60)]:
            label = f"BB({per},{std_n}) TP{tp}/SL{sl}"
            test_cases.append((label, sig, tp, sl))

    for per in [4, 6]:
        for os_v, ob_v in [(25, 75), (30, 70)]:
            sig = gen_rsi_signals(df5, per, os_v, ob_v)
            for tp, sl in [(0.05, 0.15), (0.08, 0.24), (0.10, 0.30),
                            (0.15, 0.30), (0.15, 0.45), (0.20, 0.60)]:
                label = f"RSI({per}) {os_v}/{ob_v} TP{tp}/SL{sl}"
                test_cases.append((label, sig, tp, sl))

    for per in [24, 48]:
        for ep in [0.0003, 0.0005, 0.0008]:
            sig = gen_vwap_signals(df5, per, ep)
            for tp, sl in [(0.05, 0.15), (0.08, 0.24), (0.10, 0.30), (0.15, 0.45)]:
                label = f"VWAP({per}) {ep*100:.2f}% TP{tp}/SL{sl}"
                test_cases.append((label, sig, tp, sl))

    for fast, slow in [(3, 8), (5, 13)]:
        sig = gen_ema_signals(df5, fast, slow)
        for tp, sl in [(0.05, 0.15), (0.08, 0.24), (0.10, 0.30),
                        (0.15, 0.30), (0.15, 0.45), (0.20, 0.60)]:
            label = f"EMA({fast}/{slow}) TP{tp}/SL{sl}"
            test_cases.append((label, sig, tp, sl))

    print(f"\nテストケース数: {len(test_cases)}")
    all_stats = []
    for idx, (label, sig, tp, sl) in enumerate(test_cases):
        if (idx + 1) % 50 == 0:
            print(f"  ... {idx+1}/{len(test_cases)}")
        stats = vectorized_backtest(df5, sig, tp, sl, cfg, label)
        all_stats.append(stats)

    # 結果
    active = [s for s in all_stats if s["total_trades"] >= 100]
    active.sort(key=lambda x: x["pnl_per_day"], reverse=True)

    print(f"\n{'='*120}")
    print(f"  USD/JPY スキャルピング結果（上位20 & 高勝率上位10）")
    print(f"{'='*120}")
    print(f"  {'戦略':<40} {'総取引':>7} {'回/日':>6} {'勝率':>6} {'PF':>6} {'日次PnL':>10} {'リターン':>9} {'DD':>6}")
    print(f"  {'-'*118}")
    for s in active[:20]:
        mark = " ***" if s["pnl_per_day"] > 0 and s["trades_per_day"] >= 10 else ""
        print(
            f"  {s['label']:<40} "
            f"{s['total_trades']:>6,} "
            f"{s['trades_per_day']:>5.1f} "
            f"{s['win_rate']:>5.1f}% "
            f"{s['pf']:>6.2f} "
            f"¥{s['pnl_per_day']:>+9,.0f} "
            f"{s['return_pct']:>+8.1f}% "
            f"{s['max_dd_pct']:>5.1f}%"
            f"{mark}"
        )

    # 高勝率ランキング
    high_wr = sorted(active, key=lambda x: x["win_rate"], reverse=True)
    print(f"\n  --- 勝率ランキング上位10 ---")
    for s in high_wr[:10]:
        print(
            f"  {s['label']:<40} "
            f"{s['total_trades']:>6,} "
            f"{s['trades_per_day']:>5.1f} "
            f"{s['win_rate']:>5.1f}% "
            f"{s['pf']:>6.2f} "
            f"¥{s['pnl_per_day']:>+9,.0f} "
            f"{s['return_pct']:>+8.1f}% "
            f"{s['max_dd_pct']:>5.1f}%"
        )

    # プラス収益の戦略があるか？
    profitable = [s for s in all_stats if s["pnl_per_day"] > 0]
    print(f"\n{'='*80}")
    print(f"  プラス収益の戦略数: {len(profitable)} / {len(all_stats)}")
    if profitable:
        profitable.sort(key=lambda x: x["pnl_per_day"], reverse=True)
        for s in profitable[:10]:
            print(
                f"    {s['label']:<40} "
                f"回/日:{s['trades_per_day']:>5.1f} "
                f"勝率:{s['win_rate']:>5.1f}% "
                f"PF:{s['pf']:>5.2f} "
                f"日次:¥{s['pnl_per_day']:>+,.0f}"
            )
    print(f"{'='*80}")
