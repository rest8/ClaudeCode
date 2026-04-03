"""
iFOREX Gold (XAU/USD) Trend Following Strategy — Backtest
==========================================================
過去3年分のゴールド日足データでトレンドフォロー戦略を検証する。

戦略概要:
  - EMA(短期) と EMA(長期) のクロスでトレンド方向を判定
  - ATR でボラティリティを計測し、ストップロスとポジションサイズを動的制御
  - リスク管理: 1トレードあたり資金のX%をリスクにさらす
  - トレーリングストップ: ATR の N倍で追従

ルール（先読みバイアスなし）:
  - 全てのシグナルは当日の終値確定後に判定、翌日の始値で約定と仮定
  - インジケータは当日までのデータのみで計算
"""

import datetime
import numpy as np
import pandas as pd
from dataclasses import dataclass, field


# ============================================================
# 1. データ取得
# ============================================================

def load_gold_data(csv_path: str = "data/xauusd_daily.csv") -> pd.DataFrame:
    """CSVから日足データを読み込む"""
    df = pd.read_csv(csv_path, parse_dates=["date"])
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    return df


# ============================================================
# 2. インジケータ計算
# ============================================================

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


# ============================================================
# 3. バックテストエンジン
# ============================================================

@dataclass
class Trade:
    entry_date: str
    exit_date: str
    side: str  # "LONG" or "SHORT"
    entry_price: float
    exit_price: float
    lot_size: float
    pnl: float
    pnl_pct: float  # 資金に対する損益率
    capital_at_entry: float


@dataclass
class BacktestConfig:
    initial_capital: float = 200_000       # 20万円
    ema_short: int = 20                    # 短期EMA期間
    ema_long: int = 50                     # 長期EMA期間
    atr_period: int = 14                   # ATR期間
    atr_stop_multiplier: float = 2.5       # ストップロス = ATR × N
    atr_trail_multiplier: float = 2.0      # トレーリングストップ = ATR × N
    risk_per_trade: float = 0.02           # 1トレードあたりリスク（資金の2%）
    max_leverage: float = 25.0             # 最大レバレッジ（200x中25xに制限）
    spread_pips: float = 0.50              # スプレッド（ゴールド: 約$0.50）
    jpy_per_usd: float = 150.0            # 円ドル換算（概算）
    # === 改良版フィルター ===
    long_only: bool = False                # True: ロング（買い）のみ
    momentum_period: int = 0               # >0: N日モメンタムフィルター有効化
    use_ema_slope: bool = False            # EMAの傾きでトレンド強度をフィルター
    use_reentry: bool = False              # EMAクロスだけでなく押し目/戻りでも再エントリー


@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    daily_returns: list = field(default_factory=list)


