#!/usr/bin/env python3
"""株価の前日終値・変動率を診断するスクリプト"""
import yfinance as yf

SYMBOLS = {
    "Nikkei 225": "^N225",
    "S&P 500": "^GSPC",
    "Asahi Intecc": "7747.T",
    "Terumo": "4543.T",
    "Sysmex": "6869.T",
    "Olympus": "7733.T",
}

print("=" * 70)
print("診断: auto_adjust=False vs True の比較")
print("=" * 70)

for name, sym in SYMBOLS.items():
    print(f"\n--- {name} ({sym}) ---")

    # auto_adjust=False (生の終値)
    df_raw = yf.download(sym, period="5d", progress=False, auto_adjust=False)
    if not df_raw.empty:
        close_raw = df_raw["Close"].dropna()
        print(f"  [auto_adjust=False] Close列 (生):")
        for date, val in close_raw.items():
            print(f"    {date.strftime('%Y-%m-%d')}: {float(val):.2f}")
        if len(close_raw) >= 2:
            price = float(close_raw.iloc[-1])
            prev = float(close_raw.iloc[-2])
            pct = (price - prev) / prev * 100
            print(f"  → 現在値={price:.2f}, 前日終値={prev:.2f}, 変動率={pct:+.2f}%")

    # auto_adjust=True (調整済み終値)
    df_adj = yf.download(sym, period="5d", progress=False, auto_adjust=True)
    if not df_adj.empty:
        close_adj = df_adj["Close"].dropna()
        print(f"  [auto_adjust=True] Close列 (調整済み):")
        for date, val in close_adj.items():
            print(f"    {date.strftime('%Y-%m-%d')}: {float(val):.2f}")
        if len(close_adj) >= 2:
            price = float(close_adj.iloc[-1])
            prev = float(close_adj.iloc[-2])
            pct = (price - prev) / prev * 100
            print(f"  → 現在値={price:.2f}, 前日終値={prev:.2f}, 変動率={pct:+.2f}%")

    # fast_info での前日終値
    try:
        fi = yf.Ticker(sym).fast_info
        fi_prev = fi.get("regularMarketPreviousClose") or fi.get("previousClose")
        fi_price = fi.get("lastPrice") or fi.get("regularMarketPrice")
        print(f"  [fast_info] lastPrice={fi_price}, previousClose={fi_prev}")
        if fi_price and fi_prev:
            pct = (float(fi_price) - float(fi_prev)) / float(fi_prev) * 100
            print(f"  → 変動率={pct:+.2f}%")
    except Exception as e:
        print(f"  [fast_info] エラー: {e}")

print("\n" + "=" * 70)
print("上記で auto_adjust=False と True の値が異なる場合、")
print("auto_adjust=True の方が配当・分割で調整されています。")
print("ダッシュボードは auto_adjust=False の値を使用します。")
print("=" * 70)
