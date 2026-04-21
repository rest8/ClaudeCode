"""
高頻度スキャルピング戦略のバックテスト（ベクトル化版）
=====================================================
目標: 日次50回トレード、高勝率
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field


# =============================================================
# 1. 5分足データ生成
# =============================================================

def generate_5min_from_daily(daily_csv: str = "data/xauusd_daily.csv",
                              seed: int = 42) -> pd.DataFrame:
    daily = pd.read_csv(daily_csv, parse_dates=["date"])
    rng = np.random.default_rng(seed)

    bars_per_day = 264
    n_days = len(daily)
    total_bars = n_days * bars_per_day

    all_open = np.empty(total_bars)
    all_high = np.empty(total_bars)
    all_low = np.empty(total_bars)
    all_close = np.empty(total_bars)
    all_dt = []

    for day_idx in range(n_days):
        row = daily.iloc[day_idx]
        o, h, l, c = row["open"], row["high"], row["low"], row["close"]
        base = row["date"]
        n = bars_per_day
        s = day_idx * n

        raw = rng.normal(0, 1, n)
        cumsum = np.cumsum(raw)
        bridge = cumsum - np.arange(1, n + 1) / n * cumsum[-1]
        drift = np.arange(1, n + 1) / n * (np.log(c) - np.log(o))
        spread_range = np.max(bridge) - np.min(bridge)
        if spread_range > 1e-10:
            log_path = np.log(o) + bridge * (np.log(h) - np.log(l)) / spread_range * 0.4 + drift
        else:
            log_path = np.full(n, np.log(o)) + drift
        path = np.exp(log_path)

        raw_max, raw_min = np.max(path), np.min(path)
        if raw_max - raw_min > 1e-10:
            scaled = l + (path - raw_min) / (raw_max - raw_min) * (h - l)
            scaled[0] = o
            scaled[-1] = c
            path = scaled

        opens = np.empty(n)
        opens[0] = o
        opens[1:] = path[:-1]

        noise = np.abs(rng.normal(0, 1, n)) * (h - l) / n * 0.3
        highs = np.maximum(opens, path) + noise
        lows = np.minimum(opens, path) - noise

        all_open[s:s+n] = np.round(opens, 2)
        all_high[s:s+n] = np.round(highs, 2)
        all_low[s:s+n] = np.round(lows, 2)
        all_close[s:s+n] = np.round(path, 2)

        for i in range(n):
            all_dt.append(base + pd.Timedelta(minutes=5 * i))

    return pd.DataFrame({
        "datetime": all_dt,
        "open": all_open, "high": all_high,
        "low": all_low, "close": all_close,
    })


# =============================================================
# 2. ベクトル化バックテストエンジン
# =============================================================

@dataclass
class ScalpConfig:
    initial_capital: float = 200_000
    spread: float = 0.50
    jpy_per_usd: float = 150.0
    max_leverage: float = 100.0
    risk_per_trade: float = 0.005


def vectorized_backtest(df5: pd.DataFrame, signals: np.ndarray,
                         tp_dist: float, sl_dist: float,
                         cfg: ScalpConfig, label: str) -> dict:
    """
    signals: 長さ len(df5) の配列。 +1=LONG, -1=SHORT, 0=NO SIGNAL
    エントリー: signals!=0のバーのclose
    決済: 後続バーでTP/SLに到達した時点
    """
    closes = df5["close"].values
    highs = df5["high"].values
    lows = df5["low"].values
    n = len(closes)

    capital = cfg.initial_capital
    wins = 0
    losses = 0
    total_pnl = 0.0
    peak = capital
    max_dd = 0.0
    trade_pnls = []

    i = 0
    while i < n:
        if signals[i] == 0:
            i += 1
            continue

        side = signals[i]  # +1 or -1
        entry = closes[i] + (cfg.spread / 2 * side)

        if side == 1:  # LONG
            tp = entry + tp_dist
            sl = entry - sl_dist
        else:  # SHORT
            tp = entry - tp_dist
            sl = entry + sl_dist

        # エントリーはmid price。スプレッドは決済時に1回だけ控除
        entry = closes[i]

        if side == 1:  # LONG
            tp = entry + tp_dist
            sl = entry - sl_dist
        else:  # SHORT
            tp = entry - tp_dist
            sl = entry + sl_dist

        # ポジションサイズ
        risk_amount = capital * cfg.risk_per_trade
        lot = risk_amount / ((sl_dist + cfg.spread) * cfg.jpy_per_usd)
        max_lot = (capital * cfg.max_leverage) / (entry * cfg.jpy_per_usd)
        lot = min(lot, max_lot)

        # 後続バーを走査して決済
        j = i + 1
        settled = False
        while j < n:
            if side == 1:  # LONG
                # SL判定はbidで (low = bid近似)
                if lows[j] <= sl:
                    pnl_usd = -sl_dist - cfg.spread
                    losses += 1
                    settled = True
                    break
                # TP判定はbidで (high - spread/2 >= tp相当だが、簡略化)
                if highs[j] >= tp + cfg.spread:
                    pnl_usd = tp_dist - cfg.spread
                    wins += 1
                    settled = True
                    break
            else:  # SHORT
                if highs[j] >= sl:
                    pnl_usd = -sl_dist - cfg.spread
                    losses += 1
                    settled = True
                    break
                if lows[j] <= tp - cfg.spread:
                    pnl_usd = tp_dist - cfg.spread
                    wins += 1
                    settled = True
                    break
            j += 1

        if not settled:
            pnl_usd = (closes[-1] - entry) * side - cfg.spread
            if pnl_usd > 0:
                wins += 1
            else:
                losses += 1

        pnl_jpy = pnl_usd * lot * cfg.jpy_per_usd
        capital += pnl_jpy
        total_pnl += pnl_jpy
        trade_pnls.append(pnl_jpy)

        if capital > peak:
            peak = capital
        dd = (peak - capital) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

        if capital <= 0:
            break

        i = j + 1 if settled else n

    total_trades = wins + losses
    total_days = df5["datetime"].dt.date.nunique()
    trades_per_day = total_trades / total_days if total_days > 0 else 0
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    pnl_per_day = total_pnl / total_days if total_days > 0 else 0

    gross_w = sum(p for p in trade_pnls if p > 0)
    gross_l = abs(sum(p for p in trade_pnls if p <= 0))
    pf = gross_w / gross_l if gross_l > 0 else float("inf")
    avg_win = gross_w / wins if wins > 0 else 0
    avg_loss = -gross_l / losses if losses > 0 else 0

    return {
        "label": label,
        "total_trades": total_trades,
        "trades_per_day": trades_per_day,
        "wins": wins, "losses": losses,
        "win_rate": win_rate,
        "pf": pf,
        "total_pnl": total_pnl,
        "pnl_per_day": pnl_per_day,
        "final_capital": capital,
        "return_pct": (capital - cfg.initial_capital) / cfg.initial_capital * 100,
        "max_dd_pct": max_dd * 100,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
    }


# =============================================================
# 3. シグナル生成（全てベクトル化）
# =============================================================

def gen_bb_signals(df5, period=20, num_std=2.0):
    c = df5["close"].values
    sma = pd.Series(c).rolling(period).mean().values
    std = pd.Series(c).rolling(period).std().values
    upper = sma + num_std * std
    lower = sma - num_std * std

    signals = np.zeros(len(c), dtype=int)
    for i in range(period + 1, len(c)):
        if c[i] <= lower[i] and c[i-1] > lower[i-1]:
            signals[i] = 1   # LONG
        elif c[i] >= upper[i] and c[i-1] < upper[i-1]:
            signals[i] = -1  # SHORT
    return signals


def gen_rsi_signals(df5, period=6, oversold=25, overbought=75):
    c = pd.Series(df5["close"].values)
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(period).mean().values
    loss = (-delta.clip(upper=0)).rolling(period).mean().values
    rs = gain / (loss + 1e-10)
    rsi = 100 - 100 / (1 + rs)

    signals = np.zeros(len(c), dtype=int)
    for i in range(period + 2, len(c)):
        if rsi[i-1] < oversold and rsi[i] >= oversold:
            signals[i] = 1
        elif rsi[i-1] > overbought and rsi[i] <= overbought:
            signals[i] = -1
    return signals


def gen_vwap_signals(df5, period=48, entry_pct=0.0015):
    tp = (df5["high"].values + df5["low"].values + df5["close"].values) / 3
    vwap = pd.Series(tp).rolling(period).mean().values
    c = df5["close"].values

    signals = np.zeros(len(c), dtype=int)
    for i in range(period + 1, len(c)):
        dev = (c[i] - vwap[i]) / vwap[i]
        if dev < -entry_pct:
            signals[i] = 1
        elif dev > entry_pct:
            signals[i] = -1
    return signals


def gen_ema_signals(df5, fast=5, slow=13):
    c = pd.Series(df5["close"].values)
    f = c.ewm(span=fast, adjust=False).mean().values
    s = c.ewm(span=slow, adjust=False).mean().values

    signals = np.zeros(len(c), dtype=int)
    for i in range(slow + 1, len(c)):
        if f[i-1] <= s[i-1] and f[i] > s[i]:
            signals[i] = 1
        elif f[i-1] >= s[i-1] and f[i] < s[i]:
            signals[i] = -1
    return signals


# =============================================================
# 4. メイン
# =============================================================

if __name__ == "__main__":
    print("5分足データを生成中...")
    df5 = generate_5min_from_daily()
    total_days = df5["datetime"].dt.date.nunique()
    print(f"完了: {len(df5):,}本 ({total_days}日)\n")

    cfg = ScalpConfig()

    test_cases = []

    # === 高勝率型: TP小 / SL大（スプレッドに対してTPが十分大きい設定に限定）===
    # スプレッド$0.50に対し、TP最低$3以上が現実的
    for per, std_n in [(10, 2.0), (10, 1.5), (20, 2.0), (20, 1.5)]:
        sig = gen_bb_signals(df5, per, std_n)
        for tp, sl in [(3, 9), (4, 12), (5, 15), (3, 6), (4, 8), (5, 10), (3, 12), (5, 20)]:
            label = f"BB({per},{std_n}) TP${tp}/SL${sl}"
            test_cases.append((label, sig, float(tp), float(sl)))

    for per in [4, 6]:
        for os_v, ob_v in [(20, 80), (25, 75), (30, 70)]:
            sig = gen_rsi_signals(df5, per, os_v, ob_v)
            for tp, sl in [(3, 9), (4, 12), (5, 15), (3, 6), (4, 8), (5, 10)]:
                label = f"RSI({per}) {os_v}/{ob_v} TP${tp}/SL${sl}"
                test_cases.append((label, sig, float(tp), float(sl)))

    for per in [24, 48]:
        for ep in [0.0008, 0.0010, 0.0015, 0.0020]:
            sig = gen_vwap_signals(df5, per, ep)
            for tp, sl in [(3, 9), (4, 12), (5, 15), (3, 6), (5, 10)]:
                label = f"VWAP({per}) {ep*100:.2f}% TP${tp}/SL${sl}"
                test_cases.append((label, sig, float(tp), float(sl)))

    for fast, slow in [(3, 8), (5, 13), (3, 13)]:
        sig = gen_ema_signals(df5, fast, slow)
        for tp, sl in [(3, 9), (4, 12), (5, 15), (3, 6), (4, 8), (5, 10)]:
            label = f"EMA({fast}/{slow}) TP${tp}/SL${sl}"
            test_cases.append((label, sig, float(tp), float(sl)))

    # === 対称型: TP ≈ SL、純粋にシグナルの質で勝つ ===
    for per, std_n in [(10, 2.0), (20, 1.5)]:
        sig = gen_bb_signals(df5, per, std_n)
        for tp_sl in [3, 5, 8, 10]:
            label = f"BB({per},{std_n}) TP=SL=${tp_sl}"
            test_cases.append((label, sig, float(tp_sl), float(tp_sl)))

    for per in [4, 6]:
        for os_v, ob_v in [(25, 75), (30, 70)]:
            sig = gen_rsi_signals(df5, per, os_v, ob_v)
            for tp_sl in [3, 5, 8, 10]:
                label = f"RSI({per}) {os_v}/{ob_v} TP=SL=${tp_sl}"
                test_cases.append((label, sig, float(tp_sl), float(tp_sl)))

    print(f"テストケース数: {len(test_cases)}")
    all_stats = []
    for idx, (label, sig, tp, sl) in enumerate(test_cases):
        if (idx + 1) % 30 == 0:
            print(f"  ... {idx+1}/{len(test_cases)}")
        stats = vectorized_backtest(df5, sig, tp, sl, cfg, label)
        all_stats.append(stats)

    # 結果フィルタ & ソート
    # 日次30回以上でフィルタ
    active = [s for s in all_stats if s["trades_per_day"] >= 5]
    active.sort(key=lambda x: x["pnl_per_day"], reverse=True)

    print(f"\n{'='*130}")
    print(f"  スキャルピング戦略比較（取引5回/日以上、上位30件）")
    print(f"{'='*130}")
    print(f"  {'戦略':<42} {'総取引':>7} {'取引/日':>7} {'勝率':>6} {'PF':>6} {'日次PnL':>10} {'リターン':>9} {'DD':>6} {'平均勝':>10} {'平均負':>10}")
    print(f"  {'-'*128}")

    for s in active[:30]:
        mark = ""
        if s["trades_per_day"] >= 30 and s["pnl_per_day"] >= 5000:
            mark = " ***"
        elif s["trades_per_day"] >= 30 and s["win_rate"] >= 70:
            mark = " **"
        elif s["win_rate"] >= 70:
            mark = " *"
        print(
            f"  {s['label']:<42} "
            f"{s['total_trades']:>6,} "
            f"{s['trades_per_day']:>6.1f} "
            f"{s['win_rate']:>5.1f}% "
            f"{s['pf']:>6.2f} "
            f"¥{s['pnl_per_day']:>+9,.0f} "
            f"{s['return_pct']:>+8.1f}% "
            f"{s['max_dd_pct']:>5.1f}% "
            f"¥{s['avg_win']:>+9,.0f} "
            f"¥{s['avg_loss']:>+9,.0f}"
            f"{mark}"
        )

    # 高勝率ランキング
    high_wr = [s for s in all_stats if s["total_trades"] > 100]
    high_wr.sort(key=lambda x: x["win_rate"], reverse=True)

    print(f"\n{'='*130}")
    print(f"  勝率ランキング（100回以上取引、上位20件）")
    print(f"{'='*130}")
    print(f"  {'戦略':<42} {'総取引':>7} {'取引/日':>7} {'勝率':>6} {'PF':>6} {'日次PnL':>10} {'リターン':>9} {'DD':>6}")
    print(f"  {'-'*128}")

    for s in high_wr[:20]:
        print(
            f"  {s['label']:<42} "
            f"{s['total_trades']:>6,} "
            f"{s['trades_per_day']:>6.1f} "
            f"{s['win_rate']:>5.1f}% "
            f"{s['pf']:>6.2f} "
            f"¥{s['pnl_per_day']:>+9,.0f} "
            f"{s['return_pct']:>+8.1f}% "
            f"{s['max_dd_pct']:>5.1f}%"
        )
    print(f"{'='*130}")