def run_backtest(df: pd.DataFrame, cfg: BacktestConfig) -> BacktestResult:
    """メインのバックテストループ（先読みバイアスなし）"""

    # インジケータ計算（全期間で一括計算するが、シグナルは当日終値まで）
    df = df.copy()
    df["ema_short"] = calc_ema(df["close"], cfg.ema_short)
    df["ema_long"] = calc_ema(df["close"], cfg.ema_long)
    df["atr"] = calc_atr(df, cfg.atr_period)
    if cfg.momentum_period > 0:
        df["momentum"] = df["close"] / df["close"].shift(cfg.momentum_period) - 1
    if cfg.use_ema_slope:
        df["ema_long_slope"] = df["ema_long"] - df["ema_long"].shift(5)

    capital = cfg.initial_capital
    position = None  # {"side", "entry_price", "lot_size", "stop_loss", "trail_stop"}
    result = BacktestResult(config=cfg)
    result.equity_curve.append(capital)

    warmup = max(cfg.ema_long, cfg.atr_period) + 1

    for i in range(warmup, len(df)):
        # 当日のデータ（シグナル判定用: 前日までの終値で計算されたインジケータ）
        # EMA/ATRは当日終値を含むが、エントリーは翌日始値なので先読みではない
        prev = df.iloc[i - 1]  # 前日（シグナル判定日）
        today = df.iloc[i]     # 当日（約定日 — 始値で約定）

        if pd.isna(prev["atr"]) or prev["atr"] == 0:
            result.equity_curve.append(capital)
            continue

        execution_price = today["open"]  # 翌日始値で約定

        # --- ポジション保有中の処理 ---
        if position is not None:
            # トレーリングストップの更新（前日の終値ベース）
            current_atr = prev["atr"]

            if position["side"] == "LONG":
                new_trail = prev["close"] - cfg.atr_trail_multiplier * current_atr
                position["trail_stop"] = max(position["trail_stop"], new_trail)
                stop = position["trail_stop"]

                # 当日の安値がストップに到達したか
                if today["low"] <= stop:
                    exit_price = max(stop, today["open"])  # ギャップダウン時は始値
                    if today["open"] <= stop:
                        exit_price = today["open"]
                    pnl_per_unit = exit_price - position["entry_price"] - cfg.spread_pips
                    pnl = pnl_per_unit * position["lot_size"] * cfg.jpy_per_usd
                    pnl_pct = pnl / position["capital_at_entry"]
                    result.trades.append(Trade(
                        entry_date=position["entry_date"],
                        exit_date=str(today["date"].date()),
                        side="LONG", entry_price=position["entry_price"],
                        exit_price=exit_price, lot_size=position["lot_size"],
                        pnl=pnl, pnl_pct=pnl_pct,
                        capital_at_entry=position["capital_at_entry"],
                    ))
                    capital += pnl
                    position = None

            elif position["side"] == "SHORT":
                new_trail = prev["close"] + cfg.atr_trail_multiplier * current_atr
                position["trail_stop"] = min(position["trail_stop"], new_trail)
                stop = position["trail_stop"]

                if today["high"] >= stop:
                    exit_price = min(stop, today["open"])
                    if today["open"] >= stop:
                        exit_price = today["open"]
                    pnl_per_unit = position["entry_price"] - exit_price - cfg.spread_pips
                    pnl = pnl_per_unit * position["lot_size"] * cfg.jpy_per_usd
                    pnl_pct = pnl / position["capital_at_entry"]
                    result.trades.append(Trade(
                        entry_date=position["entry_date"],
                        exit_date=str(today["date"].date()),
                        side="SHORT", entry_price=position["entry_price"],
                        exit_price=exit_price, lot_size=position["lot_size"],
                        pnl=pnl, pnl_pct=pnl_pct,
                        capital_at_entry=position["capital_at_entry"],
                    ))
                    capital += pnl
                    position = None

            # トレンド反転による決済（前日のEMAクロス）
            if position is not None:
                if position["side"] == "LONG" and prev["ema_short"] < prev["ema_long"]:
                    pnl_per_unit = execution_price - position["entry_price"] - cfg.spread_pips
                    pnl = pnl_per_unit * position["lot_size"] * cfg.jpy_per_usd
                    pnl_pct = pnl / position["capital_at_entry"]
                    result.trades.append(Trade(
                        entry_date=position["entry_date"],
                        exit_date=str(today["date"].date()),
                        side="LONG", entry_price=position["entry_price"],
                        exit_price=execution_price, lot_size=position["lot_size"],
                        pnl=pnl, pnl_pct=pnl_pct,
                        capital_at_entry=position["capital_at_entry"],
                    ))
                    capital += pnl
                    position = None

                elif position is not None and position["side"] == "SHORT" and prev["ema_short"] > prev["ema_long"]:
                    pnl_per_unit = position["entry_price"] - execution_price - cfg.spread_pips
                    pnl = pnl_per_unit * position["lot_size"] * cfg.jpy_per_usd
                    pnl_pct = pnl / position["capital_at_entry"]
                    result.trades.append(Trade(
                        entry_date=position["entry_date"],
                        exit_date=str(today["date"].date()),
                        side="SHORT", entry_price=position["entry_price"],
                        exit_price=execution_price, lot_size=position["lot_size"],
                        pnl=pnl, pnl_pct=pnl_pct,
                        capital_at_entry=position["capital_at_entry"],
                    ))
                    capital += pnl
                    position = None

        # --- 新規エントリー判定（前日のEMAクロスで判定、当日始値で約定）---
        if position is None and capital > 0:
            prev_prev = df.iloc[i - 2] if i >= 2 else None

            if prev_prev is not None and not pd.isna(prev_prev["ema_short"]):
                # ゴールデンクロス: 前々日 short<=long かつ 前日 short>long
                golden_cross = (
                    prev_prev["ema_short"] <= prev_prev["ema_long"]
                    and prev["ema_short"] > prev["ema_long"]
                )
                # デッドクロス: 前々日 short>=long かつ 前日 short<long
                dead_cross = (
                    prev_prev["ema_short"] >= prev_prev["ema_long"]
                    and prev["ema_short"] < prev["ema_long"]
                )

                # 押し目買い/戻り売りの再エントリー判定
                if cfg.use_reentry and not golden_cross and not dead_cross:
                    if prev["ema_short"] > prev["ema_long"]:
                        # 上昇トレンド中の押し目: 前日の安値がEMA短期に接近
                        if prev["low"] <= prev["ema_short"] * 1.005:
                            golden_cross = True
                    elif prev["ema_short"] < prev["ema_long"]:
                        # 下降トレンド中の戻り: 前日の高値がEMA短期に接近
                        if prev["high"] >= prev["ema_short"] * 0.995:
                            dead_cross = True

                # ロングオンリーモードではデッドクロスを無視
                if cfg.long_only:
                    dead_cross = False

                # モメンタムフィルター
                if cfg.momentum_period > 0 and not pd.isna(prev.get("momentum", float("nan"))):
                    if golden_cross and prev["momentum"] < 0:
                        golden_cross = False  # 下降モメンタム中の買いシグナルを却下
                    if dead_cross and prev["momentum"] > 0:
                        dead_cross = False    # 上昇モメンタム中の売りシグナルを却下

                # EMAスロープフィルター
                if cfg.use_ema_slope and not pd.isna(prev.get("ema_long_slope", float("nan"))):
                    if golden_cross and prev["ema_long_slope"] < 0:
                        golden_cross = False  # 長期EMAが下向きなら買わない
                    if dead_cross and prev["ema_long_slope"] > 0:
                        dead_cross = False    # 長期EMAが上向きなら売らない

                if golden_cross or dead_cross:
                    side = "LONG" if golden_cross else "SHORT"
                    atr = prev["atr"]
                    stop_distance = cfg.atr_stop_multiplier * atr  # ドル建て

                    # ポジションサイズ計算: リスク額 / (ストップ幅 × 円換算)
                    risk_amount = capital * cfg.risk_per_trade
                    lot_size = risk_amount / (stop_distance * cfg.jpy_per_usd)

                    # レバレッジ上限チェック
                    position_value = lot_size * execution_price * cfg.jpy_per_usd
                    max_position = capital * cfg.max_leverage
                    if position_value > max_position:
                        lot_size = max_position / (execution_price * cfg.jpy_per_usd)

                    if lot_size < 0.01:
                        result.equity_curve.append(capital)
                        continue

                    if side == "LONG":
                        stop_loss = execution_price - stop_distance
                        trail_stop = stop_loss
                    else:
                        stop_loss = execution_price + stop_distance
                        trail_stop = stop_loss

                    position = {
                        "side": side,
                        "entry_price": execution_price,
                        "lot_size": round(lot_size, 4),
                        "stop_loss": stop_loss,
                        "trail_stop": trail_stop,
                        "entry_date": str(today["date"].date()),
                        "capital_at_entry": capital,
                    }

        result.equity_curve.append(capital)

    # 未決済ポジションの強制決済（最終日終値）
    if position is not None:
        last = df.iloc[-1]
        if position["side"] == "LONG":
            pnl_per_unit = last["close"] - position["entry_price"] - cfg.spread_pips
        else:
            pnl_per_unit = position["entry_price"] - last["close"] - cfg.spread_pips
        pnl = pnl_per_unit * position["lot_size"] * cfg.jpy_per_usd
        pnl_pct = pnl / position["capital_at_entry"]
        result.trades.append(Trade(
            entry_date=position["entry_date"],
            exit_date=str(last["date"].date()),
            side=position["side"], entry_price=position["entry_price"],
            exit_price=last["close"], lot_size=position["lot_size"],
            pnl=pnl, pnl_pct=pnl_pct,
            capital_at_entry=position["capital_at_entry"],
        ))
        capital += pnl
        result.equity_curve[-1] = capital

    # 日次リターン
    eq = result.equity_curve
    for j in range(1, len(eq)):
        if eq[j - 1] > 0:
            result.daily_returns.append((eq[j] - eq[j - 1]) / eq[j - 1])
        else:
            result.daily_returns.append(0)

    return result


