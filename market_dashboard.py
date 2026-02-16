#!/usr/bin/env python3
"""
Market Data Dashboard - コンパクトなデスクトップ常時表示アプリ
時刻・為替・プラチナ先物・株価を自動更新で表示
"""

import tkinter as tk
from datetime import datetime
from zoneinfo import ZoneInfo
import threading
import json
import urllib.request
import ssl
import logging

logging.basicConfig(
    filename="market_dashboard.log",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
)

# --- 設定 ---
CLOCK_INTERVAL_MS = 1000
FX_INTERVAL_MS = 1000       # 為替・プラチナ: 1秒
STOCK_INTERVAL_MS = 60000   # 株価: 60秒

TIMEZONES = [
    ("Tokyo", "Asia/Tokyo"),
    ("Los Angeles", "America/Los_Angeles"),
    ("Amsterdam", "Europe/Amsterdam"),
    ("Bangkok", "Asia/Bangkok"),
    ("Manila", "Asia/Manila"),
]

FX_SYMBOLS = {
    "USD/JPY": "USDJPY=X",
    "EUR/JPY": "EURJPY=X",
    "CNY/JPY": "CNYJPY=X",
    "THB/JPY": "THBJPY=X",
}

PLATINUM_SYMBOL = "PL=F"

STOCK_SYMBOLS = {
    "Nikkei 225": "^N225",
    "S&P 500": "^GSPC",
    "Asahi Intecc": "7747.T",
    "Terumo": "4543.T",
    "Sysmex": "6869.T",
    "Olympus": "7733.T",
}

FX_PLATINUM_SYMBOLS_LIST = list(FX_SYMBOLS.values()) + [PLATINUM_SYMBOL]
STOCK_SYMBOLS_LIST = list(STOCK_SYMBOLS.values())

# --- カラーパレット ---
BG = "#0f0f1a"
CARD_BG = "#1a1a2e"
CARD_BORDER = "#2a2a4a"
FG = "#c8c8d4"
FG_DIM = "#6a6a80"
ACCENT = "#64ffda"
HEADER_FG = "#e8e8f0"
UP_COLOR = "#00e676"
DOWN_COLOR = "#ff5555"
NEUTRAL_COLOR = "#8888a0"
TITLE_FG = "#64ffda"
CLOSE_FG = "#ff5555"
CLOSE_HOVER = "#ff8888"

# --- フォント ---
FONT_TITLE = ("Segoe UI", 10, "bold")
FONT_SECTION = ("Segoe UI", 8, "bold")
FONT_LABEL = ("Segoe UI", 8)
FONT_VALUE = ("Consolas", 9)
FONT_VALUE_BOLD = ("Consolas", 9, "bold")
FONT_STATUS = ("Segoe UI", 7)
FONT_CLOSE = ("Segoe UI", 9)


# ============================================================
# データ取得: 3段階フォールバック
# ============================================================

def _fetch_via_yf_download(symbols):
    """方法1: yf.download() で一括取得（最も安定）"""
    import yfinance as yf
    df = yf.download(symbols, period="5d", group_by="ticker", progress=False, threads=True)
    data = {}
    for sym in symbols:
        try:
            if len(symbols) == 1:
                close_series = df["Close"].dropna()
            else:
                close_series = df[sym]["Close"].dropna()
            if len(close_series) >= 1:
                price = float(close_series.iloc[-1])
                prev = float(close_series.iloc[-2]) if len(close_series) >= 2 else None
                data[sym] = (price, prev)
        except Exception as e:
            logging.debug("yf.download parse error for %s: %s", sym, e)
    return data


def _fetch_via_yf_ticker(symbols):
    """方法2: yf.Ticker().history() で個別取得"""
    import yfinance as yf
    data = {}
    for sym in symbols:
        try:
            hist = yf.Ticker(sym).history(period="5d")
            if hist is not None and len(hist) >= 1:
                price = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else None
                data[sym] = (price, prev)
        except Exception as e:
            logging.debug("yf.Ticker history error for %s: %s", sym, e)
    return data


def _fetch_via_http(symbols):
    """方法3: Yahoo Finance v8 API に直接HTTPリクエスト"""
    ctx = ssl.create_default_context()
    data = {}
    for sym in symbols:
        try:
            url = (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
                f"?range=5d&interval=1d"
            )
            req = urllib.request.Request(url, headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            })
            resp = urllib.request.urlopen(req, timeout=10, context=ctx)
            body = json.loads(resp.read())
            result = body["chart"]["result"][0]
            meta = result["meta"]
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            if price is not None:
                data[sym] = (float(price), float(prev) if prev else None)
        except Exception as e:
            logging.debug("HTTP fetch error for %s: %s", sym, e)
    return data


