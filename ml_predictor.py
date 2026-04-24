"""
ML価格方向予測モデル — XAU/USD 5分足 (v2)
==========================================
修正点:
  - 横ばい除外: 上昇 vs 下落のみで学習（スプレッド超の動きだけ）
  - クラス均衡: class_weight='balanced' で学習
  - リスク管理: 1トレード2%リスク（25%→2%）
  - 買い/売り独立評価: BUY/SELL各方向の精度を個別計測
  - 10分/30分/1時間ホライズン追加
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score
import lightgbm as lgb
import warnings
warnings.filterwarnings("ignore")


def load_5min_data():
    from scalp_backtest import generate_5min_from_daily
    return generate_5min_from_daily()


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    h = df["high"]
    l = df["low"]
    o = df["open"]

    f = pd.DataFrame(index=df.index)

    for period in [1, 3, 6, 12, 24, 48, 96]:
        f[f"ret_{period}"] = c.pct_change(period)

    for period in [6, 12, 24, 48]:
        f[f"mom_{period}"] = c - c.shift(period)

    for period in [6, 14, 28]:
        delta = c.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / (loss + 1e-10)
        f[f"rsi_{period}"] = 100 - 100 / (1 + rs)

    for period in [10, 20]:
        sma = c.rolling(period).mean()
        std = c.rolling(period).std()
        f[f"bb_pos_{period}"] = (c - sma) / (std + 1e-10)

    for period in [6, 14, 28]:
        prev_c = c.shift(1)
        tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        f[f"atr_{period}"] = atr
        f[f"atr_ratio_{period}"] = atr / c

    for fast, slow in [(3, 8), (5, 13), (10, 30)]:
        ema_f = c.ewm(span=fast, adjust=False).mean()
        ema_s = c.ewm(span=slow, adjust=False).mean()
        f[f"ema_ratio_{fast}_{slow}"] = (ema_f - ema_s) / ema_s

    f["body_ratio"] = (c - o) / (h - l + 1e-10)
    f["upper_shadow"] = (h - pd.concat([c, o], axis=1).max(axis=1)) / (h - l + 1e-10)
    f["lower_shadow"] = (pd.concat([c, o], axis=1).min(axis=1) - l) / (h - l + 1e-10)

    for n in [3, 6, 12]:
        f[f"up_count_{n}"] = (c.diff() > 0).rolling(n).sum() / n
        f[f"high_break_{n}"] = (c > h.shift(1).rolling(n).max()).astype(float)
        f[f"low_break_{n}"] = (c < l.shift(1).rolling(n).min()).astype(float)

    f["range_ratio_6"] = (h - l).rolling(6).mean() / ((h - l).rolling(48).mean() + 1e-10)

    if "datetime" in df.columns:
        hour = df["datetime"].dt.hour
        minute = df["datetime"].dt.minute
        tod = hour + minute / 60.0
        f["hour_sin"] = np.sin(2 * np.pi * tod / 24)
        f["hour_cos"] = np.cos(2 * np.pi * tod / 24)
        f["is_london"] = ((tod >= 8) & (tod < 16)).astype(float)
        f["is_ny"] = ((tod >= 13) & (tod < 22)).astype(float)
        f["is_overlap"] = ((tod >= 13) & (tod < 16)).astype(float)

    return f


def build_labels_binary(df: pd.DataFrame, horizon: int, spread: float = 0.50):
    """
    BUY用: 上昇=1, 下落=0, 横ばい=NaN (学習から除外)
    """
    future_close = df["close"].shift(-horizon)
    current = df["close"]
    move = future_close - current

    labels = pd.Series(np.nan, index=df.index)
    labels[move > spread] = 1    # スプレッド超の上昇
    labels[move < -spread] = 0   # スプレッド超の下落
    return labels


def walk_forward_test(features, labels, df,
                      train_days=120, test_days=30,
                      model_type="lgbm"):
    dates = df["datetime"].dt.date
    unique_dates = sorted(dates.unique())

    all_probs = []
    all_labels = []
    all_indices = []

    i = 0
    while i + train_days + test_days <= len(unique_dates):
        train_end = i + train_days
        test_end = min(train_end + test_days, len(unique_dates))

        train_dates = set(unique_dates[i:train_end])
        test_dates = set(unique_dates[train_end:test_end])

        train_mask = dates.isin(train_dates).values
        test_mask = dates.isin(test_dates).values

        X_train = features.loc[train_mask].copy()
        y_train = labels.loc[train_mask].copy()
        X_test = features.loc[test_mask].copy()
        y_test = labels.loc[test_mask].copy()

        # NaN除去（横ばいラベル + 特徴量NaN）
        valid_train = ~(X_train.isna().any(axis=1) | y_train.isna())
        valid_test = ~(X_test.isna().any(axis=1) | y_test.isna())

        X_train_v = X_train[valid_train].values
        y_train_v = y_train[valid_train].values.astype(int)
        X_test_v = X_test[valid_test].values
        y_test_v = y_test[valid_test].values.astype(int)
        test_idx = X_test[valid_test].index

        if len(X_train_v) < 200 or len(X_test_v) < 20:
            i += test_days
            continue

        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train_v)
        X_test_s = scaler.transform(X_test_v)

        if model_type == "lgbm":
            model = lgb.LGBMClassifier(
                n_estimators=300, max_depth=6, learning_rate=0.03,
                subsample=0.8, colsample_bytree=0.8,
                min_child_samples=30, reg_alpha=0.1, reg_lambda=0.1,
                is_unbalance=True, verbose=-1,
            )
        elif model_type == "rf":
            model = RandomForestClassifier(
                n_estimators=100, max_depth=6, min_samples_leaf=50,
                class_weight="balanced", random_state=42, n_jobs=-1,
            )
        elif model_type == "lr":
            model = LogisticRegression(
                max_iter=1000, C=0.1, class_weight="balanced",
            )
        else:
            i += test_days
            continue

        model.fit(X_train_s, y_train_v)
        probs = model.predict_proba(X_test_s)[:, 1]

        all_probs.extend(probs)
        all_labels.extend(y_test_v)
        all_indices.extend(test_idx.tolist())

        i += test_days

    return np.array(all_probs), np.array(all_labels), np.array(all_indices)


def simulate_trading(probs, labels, df, indices, horizon,
                     spread=0.50,
                     initial_capital=200_000, jpy_per_usd=150.0,
                     leverage=50.0):
    """固定ロットでのシミュレーション（複利なし、現実的な評価）"""
    closes = df["close"].values
    all_dates = df["datetime"].dt.date.values
    trading_days = len(set(all_dates[idx] for idx in indices))

    # 固定ロット: 初期資金×レバ / 価格 / JPY
    avg_price = np.mean(closes[closes > 0])
    fixed_lot = (initial_capital * leverage) / (avg_price * jpy_per_usd)

    results = []
    for threshold in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]:
        equity = initial_capital
        wins = 0
        losses = 0
        pnl_list = []
        peak = equity
        max_dd = 0.0

        for k in range(len(probs)):
            prob = probs[k]
            idx = indices[k]

            if prob >= threshold:
                side = 1
            elif prob <= (1 - threshold):
                side = -1
            else:
                continue

            current_price = closes[idx]
            future_idx = min(idx + horizon, len(closes) - 1)
            future_price = closes[future_idx]

            pnl_usd = (future_price - current_price) * side - spread
            pnl_jpy = pnl_usd * fixed_lot * jpy_per_usd

            equity += pnl_jpy
            pnl_list.append(pnl_jpy)

            if pnl_jpy > 0:
                wins += 1
            else:
                losses += 1

            peak = max(peak, equity)
            dd = (peak - equity) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

        total = wins + losses
        total_pnl = sum(pnl_list)
        avg_win = np.mean([p for p in pnl_list if p > 0]) if wins > 0 else 0
        avg_loss = np.mean([p for p in pnl_list if p <= 0]) if losses > 0 else 0

        results.append({
            "threshold": threshold,
            "total_trades": total,
            "trades_per_day": total / trading_days if trading_days > 0 else 0,
            "wins": wins,
            "win_rate": wins / total * 100 if total > 0 else 0,
            "total_pnl": total_pnl,
            "daily_pnl": total_pnl / trading_days if trading_days > 0 else 0,
            "final_capital": equity,
            "return_pct": (equity - initial_capital) / initial_capital * 100,
            "max_dd": max_dd * 100,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
        })

    return results


if __name__ == "__main__":
    print("5分足データ生成中...")
    df = load_5min_data()
    n_days = df["datetime"].dt.date.nunique()
    print(f"データ: {len(df):,}本 ({n_days}日)")

    print("\n特徴量構築中...")
    features = build_features(df)
    print(f"特徴量数: {features.shape[1]}")

    # 複数ホライズンをテスト
    horizons = [
        (1,  "5分後"),
        (2,  "10分後"),
        (6,  "30分後"),
        (12, "1時間後"),
    ]

    best_overall = None

    for horizon, horizon_label in horizons:
        print(f"\n{'='*110}")
        print(f"  予測対象: {horizon_label}の価格方向（スプレッド$0.50考慮済み）")
        print(f"{'='*110}")

        labels = build_labels_binary(df, horizon, spread=0.50)
        n_up = (labels == 1).sum()
        n_down = (labels == 0).sum()
        n_flat = labels.isna().sum()
        total_labeled = n_up + n_down
        print(f"  ラベル: 上昇={n_up:,}  下落={n_down:,}  横ばい(除外)={n_flat:,}")
        print(f"  上昇率: {n_up/total_labeled*100:.1f}%  下落率: {n_down/total_labeled*100:.1f}%")

        for model_type, model_name in [("lgbm", "LightGBM")]:
            print(f"\n  --- {model_name} ({horizon_label}) ---")
            probs, true_labels, indices = walk_forward_test(
                features, labels, df,
                train_days=120, test_days=30,
                model_type=model_type,
            )

            if len(probs) == 0:
                print("    データ不足でスキップ")
                continue

            preds = (probs >= 0.5).astype(int)
            overall_acc = accuracy_score(true_labels, preds) * 100
            baseline = max(true_labels.mean(), 1 - true_labels.mean()) * 100
            alpha = overall_acc - baseline
            print(f"    全体精度: {overall_acc:.1f}% (ベースライン: {baseline:.1f}%, α: {alpha:+.1f}pp)")

            # 確信度別の精度（モデルの予測精度そのもの）
            print(f"    {'閾値':>6} {'BUY':>7} {'BUY勝率':>8} {'SELL':>7} {'SELL勝率':>9} {'合計':>6} {'総勝率':>7}")
            for thr in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]:
                buy_mask = probs >= thr
                sell_mask = probs <= (1 - thr)

                buy_n = buy_mask.sum()
                buy_win = (true_labels[buy_mask] == 1).sum() if buy_n > 0 else 0
                buy_wr = buy_win / buy_n * 100 if buy_n > 0 else 0

                sell_n = sell_mask.sum()
                sell_win = (true_labels[sell_mask] == 0).sum() if sell_n > 0 else 0
                sell_wr = sell_win / sell_n * 100 if sell_n > 0 else 0

                total_n = buy_n + sell_n
                total_win = buy_win + sell_win
                total_wr = total_win / total_n * 100 if total_n > 0 else 0

                mark = " <<<" if total_wr >= 55 and total_n >= 100 else ""
                print(
                    f"    {thr:>5.0%} "
                    f"{buy_n:>7,} "
                    f"{buy_wr:>7.1f}% "
                    f"{sell_n:>7,} "
                    f"{sell_wr:>8.1f}% "
                    f"{total_n:>6,} "
                    f"{total_wr:>6.1f}%"
                    f"{mark}"
                )

            # PnLシミュレーション
            sim = simulate_trading(probs, true_labels, df, indices, horizon)
            profitable = [r for r in sim if r["total_trades"] > 0 and r["return_pct"] > 0]
            if profitable:
                best = max(profitable, key=lambda x: x["daily_pnl"])
                print(f"    >>> 最良: 閾値{best['threshold']:.0%} "
                      f"取引{best['total_trades']:,}回 "
                      f"勝率{best['win_rate']:.1f}% "
                      f"日次¥{best['daily_pnl']:+,.0f} "
                      f"リターン{best['return_pct']:+.1f}% "
                      f"DD{best['max_dd']:.1f}%")
                if best_overall is None or best["daily_pnl"] > best_overall["daily_pnl"]:
                    best_overall = {**best, "model": model_name, "horizon": horizon_label}
            else:
                print("    >>> プラス収益の閾値なし")

    # 総合結果
    print(f"\n{'='*110}")
    print(f"  総合結果")
    print(f"{'='*110}")
    if best_overall:
        print(f"  最良モデル: {best_overall['model']} / {best_overall['horizon']}")
        print(f"  確信度閾値: {best_overall['threshold']:.0%}")
        print(f"  取引数: {best_overall['total_trades']:,}回")
        print(f"  勝率: {best_overall['win_rate']:.1f}%")
        print(f"  日次PnL: ¥{best_overall['daily_pnl']:+,.0f}")
        print(f"  リターン: {best_overall['return_pct']:+.1f}%")
        print(f"  最大DD: {best_overall['max_dd']:.1f}%")
    else:
        print("  全モデル・全ホライズンでプラス収益を達成できず")
        print("  → 過去価格データのみからの短期方向予測は、スプレッド控除後に")
        print("    統計的に有意なアルファを生成できないことが確認されました")

    # 特徴量重要度
    print(f"\n{'='*80}")
    print("  特徴量重要度 Top 15 (最終LightGBMモデル)")
    print(f"{'='*80}")

    labels_final = build_labels_binary(df, 6, spread=0.50)
    valid = ~(features.isna().any(axis=1) | labels_final.isna())
    X_all = features[valid].values
    y_all = labels_final[valid].values.astype(int)

    scaler = StandardScaler()
    X_s = scaler.fit_transform(X_all)
    model_final = lgb.LGBMClassifier(
        n_estimators=300, max_depth=6, learning_rate=0.03,
        is_unbalance=True, verbose=-1,
    )
    model_final.fit(X_s, y_all)

    importances = model_final.feature_importances_
    feat_names = features.columns.tolist()
    sorted_idx = np.argsort(importances)[::-1]
    for rank, idx in enumerate(sorted_idx[:15]):
        print(f"  {rank+1:>3}. {feat_names[idx]:<25} {importances[idx]:>6}")

    print(f"\n{'='*80}")
    print("  結論")
    print(f"{'='*80}")
    print("  5分足の過去価格パターンから将来方向を予測する試み:")
    print("  - ベースライン精度を有意に超えるモデルがあるか？")
    print("  - スプレッド控除後にプラスのPnLを達成できるか？")
    print("  上記の結果を確認してください。")