# ============================================================
# 4. 結果分析・表示
# ============================================================

def analyze(result: BacktestResult, label: str = "") -> dict:
    """バックテスト結果の統計を計算・表示"""
    trades = result.trades
    eq = result.equity_curve
    daily_ret = np.array(result.daily_returns)
    cfg = result.config

    if not trades:
        print(f"\n{'='*60}")
        print(f"  {label} — 取引なし")
        print(f"{'='*60}")
        return {}

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trades)
    final_capital = eq[-1]

    # 最大ドローダウン
    peak = eq[0]
    max_dd = 0
    for v in eq:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # シャープレシオ (年率)
    if len(daily_ret) > 0 and np.std(daily_ret) > 0:
        sharpe = np.mean(daily_ret) / np.std(daily_ret) * np.sqrt(252)
    else:
        sharpe = 0

    # プロフィットファクター
    gross_profit = sum(t.pnl for t in wins) if wins else 0
    gross_loss = abs(sum(t.pnl for t in losses)) if losses else 1
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # 平均保有日数
    avg_holding = 0
    for t in trades:
        d1 = datetime.datetime.strptime(t.entry_date, "%Y-%m-%d")
        d2 = datetime.datetime.strptime(t.exit_date, "%Y-%m-%d")
        avg_holding += (d2 - d1).days
    avg_holding /= len(trades)

    # 連勝・連敗
    max_consec_wins = max_consec_losses = 0
    cw = cl = 0
    for t in trades:
        if t.pnl > 0:
            cw += 1
            cl = 0
        else:
            cl += 1
            cw = 0
        max_consec_wins = max(max_consec_wins, cw)
        max_consec_losses = max(max_consec_losses, cl)

    stats = {
        "label": label,
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) * 100,
        "total_pnl_jpy": total_pnl,
        "final_capital": final_capital,
        "return_pct": (final_capital - cfg.initial_capital) / cfg.initial_capital * 100,
        "max_drawdown_pct": max_dd * 100,
        "sharpe_ratio": sharpe,
        "profit_factor": profit_factor,
        "avg_win_jpy": np.mean([t.pnl for t in wins]) if wins else 0,
        "avg_loss_jpy": np.mean([t.pnl for t in losses]) if losses else 0,
        "avg_holding_days": avg_holding,
        "max_consec_wins": max_consec_wins,
        "max_consec_losses": max_consec_losses,
    }

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  期間リターン     : {stats['return_pct']:+.1f}%")
    print(f"  最終資産         : ¥{stats['final_capital']:,.0f} (初期: ¥{cfg.initial_capital:,.0f})")
    print(f"  総損益           : ¥{stats['total_pnl_jpy']:+,.0f}")
    print(f"  取引回数         : {stats['total_trades']}回 (勝{stats['wins']} / 負{stats['losses']})")
    print(f"  勝率             : {stats['win_rate']:.1f}%")
    print(f"  プロフィットファクター : {stats['profit_factor']:.2f}")
    print(f"  シャープレシオ   : {stats['sharpe_ratio']:.2f}")
    print(f"  最大ドローダウン : {stats['max_drawdown_pct']:.1f}%")
    print(f"  平均勝ちトレード : ¥{stats['avg_win_jpy']:+,.0f}")
    print(f"  平均負けトレード : ¥{stats['avg_loss_jpy']:+,.0f}")
    print(f"  平均保有日数     : {stats['avg_holding_days']:.1f}日")
    print(f"  最大連勝         : {stats['max_consec_wins']}回")
    print(f"  最大連敗         : {stats['max_consec_losses']}回")
    print(f"{'='*60}")

    return stats