def fetch_all_market_data(symbols, fast=False):
    """マーケットデータを取得。fast=True の場合は軽量な方法を優先"""
    data = {}

    if fast:
        # 高頻度更新用: HTTP直接 → yf.Ticker (軽量な順)
        try:
            data = _fetch_via_http(symbols)
        except Exception as e:
            logging.debug("HTTP fetch failed: %s", e)

        missing = [s for s in symbols if s not in data]
        if missing:
            try:
                extra = _fetch_via_yf_ticker(missing)
                data.update(extra)
            except Exception as e:
                logging.debug("yf.Ticker fallback failed: %s", e)
        return data

    # 通常更新: yf.download() → yf.Ticker → HTTP
    try:
        logging.info("Trying yf.download()...")
        data = _fetch_via_yf_download(symbols)
        logging.info("yf.download() got %d/%d symbols", len(data), len(symbols))
    except Exception as e:
        logging.warning("yf.download() failed: %s", e)

    missing = [s for s in symbols if s not in data]
    if missing:
        try:
            extra = _fetch_via_yf_ticker(missing)
            data.update(extra)
        except Exception as e:
            logging.warning("yf.Ticker() failed: %s", e)

    missing = [s for s in symbols if s not in data]
    if missing:
        try:
            extra = _fetch_via_http(missing)
            data.update(extra)
        except Exception as e:
            logging.warning("HTTP fetch failed: %s", e)

    return data


# ============================================================
# GUI
# ============================================================

