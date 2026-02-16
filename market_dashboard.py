#!/usr/bin/env python3
"""
Market Data Dashboard - コンパクトなデスクトップ常時表示アプリ
時刻・為替・プラチナ先物・株価を自動更新で表示
"""

import tkinter as tk
from datetime import datetime
from zoneinfo import ZoneInfo
import threading
import yfinance as yf

# --- 設定 ---
CLOCK_INTERVAL_MS = 1000
MARKET_INTERVAL_S = 60

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

        self._build_ui()
        self._update_clocks()
        self._schedule_market_update()

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
        close_btn = tk.Label(
            title_bar, text="\u2715", font=FONT_CLOSE,
            bg=BG, fg=CLOSE_FG, cursor="hand2"
        )
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda e: self.root.destroy())
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg=CLOSE_HOVER))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg=CLOSE_FG))

        # 区切り線
        tk.Frame(main, bg=ACCENT, height=1).pack(fill="x", padx=6)

        # ① 時刻
        card = self._make_card(main, "WORLD CLOCK")
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
        card = self._make_card(main, "FOREX")
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
        card = self._make_card(main, "PLATINUM FUTURES")
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
        card = self._make_card(main, "STOCKS")
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
        tk.Frame(main, bg=CARD_BORDER, height=1).pack(fill="x", padx=6, pady=(4, 0))
        self.status_label = tk.Label(
            main, text="Starting...", font=FONT_STATUS,
            bg=BG, fg=FG_DIM, anchor="e", padx=10, pady=4
        )
        self.status_label.pack(fill="x")

    def _update_clocks(self):
        for tz_name, tz_str in TIMEZONES:
            now = datetime.now(ZoneInfo(tz_str))
            self.clock_labels[tz_str].config(text=now.strftime("%m/%d %H:%M:%S"))
        self.root.after(CLOCK_INTERVAL_MS, self._update_clocks)

    def _schedule_market_update(self):
        self._fetch_market_data()
        self.root.after(MARKET_INTERVAL_S * 1000, self._schedule_market_update)

    def _fetch_market_data(self):
        def worker():
            all_symbols = (
                list(FX_SYMBOLS.values())
                + [PLATINUM_SYMBOL]
                + list(STOCK_SYMBOLS.values())
            )
            try:
                data = {}
                for sym in all_symbols:
                    try:
                        ticker = yf.Ticker(sym)
                        info = ticker.fast_info
                        price = getattr(info, "last_price", None)
                        prev = getattr(info, "previous_close", None)
                        data[sym] = (price, prev)
                    except Exception:
                        data[sym] = (None, None)
                self.root.after(0, lambda: self._apply_market_data(data))
            except Exception as e:
                self.root.after(0, lambda: self.status_label.config(
                    text=f"Error: {str(e)[:30]}"
                ))

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

    def _apply_market_data(self, data):
        now = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%H:%M:%S")

        # 為替
        for name, sym in FX_SYMBOLS.items():
            price, prev_close = data.get(sym, (None, None))
            if price is not None:
                color = self._color_for_change(price, prev_close)
                lbl, change_lbl = self.fx_labels[name]
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

        # 株価
        for name, sym in STOCK_SYMBOLS.items():
            price, prev_close = data.get(sym, (None, None))
            if price is not None:
                if price >= 10000:
                    text = f"{price:,.0f}"
                else:
                    text = f"{price:,.2f}"
                color = self._color_for_change(price, prev_close)
                lbl, change_lbl = self.stock_labels[name]
                lbl.config(text=text, fg=color)
                change_lbl.config(
                    text=self._change_text(price, prev_close), fg=color
                )
                self.prev_stocks[name] = price

        self.status_label.config(text=f"Updated {now}  |  60s interval")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = MarketDashboard()
    app.run()