# ============================================================
# 5. パラメータ感度分析
# ============================================================

def parameter_sweep(df: pd.DataFrame) -> list[dict]:
    """複数パラメータ組み合わせでバックテストを実行"""
    results = []

    configs = [
        # === Phase 1: ベースライン（EMAクロスのみ）===
        ("v1 Base EMA20/50 R2%",
         BacktestConfig(ema_short=20, ema_long=50, risk_per_trade=0.02)),
        ("v1 Fast EMA10/30 R2%",
         BacktestConfig(ema_short=10, ema_long=30, atr_stop_multiplier=2.0, atr_trail_multiplier=1.5, risk_per_trade=0.02)),
        ("v1 EMA10/50 R2%",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.02)),

        # === Phase 2: ロングオンリー（上昇トレンド銘柄に特化）===
        ("v2 LongOnly EMA10/50 R2%",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.02, long_only=True)),
        ("v2 LongOnly EMA10/30 R2%",
         BacktestConfig(ema_short=10, ema_long=30, atr_stop_multiplier=2.0, atr_trail_multiplier=1.5, risk_per_trade=0.02, long_only=True)),
        ("v2 LongOnly EMA20/50 R2%",
         BacktestConfig(ema_short=20, ema_long=50, risk_per_trade=0.02, long_only=True)),

        # === Phase 3: モメンタムフィルター付き ===
        ("v3 Mom40 EMA10/50 R2%",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.02, momentum_period=40)),
        ("v3 Mom20 EMA10/30 R2%",
         BacktestConfig(ema_short=10, ema_long=30, atr_stop_multiplier=2.0, atr_trail_multiplier=1.5, risk_per_trade=0.02, momentum_period=20)),
        ("v3 LO+Mom40 EMA10/50 R2%",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.02, long_only=True, momentum_period=40)),

        # === Phase 4: EMAスロープフィルター ===
        ("v4 Slope EMA10/50 R2%",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.02, use_ema_slope=True)),
        ("v4 LO+Slope EMA10/50 R2%",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.02, long_only=True, use_ema_slope=True)),

        # === Phase 5: 押し目買い再エントリー ===
        ("v5 LO+Reentry EMA10/50 R2%",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.02, long_only=True, use_reentry=True)),
        ("v5 LO+Reentry+Mom EMA10/50 R2%",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.02, long_only=True, use_reentry=True, momentum_period=40)),

        # === Phase 6: リスク増加バリエーション（ベスト戦略に対して）===
        ("v6 LO EMA10/50 R3%",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.03, long_only=True)),
        ("v6 LO EMA10/50 R5%",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.05, long_only=True)),
        ("v6 LO EMA10/50 R5% Lev40x",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.05, long_only=True, max_leverage=40)),
        ("v6 LO+Mom EMA10/50 R5%",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.05, long_only=True, momentum_period=40)),
        ("v6 LO+Slope EMA10/50 R5%",
         BacktestConfig(ema_short=10, ema_long=50, risk_per_trade=0.05, long_only=True, use_ema_slope=True)),
    ]

    for label, cfg in configs:
        res = run_backtest(df, cfg)
        stats = analyze(res, label)
        if stats:
            results.append(stats)

    return results