class MarketDashboard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Market Dashboard")
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self.root.overrideredirect(True)

        # ドラッグで移動
        self._drag_data = {"x": 0, "y": 0}
        self.root.bind("<Button-1>", self._on_drag_start)
        self.root.bind("<B1-Motion>", self._on_drag_motion)

        # データ格納
        self.clock_labels = {}
        self.fx_labels = {}
        self.platinum_label = None
        self.platinum_change_label = None
        self.stock_labels = {}
        self.status_label = None
        self.prev_fx = {}
        self.prev_stocks = {}
        self.prev_platinum = None
        self._minimized = False

        self._build_ui()
        self._update_clocks()
        self._schedule_fx_update()
        self._schedule_stock_update()

    def _on_drag_start(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _on_drag_motion(self, event):
        dx = event.x - self._drag_data["x"]
        dy = event.y - self._drag_data["y"]
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")

    def _make_card(self, parent, title):
        """セクションカードを生成"""
        outer = tk.Frame(parent, bg=CARD_BORDER, padx=1, pady=1)
        outer.pack(fill="x", padx=6, pady=3)
        card = tk.Frame(outer, bg=CARD_BG, padx=10, pady=6)
        card.pack(fill="x")
        tk.Label(
            card, text=title, font=FONT_SECTION,
            bg=CARD_BG, fg=FG_DIM, anchor="w"
        ).pack(fill="x", pady=(0, 4))
        return card

    def _make_separator(self, parent):
        """薄いセパレータライン"""
        tk.Frame(parent, bg=CARD_BORDER, height=1).pack(fill="x", pady=2)

    def _build_ui(self):
        # 外枠（ボーダー）
        border = tk.Frame(self.root, bg=CARD_BORDER, padx=1, pady=1)
        border.pack(fill="both", expand=True)
        main = tk.Frame(border, bg=BG, padx=0, pady=0)
        main.pack(fill="both", expand=True)

        # タイトルバー
        title_bar = tk.Frame(main, bg=BG, padx=10, pady=6)
        title_bar.pack(fill="x")
        tk.Label(
            title_bar, text="MARKET DASHBOARD",
            font=FONT_TITLE, bg=BG, fg=TITLE_FG, anchor="w"
        ).pack(side="left")

        # 閉じるボタン
        close_btn = tk.Label(
            title_bar, text="\u2715", font=FONT_CLOSE,
            bg=BG, fg=CLOSE_FG, cursor="hand2"
        )
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda e: self.root.destroy())
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg=CLOSE_HOVER))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg=CLOSE_FG))

        # 最小化ボタン
        self._min_btn = tk.Label(
            title_bar, text="\u2013", font=FONT_CLOSE,
            bg=BG, fg=FG_DIM, cursor="hand2"
        )
        self._min_btn.pack(side="right", padx=(0, 6))
        self._min_btn.bind("<Button-1>", lambda e: self._toggle_minimize())
        self._min_btn.bind("<Enter>", lambda e: self._min_btn.config(fg=FG))
        self._min_btn.bind("<Leave>", lambda e: self._min_btn.config(fg=FG_DIM))

        # 区切り線
        self._accent_line = tk.Frame(main, bg=ACCENT, height=1)
        self._accent_line.pack(fill="x", padx=6)

        # コンテンツ部分（最小化時に非表示にするコンテナ）
        self._content_frame = tk.Frame(main, bg=BG)
        self._content_frame.pack(fill="x")

        # ① 時刻
        card = self._make_card(self._content_frame, "WORLD CLOCK")
        for i, (name, tz) in enumerate(TIMEZONES):
            if i > 0:
                self._make_separator(card)
            row = tk.Frame(card, bg=CARD_BG)
            row.pack(fill="x")
            tk.Label(
                row, text=name, font=FONT_LABEL,
                bg=CARD_BG, fg=FG, anchor="w", width=12
            ).pack(side="left")
            lbl = tk.Label(
                row, text="--/-- --:--:--", font=FONT_VALUE,
                bg=CARD_BG, fg=ACCENT, anchor="e"
            )
            lbl.pack(side="right")
            self.clock_labels[tz] = lbl

        # ② 為替
        card = self._make_card(self._content_frame, "FOREX")
        for i, name in enumerate(FX_SYMBOLS):
            if i > 0:
                self._make_separator(card)
            row = tk.Frame(card, bg=CARD_BG)
            row.pack(fill="x")
            tk.Label(
                row, text=name, font=FONT_LABEL,
                bg=CARD_BG, fg=FG, anchor="w", width=8
            ).pack(side="left")
            change_lbl = tk.Label(
                row, text="", font=FONT_STATUS,
                bg=CARD_BG, fg=NEUTRAL_COLOR, anchor="e"
            )
            change_lbl.pack(side="right", padx=(4, 0))
            lbl = tk.Label(
                row, text="----.--", font=FONT_VALUE_BOLD,
                bg=CARD_BG, fg=NEUTRAL_COLOR, anchor="e"
            )
            lbl.pack(side="right")
            self.fx_labels[name] = (lbl, change_lbl)

        # ③ プラチナ先物
        card = self._make_card(self._content_frame, "PLATINUM FUTURES")
        row = tk.Frame(card, bg=CARD_BG)
        row.pack(fill="x")
        tk.Label(
            row, text="PL", font=FONT_LABEL,
            bg=CARD_BG, fg=FG, anchor="w", width=8
        ).pack(side="left")
        self.platinum_change_label = tk.Label(
            row, text="", font=FONT_STATUS,
            bg=CARD_BG, fg=NEUTRAL_COLOR, anchor="e"
        )
        self.platinum_change_label.pack(side="right", padx=(4, 0))
        self.platinum_label = tk.Label(
            row, text="-----.--", font=FONT_VALUE_BOLD,
            bg=CARD_BG, fg=NEUTRAL_COLOR, anchor="e"
        )
        self.platinum_label.pack(side="right")

        # ④ 株価
        card = self._make_card(self._content_frame, "STOCKS")
        for i, name in enumerate(STOCK_SYMBOLS):
            if i > 0:
                self._make_separator(card)
            row = tk.Frame(card, bg=CARD_BG)
            row.pack(fill="x")
            tk.Label(
                row, text=name, font=FONT_LABEL,
                bg=CARD_BG, fg=FG, anchor="w", width=12
            ).pack(side="left")
            change_lbl = tk.Label(
                row, text="", font=FONT_STATUS,
                bg=CARD_BG, fg=NEUTRAL_COLOR, anchor="e"
            )
            change_lbl.pack(side="right", padx=(4, 0))
            lbl = tk.Label(
                row, text="--------", font=FONT_VALUE_BOLD,
                bg=CARD_BG, fg=NEUTRAL_COLOR, anchor="e"
            )
            lbl.pack(side="right")
            self.stock_labels[name] = (lbl, change_lbl)

        # ステータスバー
        tk.Frame(self._content_frame, bg=CARD_BORDER, height=1).pack(
            fill="x", padx=6, pady=(4, 0)
        )
        self.status_label = tk.Label(
            self._content_frame, text="Starting...", font=FONT_STATUS,
            bg=BG, fg=FG_DIM, anchor="e", padx=10, pady=4
        )
        self.status_label.pack(fill="x")

    def _toggle_minimize(self):
        """コンテンツの表示/非表示を切り替え"""
        if self._minimized:
            self._accent_line.pack(fill="x", padx=6)
            self._content_frame.pack(fill="x")
            self._min_btn.config(text="\u2013")  # –
            self._minimized = False
        else:
            self._content_frame.pack_forget()
            self._accent_line.pack_forget()
            self._min_btn.config(text="\u002b")  # +
            self._minimized = True

    def _update_clocks(self):
        for tz_name, tz_str in TIMEZONES:
            now = datetime.now(ZoneInfo(tz_str))
            self.clock_labels[tz_str].config(text=now.strftime("%m/%d %H:%M:%S"))
        self.root.after(CLOCK_INTERVAL_MS, self._update_clocks)

    # --- 為替・プラチナ (毎秒更新) ---
    def _schedule_fx_update(self):
        self._fetch_fx_data()
        self.root.after(FX_INTERVAL_MS, self._schedule_fx_update)

    def _fetch_fx_data(self):
        def worker():
            try:
                data = fetch_all_market_data(FX_PLATINUM_SYMBOLS_LIST, fast=True)
                self.root.after(0, lambda: self._apply_fx_data(data))
            except Exception as e:
                logging.debug("FX fetch error: %s", e)

        threading.Thread(target=worker, daemon=True).start()

    # --- 株価 (60秒更新) ---
    def _schedule_stock_update(self):
        self._fetch_stock_data()
        self.root.after(STOCK_INTERVAL_MS, self._schedule_stock_update)

    def _fetch_stock_data(self):
        def worker():
            try:
                data = fetch_all_market_data(STOCK_SYMBOLS_LIST)
                self.root.after(0, lambda: self._apply_stock_data(data))
            except Exception as e:
                logging.debug("Stock fetch error: %s", e)

        threading.Thread(target=worker, daemon=True).start()

    def _color_for_change(self, current, previous):
        if current is None or previous is None:
            return NEUTRAL_COLOR
        if current > previous:
            return UP_COLOR
        elif current < previous:
            return DOWN_COLOR
        return NEUTRAL_COLOR

    def _change_text(self, current, previous):
        """前日比の変動率テキストを生成"""
        if current is None or previous is None or previous == 0:
            return ""
        pct = (current - previous) / previous * 100
        sign = "+" if pct >= 0 else ""
        return f"{sign}{pct:.2f}%"

    def _apply_fx_data(self, data):
        now = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%H:%M:%S")

        # 為替
        for name, sym in FX_SYMBOLS.items():
            price, prev_close = data.get(sym, (None, None))
            lbl, change_lbl = self.fx_labels[name]
            if price is not None:
                color = self._color_for_change(price, prev_close)
                lbl.config(text=f"{price:.2f}", fg=color)
                change_lbl.config(
                    text=self._change_text(price, prev_close), fg=color
                )
                self.prev_fx[name] = price

        # プラチナ
        price, prev_close = data.get(PLATINUM_SYMBOL, (None, None))
        if price is not None:
            color = self._color_for_change(price, prev_close)
            self.platinum_label.config(text=f"{price:.2f}", fg=color)
            self.platinum_change_label.config(
                text=self._change_text(price, prev_close), fg=color
            )
            self.prev_platinum = price

        self.status_label.config(text=f"FX {now}  |  1s interval")

    def _apply_stock_data(self, data):
        now = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%H:%M:%S")

        for name, sym in STOCK_SYMBOLS.items():
            price, prev_close = data.get(sym, (None, None))
            lbl, change_lbl = self.stock_labels[name]
            if price is not None:
                if price >= 10000:
                    text = f"{price:,.0f}"
                else:
                    text = f"{price:,.2f}"
                color = self._color_for_change(price, prev_close)
                lbl.config(text=text, fg=color)
                change_lbl.config(
                    text=self._change_text(price, prev_close), fg=color
                )
                self.prev_stocks[name] = price

        self.status_label.config(text=f"Stocks {now}  |  60s interval")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = MarketDashboard()
    app.run()
