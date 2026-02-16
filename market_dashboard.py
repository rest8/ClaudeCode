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
# 時刻更新: 1秒, マーケットデータ更新: 60秒
CLOCK_INTERVAL_MS = 1000
MARKET_INTERVAL_S = 60

TIMEZONES = [
    ("東京", "Asia/Tokyo"),
    ("LA", "America/Los_Angeles"),
    ("Amsterdam", "Europe/Amsterdam"),
    ("Bangkok", "Asia/Bangkok"),
    ("Manila", "Asia/Manila"),
]

FX_SYMBOLS = {
    "USDJPY": "USDJPY=X",
    "EURJPY": "EURJPY=X",
    "CNYJPY": "CNYJPY=X",
    "THBJPY": "THBJPY=X",
}

PLATINUM_SYMBOL = "PL=F"

STOCK_SYMBOLS = {
    "日経平均": "^N225",
    "S&P500": "^GSPC",
    "朝日インテック": "7747.T",
    "テルモ": "4543.T",
    "Sysmex": "6869.T",
    "オリンパス": "7733.T",
}

# --- 色 ---
BG = "#1a1a2e"
FG = "#e0e0e0"
ACCENT = "#00d4aa"
SECTION_BG = "#16213e"
HEADER_FG = "#ff9f1c"
UP_COLOR = "#00e676"
DOWN_COLOR = "#ff5252"
NEUTRAL_COLOR = "#e0e0e0"


class MarketDashboard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Market Dashboard")
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)

        # ドラッグで移動
        self._drag_data = {"x": 0, "y": 0}
        self.root.bind("<Button-1>", self._on_drag_start)
        self.root.bind("<B1-Motion>", self._on_drag_motion)

        # データ格納
        self.clock_labels = {}
        self.fx_labels = {}
        self.platinum_label = None
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

    def _make_section(self, parent, title):
        frame = tk.Frame(parent, bg=SECTION_BG, padx=4, pady=2)
        frame.pack(fill="x", padx=2, pady=1)
        tk.Label(
            frame, text=title, font=("Consolas", 8, "bold"),
            bg=SECTION_BG, fg=HEADER_FG, anchor="w"
        ).pack(fill="x")
        return frame

    def _build_ui(self):
        main = tk.Frame(self.root, bg=BG, padx=3, pady=3)
        main.pack()

        # タイトルバー (閉じるボタン付き)
        title_frame = tk.Frame(main, bg=BG)
        title_frame.pack(fill="x")
        tk.Label(
            title_frame, text="📊 Market Dashboard", font=("Consolas", 8, "bold"),
            bg=BG, fg=ACCENT, anchor="w"
        ).pack(side="left")
        tk.Button(
            title_frame, text="✕", font=("Consolas", 7), bg=BG, fg="#ff5252",
            bd=0, activebackground="#ff5252", activeforeground="white",
            command=self.root.destroy, cursor="hand2"
        ).pack(side="right")

        # ① 時刻
        sec = self._make_section(main, "⏰ 時刻")
        for name, tz in TIMEZONES:
            row = tk.Frame(sec, bg=SECTION_BG)
            row.pack(fill="x")
            tk.Label(
                row, text=f"{name:>10}", font=("Consolas", 8),
                bg=SECTION_BG, fg=FG, width=10, anchor="e"
            ).pack(side="left")
            lbl = tk.Label(
                row, text="--:--:--", font=("Consolas", 8, "bold"),
                bg=SECTION_BG, fg=ACCENT, anchor="w"
            )
            lbl.pack(side="left", padx=(4, 0))
            self.clock_labels[tz] = lbl

        # ② 為替
        sec = self._make_section(main, "💱 為替")
        for name in FX_SYMBOLS:
            row = tk.Frame(sec, bg=SECTION_BG)
            row.pack(fill="x")
            tk.Label(
                row, text=f"{name:>7}", font=("Consolas", 8),
                bg=SECTION_BG, fg=FG, width=7, anchor="e"
            ).pack(side="left")
            lbl = tk.Label(
                row, text="----.--", font=("Consolas", 8, "bold"),
                bg=SECTION_BG, fg=NEUTRAL_COLOR, anchor="e", width=10
            )
            lbl.pack(side="left", padx=(4, 0))
            self.fx_labels[name] = lbl

        # ③ プラチナ先物
        sec = self._make_section(main, "🪙 プラチナ先物")
        row = tk.Frame(sec, bg=SECTION_BG)
        row.pack(fill="x")
        tk.Label(
            row, text="  PL", font=("Consolas", 8),
            bg=SECTION_BG, fg=FG, width=7, anchor="e"
        ).pack(side="left")
        self.platinum_label = tk.Label(
            row, text="-----.--", font=("Consolas", 8, "bold"),
            bg=SECTION_BG, fg=NEUTRAL_COLOR, anchor="e", width=10
        )
        self.platinum_label.pack(side="left", padx=(4, 0))

        # ④ 株価
        sec = self._make_section(main, "📈 株価")
        for name in STOCK_SYMBOLS:
            row = tk.Frame(sec, bg=SECTION_BG)
            row.pack(fill="x")
            display = name if len(name) <= 7 else name[:6] + "…"
            tk.Label(
                row, text=f"{display:>7}", font=("Consolas", 8),
                bg=SECTION_BG, fg=FG, width=7, anchor="e"
            ).pack(side="left")
            lbl = tk.Label(
                row, text="--------", font=("Consolas", 8, "bold"),
                bg=SECTION_BG, fg=NEUTRAL_COLOR, anchor="e", width=12
            )
            lbl.pack(side="left", padx=(4, 0))
            self.stock_labels[name] = lbl

        # ステータス
        self.status_label = tk.Label(
            main, text="起動中...", font=("Consolas", 7),
            bg=BG, fg="#666", anchor="e"
        )
        self.status_label.pack(fill="x", pady=(2, 0))

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
                    text=f"取得エラー: {str(e)[:30]}"
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

    def _apply_market_data(self, data):
        now = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%H:%M:%S")

        # 為替
        for name, sym in FX_SYMBOLS.items():
            price, prev_close = data.get(sym, (None, None))
            if price is not None:
                color = self._color_for_change(price, prev_close)
                self.fx_labels[name].config(text=f"{price:.2f}", fg=color)
                self.prev_fx[name] = price

        # プラチナ
        price, prev_close = data.get(PLATINUM_SYMBOL, (None, None))
        if price is not None:
            color = self._color_for_change(price, prev_close)
            self.platinum_label.config(text=f"{price:.2f}", fg=color)
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
                self.stock_labels[name].config(text=text, fg=color)
                self.prev_stocks[name] = price

        self.status_label.config(text=f"更新: {now} (60s間隔)")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = MarketDashboard()
    app.run()