def print_comparison(all_stats: list[dict]) -> None:
    """全パラメータセットの比較表"""
    print(f"\n{'='*100}")
    print("  パラメータ感度分析 — 比較表")
    print(f"{'='*100}")
    header = f"{'設定':<48} {'リターン':>8} {'DD':>6} {'Sharpe':>7} {'PF':>6} {'勝率':>6} {'取引数':>5}"
    print(header)
    print("-" * 100)

    for s in sorted(all_stats, key=lambda x: x["return_pct"], reverse=True):
        row = (
            f"{s['label']:<48} "
            f"{s['return_pct']:>+7.1f}% "
            f"{s['max_drawdown_pct']:>5.1f}% "
            f"{s['sharpe_ratio']:>7.2f} "
            f"{s['profit_factor']:>6.2f} "
            f"{s['win_rate']:>5.1f}% "
            f"{s['total_trades']:>5}"
        )
        print(row)
    print(f"{'='*100}")


# ============================================================
# 6. メイン
# ============================================================

if __name__ == "__main__":
    print("ゴールド(XAU/USD)のデータを読み込み中...")
    df = load_gold_data()
    print(f"読み込み完了: {len(df)}日分 ({df['date'].iloc[0].date()} 〜 {df['date'].iloc[-1].date()})")
    print(f"価格レンジ: ${df['close'].min():.2f} 〜 ${df['close'].max():.2f}")

    print("\n\nパラメータ感度分析を実行中...")
    all_stats = parameter_sweep(df)

    print_comparison(all_stats)
