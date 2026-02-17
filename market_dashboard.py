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
WARN_COLOR = "#ffab40"

# iOS Timer 用カラー
IOS_BG = "#000000"
IOS_CARD = "#1c1c1e"
IOS_RING_BG = "#2c2c2e"
IOS_RING_FG = "#ff9f0a"       # オレンジ (iOS Timer風)
IOS_RING_WORK = "#30d158"     # グリーン (作業中)
IOS_RING_BREAK = "#ff9f0a"    # オレンジ (休憩中)
IOS_GREEN_BTN = "#30d158"
IOS_GREEN_BTN_BG = "#0a3a1a"
IOS_RED_BTN = "#ff453a"
IOS_RED_BTN_BG = "#3a1a1a"
IOS_GRAY_BTN = "#8e8e93"
IOS_GRAY_BTN_BG = "#2c2c2e"
IOS_TEXT = "#ffffff"
IOS_TEXT_DIM = "#8e8e93"
IOS_PICKER_BG = "#1c1c1e"
IOS_PICKER_SEL = "#2c2c2e"

# --- フォント ---
FONT_TITLE = ("Segoe UI", 10, "bold")
FONT_SECTION = ("Segoe UI", 8, "bold")
FONT_LABEL = ("Segoe UI", 8)
FONT_VALUE = ("Consolas", 9)
FONT_VALUE_BOLD = ("Consolas", 9, "bold")
FONT_STATUS = ("Segoe UI", 7)
FONT_CLOSE = ("Segoe UI", 9)
FONT_TIMER_DISPLAY = ("Consolas", 18, "bold")
FONT_TIMER_LARGE = ("Consolas", 28, "bold")
FONT_TIMER_BTN = ("Segoe UI", 8)
FONT_TIMER_BTN_LG = ("Segoe UI", 9, "bold")
FONT_PICKER = ("Consolas", 13)
FONT_PICKER_DIM = ("Consolas", 11)
FONT_PICKER_LABEL = ("Segoe UI", 8)
FONT_ICON = ("Segoe UI", 9)


# ============================================================
# データ取得: 3段階フォールバック
# ============================================================

def _fetch_via_yf_download(symbols):
    """方法1: yf.download() で現在値を一括取得 (auto_adjust=False で生の終値を使用)"""
    import yfinance as yf
    df = yf.download(symbols, period="5d", group_by="ticker", progress=False,
                     threads=True, auto_adjust=False)
    data = {}
    for sym in symbols:
        try:
            if len(symbols) == 1:
                close_series = df["Close"].dropna()
            else:
                close_series = df[sym]["Close"].dropna()
            if len(close_series) >= 2:
                price = float(close_series.iloc[-1])
                prev = float(close_series.iloc[-2])
                data[sym] = (price, prev)
            elif len(close_series) == 1:
                price = float(close_series.iloc[-1])
                data[sym] = (price, None)
        except Exception as e:
            logging.debug("yf.download parse error for %s: %s", sym, e)
    return data


def _fetch_via_yf_ticker(symbols):
    """方法2: yf.Ticker().fast_info で個別取得"""
    import yfinance as yf
    data = {}
    for sym in symbols:
        try:
            info = yf.Ticker(sym).fast_info
            price = float(info["lastPrice"])
            prev = None
            try:
                prev = float(info["regularMarketPreviousClose"])
            except Exception:
                try:
                    prev = float(info["previousClose"])
                except Exception:
                    pass
            data[sym] = (price, prev)
        except Exception as e:
            logging.debug("yf.Ticker fast_info error for %s: %s", sym, e)
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

    # 通常更新: HTTP → yf.Ticker → yf.download()
    # HTTP の chartPreviousClose が最も正確な前日終値を返すため最優先
    try:
        logging.info("Trying HTTP fetch...")
        data = _fetch_via_http(symbols)
        logging.info("HTTP fetch got %d/%d symbols", len(data), len(symbols))
    except Exception as e:
        logging.warning("HTTP fetch failed: %s", e)

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
            extra = _fetch_via_yf_download(missing)
            data.update(extra)
        except Exception as e:
            logging.warning("yf.download() failed: %s", e)

    return data


# ============================================================
# Pomodoro Timer / Schedule Alert Popup
# ============================================================

# ポモドーロ設定
POMO_WORK_MIN = 25
POMO_BREAK_MIN = 5
POMO_LONG_BREAK_MIN = 15
POMO_LONG_BREAK_AFTER = 4   # 4セット後にロングブレイク

# 透過ウィンドウ用の色キー (Linux)
TRANSPARENT_COLOR = "#f0f0f0"

# スケジュール通知タイミング (秒)
SCHEDULE_NOTIFY_BEFORE = [600, 300, 120, 30]  # 10m, 5m, 2m, 30s
SCHEDULE_NOTIFY_LABELS = {600: "10 min", 300: "5 min", 120: "2 min", 30: "30 sec"}


class iOSWheelPicker(tk.Frame):
    """iOS風ホイールピッカー (上下ボタン + 数値表示)"""

    def __init__(self, parent, values, initial=0, label="", on_change=None, **kwargs):
        super().__init__(parent, bg=IOS_BG, **kwargs)
        self._values = values
        self._selected = min(initial, len(values) - 1)
        self._label = label
        self._on_change = on_change

        # 上矢印
        up_btn = tk.Label(
            self, text="\u25b2", font=("Segoe UI", 10),
            bg=IOS_BG, fg=IOS_TEXT_DIM, cursor="hand2"
        )
        up_btn.pack(pady=(0, 2))
        up_btn.bind("<Button-1>", lambda e: self._step(-1))
        up_btn.bind("<Enter>", lambda e: up_btn.config(fg=IOS_TEXT))
        up_btn.bind("<Leave>", lambda e: up_btn.config(fg=IOS_TEXT_DIM))

        # 数値表示エリア (選択ハイライト帯)
        sel_frame = tk.Frame(self, bg=IOS_PICKER_SEL, padx=8, pady=4)
        sel_frame.pack(fill="x")

        # 前の値 (薄く)
        self._prev_label = tk.Label(
            sel_frame, text="", font=FONT_PICKER_DIM,
            bg=IOS_PICKER_SEL, fg=IOS_TEXT_DIM
        )
        self._prev_label.pack()

        # セパレータ上
        tk.Frame(sel_frame, bg=IOS_GRAY_BTN, height=1).pack(fill="x", pady=1)

        # 選択中の値 + ラベル
        center = tk.Frame(sel_frame, bg=IOS_PICKER_SEL)
        center.pack(pady=2)
        self._value_label = tk.Label(
            center, text="", font=FONT_PICKER,
            bg=IOS_PICKER_SEL, fg=IOS_TEXT, width=3
        )
        self._value_label.pack(side="left")
        if label:
            tk.Label(
                center, text=label, font=FONT_PICKER_LABEL,
                bg=IOS_PICKER_SEL, fg=IOS_TEXT_DIM
            ).pack(side="left", padx=(2, 0))

        # セパレータ下
        tk.Frame(sel_frame, bg=IOS_GRAY_BTN, height=1).pack(fill="x", pady=1)

        # 次の値 (薄く)
        self._next_label = tk.Label(
            sel_frame, text="", font=FONT_PICKER_DIM,
            bg=IOS_PICKER_SEL, fg=IOS_TEXT_DIM
        )
        self._next_label.pack()

        # 下矢印
        down_btn = tk.Label(
            self, text="\u25bc", font=("Segoe UI", 10),
            bg=IOS_BG, fg=IOS_TEXT_DIM, cursor="hand2"
        )
        down_btn.pack(pady=(2, 0))
        down_btn.bind("<Button-1>", lambda e: self._step(1))
        down_btn.bind("<Enter>", lambda e: down_btn.config(fg=IOS_TEXT))
        down_btn.bind("<Leave>", lambda e: down_btn.config(fg=IOS_TEXT_DIM))

        # マウスホイール
        for widget in [self, sel_frame, self._value_label,
                       self._prev_label, self._next_label, center]:
            widget.bind("<MouseWheel>", self._on_mousewheel)
            widget.bind("<Button-4>", lambda e: self._step(-1))
            widget.bind("<Button-5>", lambda e: self._step(1))

        self._update_display()

    @property
    def value(self):
        return self._values[self._selected]

    def set_index(self, idx):
        self._selected = max(0, min(idx, len(self._values) - 1))
        self._update_display()

    def _step(self, direction):
        new_idx = self._selected + direction
        if 0 <= new_idx < len(self._values):
            self._selected = new_idx
            self._update_display()
            if self._on_change:
                self._on_change(self._values[self._selected])

    def _on_mousewheel(self, event):
        direction = -1 if event.delta > 0 else 1
        self._step(direction)

    def _update_display(self):
        self._value_label.config(text=str(self._values[self._selected]))
        # 前後の値
        if self._selected > 0:
            self._prev_label.config(text=str(self._values[self._selected - 1]))
        else:
            self._prev_label.config(text="")
        if self._selected < len(self._values) - 1:
            self._next_label.config(text=str(self._values[self._selected + 1]))
        else:
            self._next_label.config(text="")


class TimerAlertPopup:
    """iOS風タイマー＆スケジュールアラートのポップアップ"""

    # 円形プログレスリングのサイズ
    RING_SIZE = 200
    RING_WIDTH = 12

    def __init__(self, parent, dashboard):
        self.dashboard = dashboard
        self.win = tk.Toplevel(parent)
        self.win.title("Timer & Alerts")
        self.win.attributes("-topmost", True)
        self.win.overrideredirect(True)
        self.win.resizable(False, False)

        # 背景を完全透明に
        self.win.configure(bg=TRANSPARENT_COLOR)
        try:
            self.win.attributes("-transparentcolor", TRANSPARENT_COLOR)
        except tk.TclError:
            try:
                self.win.wait_visibility(self.win)
                self.win.attributes("-alpha", 0.95)
            except tk.TclError:
                pass

        # 親ウィンドウの近くに配置
        px = parent.winfo_x() + parent.winfo_width() + 4
        py = parent.winfo_y()
        self.win.geometry(f"+{px}+{py}")

        # ドラッグ
        self._drag_data = {"x": 0, "y": 0}
        self.win.bind("<Button-1>", self._on_drag_start)
        self.win.bind("<B1-Motion>", self._on_drag_motion)

        # タイマー状態
        self._total_seconds = POMO_WORK_MIN * 60  # 設定された合計秒数
        self._remaining = self._total_seconds
        self._running = False
        self._pomo_phase = "work"
        self._pomo_count = 0
        self._after_id = None
        self._state = "picker"  # "picker" (時間選択) or "timer" (カウントダウン)

        # ピッカーの現在値
        self._picker_min = POMO_WORK_MIN
        self._picker_sec = 0

        # スケジュールアラート
        self._schedules = []

        self._build_ui()
        self._tick_schedule_check()

    def _on_drag_start(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _on_drag_motion(self, event):
        dx = event.x - self._drag_data["x"]
        dy = event.y - self._drag_data["y"]
        x = self.win.winfo_x() + dx
        y = self.win.winfo_y() + dy
        self.win.geometry(f"+{x}+{y}")

    def _build_ui(self):
        main = tk.Frame(self.win, bg=TRANSPARENT_COLOR)
        main.pack(fill="both", expand=True)

        # ヘッダー
        hdr_outer = tk.Frame(main, bg=CARD_BORDER, padx=1, pady=1)
        hdr_outer.pack(fill="x", pady=(0, 0))
        hdr = tk.Frame(hdr_outer, bg=IOS_BG, padx=10, pady=6)
        hdr.pack(fill="x")
        tk.Label(hdr, text="TIMER", font=FONT_SECTION,
                 bg=IOS_BG, fg=IOS_TEXT).pack(side="left")

        # フェーズ・セッション表示
        self._phase_label = tk.Label(
            hdr, text="", font=FONT_STATUS,
            bg=IOS_BG, fg=IOS_GREEN_BTN
        )
        self._phase_label.pack(side="left", padx=(8, 0))

        close_btn = tk.Label(hdr, text="\u2715", font=FONT_STATUS,
                             bg=IOS_BG, fg=IOS_RED_BTN, cursor="hand2")
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda e: self.close())
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg=CLOSE_HOVER))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg=IOS_RED_BTN))

        # メインカード
        card_outer = tk.Frame(main, bg=CARD_BORDER, padx=1, pady=1)
        card_outer.pack(fill="x", pady=0)
        self._card = tk.Frame(card_outer, bg=IOS_BG, padx=12, pady=10)
        self._card.pack(fill="x")

        # コンテナ: ピッカー or タイマーリング (切り替え用)
        self._display_frame = tk.Frame(self._card, bg=IOS_BG)
        self._display_frame.pack(fill="x")

        # ボタンフレーム
        self._btn_frame = tk.Frame(self._card, bg=IOS_BG)
        self._btn_frame.pack(fill="x", pady=(10, 4))

        # 初期表示: ピッカー
        self._show_picker()

        # スケジュールセクション
        self._build_schedule_section(main)

    # ============================
    # iOS風ピッカー表示
    # ============================
    def _show_picker(self):
        self._state = "picker"
        for w in self._display_frame.winfo_children():
            w.destroy()
        for w in self._btn_frame.winfo_children():
            w.destroy()

        # ピッカーコンテナ
        picker_frame = tk.Frame(self._display_frame, bg=IOS_BG)
        picker_frame.pack(pady=(6, 0))

        # 分ピッカー
        min_values = list(range(0, 100))
        self._min_picker = iOSWheelPicker(
            picker_frame, min_values, initial=self._picker_min,
            label="min", on_change=self._on_min_change
        )
        self._min_picker.pack(side="left", padx=(10, 4))

        # コロン
        tk.Label(picker_frame, text=":", font=FONT_TIMER_LARGE,
                 bg=IOS_BG, fg=IOS_TEXT).pack(side="left", padx=4)

        # 秒ピッカー
        sec_values = list(range(0, 60))
        self._sec_picker = iOSWheelPicker(
            picker_frame, sec_values, initial=self._picker_sec,
            label="sec", on_change=self._on_sec_change
        )
        self._sec_picker.pack(side="left", padx=(4, 10))

        # プリセットボタン
        preset_frame = tk.Frame(self._display_frame, bg=IOS_BG)
        preset_frame.pack(fill="x", pady=(8, 0))

        presets = [("5m", 5, 0), ("15m", 15, 0), ("25m", 25, 0),
                   ("45m", 45, 0), ("60m", 60, 0), ("90m", 90, 0)]
        for label, m, s in presets:
            btn = tk.Label(
                preset_frame, text=label, font=FONT_STATUS,
                bg=IOS_GRAY_BTN_BG, fg=IOS_RING_FG,
                padx=8, pady=3, cursor="hand2"
            )
            btn.pack(side="left", padx=2)
            btn.bind("<Button-1>", lambda e, mm=m, ss=s: self._set_preset(mm, ss))
            btn.bind("<Enter>", lambda e, b=btn: b.config(bg=IOS_PICKER_SEL))
            btn.bind("<Leave>", lambda e, b=btn: b.config(bg=IOS_GRAY_BTN_BG))

        # 開始ボタン (iOS風丸ボタン)
        self._make_ios_round_btn(
            self._btn_frame, "Start", IOS_GREEN_BTN, IOS_GREEN_BTN_BG,
            self._start_timer
        ).pack(side="right", padx=4)

    def _on_min_change(self, val):
        self._picker_min = val

    def _on_sec_change(self, val):
        self._picker_sec = val

    def _set_preset(self, m, s):
        self._picker_min = m
        self._picker_sec = s
        self._min_picker.set_index(m)
        self._sec_picker.set_index(s)

    # ============================
    # iOS風タイマーリング表示
    # ============================
    def _show_timer(self):
        self._state = "timer"
        for w in self._display_frame.winfo_children():
            w.destroy()
        for w in self._btn_frame.winfo_children():
            w.destroy()

        size = self.RING_SIZE

        # Canvas でリング描画
        self._ring_canvas = tk.Canvas(
            self._display_frame, width=size, height=size,
            bg=IOS_BG, highlightthickness=0
        )
        self._ring_canvas.pack(pady=(8, 4))

        # セッション表示
        self._count_label = tk.Label(
            self._display_frame, text=self._session_text(),
            font=FONT_STATUS, bg=IOS_BG, fg=IOS_TEXT_DIM
        )
        self._count_label.pack()

        # ボタン: Cancel (左) / Pause・Resume (右)
        self._cancel_btn = self._make_ios_round_btn(
            self._btn_frame, "Cancel", IOS_RED_BTN, IOS_RED_BTN_BG,
            self._cancel_timer
        )
        self._cancel_btn.pack(side="left", padx=4)

        self._pause_resume_btn = self._make_ios_round_btn(
            self._btn_frame, "Pause", IOS_RING_FG, IOS_GRAY_BTN_BG,
            self._toggle_pause
        )
        self._pause_resume_btn.pack(side="right", padx=4)

        self._draw_ring()

    def _session_text(self):
        phase = "WORK" if self._pomo_phase == "work" else "BREAK"
        return f"{phase}  |  Session {self._pomo_count} / {POMO_LONG_BREAK_AFTER}"

    def _draw_ring(self):
        canvas = self._ring_canvas
        canvas.delete("all")
        size = self.RING_SIZE
        pad = 20
        lw = self.RING_WIDTH

        # 背景リング (360度の円弧)
        canvas.create_arc(
            pad, pad, size - pad, size - pad,
            start=0, extent=359.9,
            outline=IOS_RING_BG, width=lw, style="arc"
        )

        # プログレスリング
        if self._total_seconds > 0:
            progress = self._remaining / self._total_seconds
        else:
            progress = 0
        ring_color = IOS_RING_WORK if self._pomo_phase == "work" else IOS_RING_BREAK
        if progress > 0:
            extent = 360 * progress
            canvas.create_arc(
                pad, pad, size - pad, size - pad,
                start=90, extent=extent,
                outline=ring_color, width=lw, style="arc"
            )

        # 中央のタイマーテキスト
        m = self._remaining // 60
        s = self._remaining % 60
        time_text = f"{m:02d}:{s:02d}"
        text_color = IOS_TEXT
        if self._remaining <= 10 and self._running:
            text_color = IOS_RED_BTN
        canvas.create_text(
            size / 2, size / 2,
            text=time_text, font=FONT_TIMER_LARGE,
            fill=text_color
        )

    # ============================
    # iOS風丸ボタン
    # ============================
    def _make_ios_round_btn(self, parent, text, fg_color, bg_color, command):
        btn = tk.Label(
            parent, text=text, font=FONT_TIMER_BTN_LG,
            bg=bg_color, fg=fg_color,
            padx=16, pady=6, cursor="hand2"
        )
        btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e: btn.config(
            bg=self._lighten(bg_color, 0.15)
        ))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg_color))
        return btn

    def _lighten(self, hex_color, amount):
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        r = min(255, int(r + (255 - r) * amount))
        g = min(255, int(g + (255 - g) * amount))
        b = min(255, int(b + (255 - b) * amount))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _make_btn(self, parent, text, color, command):
        btn = tk.Label(
            parent, text=text, font=FONT_TIMER_BTN,
            bg=CARD_BORDER, fg=color, padx=8, pady=2, cursor="hand2"
        )
        btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e: btn.config(bg=FG_DIM))
        btn.bind("<Leave>", lambda e: btn.config(bg=CARD_BORDER))
        return btn

    # ============================
    # タイマーコントロール
    # ============================
    def _start_timer(self):
        total = self._picker_min * 60 + self._picker_sec
        if total <= 0:
            return
        self._total_seconds = total
        self._remaining = total
        self._running = True
        self._show_timer()
        self._tick()

    def _toggle_pause(self):
        if self._running:
            self._running = False
            self._pause_resume_btn.config(text="Resume", fg=IOS_GREEN_BTN)
        else:
            self._running = True
            self._pause_resume_btn.config(text="Pause", fg=IOS_RING_FG)
            self._tick()

    def _cancel_timer(self):
        self._running = False
        if self._after_id:
            self.win.after_cancel(self._after_id)
            self._after_id = None
        self._show_picker()

    def _tick(self):
        if not self._running:
            return
        if self._remaining <= 0:
            self._running = False
            self._on_phase_done()
            return
        self._remaining -= 1
        self._draw_ring()
        self._after_id = self.win.after(1000, self._tick)

    def _on_phase_done(self):
        if self._pomo_phase == "work":
            self._pomo_count += 1
            msg = f"Work session #{self._pomo_count} done!"
        else:
            msg = "Break is over. Time to focus!"
        self._show_notification("TIMER", msg, IOS_GREEN_BTN)
        self._flash_ring(0, callback=self._transition_phase)

    def _transition_phase(self):
        if self._pomo_phase == "work":
            if self._pomo_count % POMO_LONG_BREAK_AFTER == 0:
                self._pomo_phase = "break"
                self._picker_min = POMO_LONG_BREAK_MIN
            else:
                self._pomo_phase = "break"
                self._picker_min = POMO_BREAK_MIN
            self._picker_sec = 0
            self._phase_label.config(
                text="BREAK" if self._picker_min == POMO_BREAK_MIN else "LONG BREAK",
                fg=IOS_RING_BREAK
            )
        else:
            self._pomo_phase = "work"
            self._picker_min = POMO_WORK_MIN
            self._picker_sec = 0
            self._phase_label.config(text="WORK", fg=IOS_GREEN_BTN)

        # ピッカーに戻して次の時間を設定
        self._show_picker()

    def _flash_ring(self, count, callback=None):
        if count >= 8:
            if callback:
                callback()
            return
        if self._state != "timer":
            if callback:
                callback()
            return
        canvas = self._ring_canvas
        size = self.RING_SIZE
        if count % 2 == 0:
            canvas.create_oval(
                20, 20, size - 20, size - 20,
                outline=IOS_RED_BTN, width=3
            )
        else:
            self._draw_ring()
        self.win.after(400, lambda: self._flash_ring(count + 1, callback))

    # ============================
    # スケジュールアラート
    # ============================
    def _build_schedule_section(self, parent):
        card_outer = tk.Frame(parent, bg=CARD_BORDER, padx=1, pady=1)
        card_outer.pack(fill="x", pady=(2, 0))
        self._sched_card = tk.Frame(card_outer, bg=IOS_BG, padx=10, pady=6)
        self._sched_card.pack(fill="x")

        tk.Label(self._sched_card, text="SCHEDULE ALERTS", font=FONT_SECTION,
                 bg=IOS_BG, fg=IOS_TEXT_DIM).pack(anchor="w", pady=(0, 4))

        # 入力行1: 予定名
        row1 = tk.Frame(self._sched_card, bg=IOS_BG)
        row1.pack(fill="x", pady=(0, 2))
        tk.Label(row1, text="Event:", font=FONT_STATUS,
                 bg=IOS_BG, fg=IOS_TEXT_DIM).pack(side="left")
        self._sched_title_entry = tk.Entry(
            row1, width=18, font=FONT_STATUS,
            bg=IOS_CARD, fg=IOS_TEXT, insertbackground=IOS_TEXT,
            relief="flat", bd=2
        )
        self._sched_title_entry.pack(side="left", padx=2, fill="x", expand=True)

        # 入力行2: 時刻 (HH:MM)
        row2 = tk.Frame(self._sched_card, bg=IOS_BG)
        row2.pack(fill="x", pady=(0, 4))
        tk.Label(row2, text="Time:", font=FONT_STATUS,
                 bg=IOS_BG, fg=IOS_TEXT_DIM).pack(side="left")
        self._sched_hour_entry = tk.Entry(
            row2, width=3, font=FONT_STATUS,
            bg=IOS_CARD, fg=IOS_TEXT, insertbackground=IOS_TEXT,
            relief="flat", bd=2, justify="center"
        )
        self._sched_hour_entry.pack(side="left", padx=2)
        self._sched_hour_entry.insert(0, "09")
        tk.Label(row2, text=":", font=FONT_STATUS,
                 bg=IOS_BG, fg=IOS_TEXT).pack(side="left")
        self._sched_min_entry = tk.Entry(
            row2, width=3, font=FONT_STATUS,
            bg=IOS_CARD, fg=IOS_TEXT, insertbackground=IOS_TEXT,
            relief="flat", bd=2, justify="center"
        )
        self._sched_min_entry.pack(side="left", padx=2)
        self._sched_min_entry.insert(0, "00")

        add_btn = self._make_btn(row2, "+Add", IOS_GREEN_BTN, self._add_schedule)
        add_btn.pack(side="left", padx=6)

        # スケジュール一覧
        self._sched_list_frame = tk.Frame(self._sched_card, bg=IOS_BG)
        self._sched_list_frame.pack(fill="x")

    def _add_schedule(self):
        title = self._sched_title_entry.get().strip()
        if not title:
            return
        try:
            hour = int(self._sched_hour_entry.get())
            minute = int(self._sched_min_entry.get())
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return
        except ValueError:
            return

        self._schedules.append({
            "title": title,
            "hour": hour,
            "minute": minute,
            "notified": set(),
        })
        self._sched_title_entry.delete(0, tk.END)
        self._render_schedule_list()

    def _remove_schedule(self, idx):
        if 0 <= idx < len(self._schedules):
            self._schedules.pop(idx)
            self._render_schedule_list()

    def _render_schedule_list(self):
        for w in self._sched_list_frame.winfo_children():
            w.destroy()

        now = datetime.now(ZoneInfo("Asia/Tokyo"))

        for i, sched in enumerate(self._schedules):
            row = tk.Frame(self._sched_list_frame, bg=IOS_BG)
            row.pack(fill="x", pady=1)

            target_min = sched["hour"] * 60 + sched["minute"]
            now_min = now.hour * 60 + now.minute
            is_past = now_min > target_min
            all_notified = len(sched["notified"]) >= len(SCHEDULE_NOTIFY_BEFORE)
            color = IOS_TEXT_DIM if (is_past and all_notified) else IOS_RING_FG

            time_str = f"{sched['hour']:02d}:{sched['minute']:02d}"
            text = f"{time_str}  {sched['title']}"

            tk.Label(
                row, text=text, font=FONT_STATUS,
                bg=IOS_BG, fg=color, anchor="w"
            ).pack(side="left")

            del_btn = tk.Label(
                row, text="\u2715", font=("Segoe UI", 7),
                bg=IOS_BG, fg=IOS_RED_BTN, cursor="hand2"
            )
            del_btn.pack(side="right")
            del_btn.bind("<Button-1>", lambda e, idx=i: self._remove_schedule(idx))

    def _tick_schedule_check(self):
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        now_total_sec = now.hour * 3600 + now.minute * 60 + now.second

        for sched in self._schedules:
            target_sec = sched["hour"] * 3600 + sched["minute"] * 60
            diff = target_sec - now_total_sec

            for before_sec in SCHEDULE_NOTIFY_BEFORE:
                if before_sec in sched["notified"]:
                    continue
                if 0 <= diff <= before_sec:
                    if abs(diff - before_sec) <= 1 or (diff < before_sec and before_sec not in sched["notified"]):
                        sched["notified"].add(before_sec)
                        label = SCHEDULE_NOTIFY_LABELS.get(before_sec, f"{before_sec}s")
                        self._show_notification(
                            f"{label} before",
                            f"{sched['title']}  ({sched['hour']:02d}:{sched['minute']:02d})",
                            WARN_COLOR
                        )
                        self._render_schedule_list()
                        break

        self.win.after(1000, self._tick_schedule_check)

    # ============================
    # 通知ポップアップ (共通)
    # ============================
    def _show_notification(self, header, message, color):
        notif = tk.Toplevel(self.win)
        notif.overrideredirect(True)
        notif.attributes("-topmost", True)
        notif.configure(bg=color)

        nx = self.win.winfo_x()
        ny = self.win.winfo_y() - 60
        notif.geometry(f"+{nx}+{ny}")

        frame = tk.Frame(notif, bg=IOS_BG, padx=12, pady=8)
        frame.pack(padx=2, pady=2)

        tk.Label(
            frame, text=header, font=FONT_SECTION,
            bg=IOS_BG, fg=color
        ).pack(anchor="w")
        tk.Label(
            frame, text=message, font=FONT_LABEL,
            bg=IOS_BG, fg=IOS_TEXT
        ).pack(anchor="w")

        dismiss = tk.Label(
            frame, text="OK", font=FONT_TIMER_BTN_LG,
            bg=IOS_GRAY_BTN_BG, fg=IOS_GREEN_BTN,
            padx=10, pady=3, cursor="hand2"
        )
        dismiss.pack(anchor="e", pady=(6, 0))
        dismiss.bind("<Button-1>", lambda e: notif.destroy())

        notif.after(10000, lambda: notif.destroy() if notif.winfo_exists() else None)

    def close(self):
        self.win.destroy()
        self.dashboard._timer_popup = None


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
        self._timer_popup = None

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

        # タイマーアイコン (時計)
        self._timer_icon = tk.Label(
            title_bar, text="\u23f0", font=FONT_ICON,
            bg=BG, fg=FG_DIM, cursor="hand2"
        )
        self._timer_icon.pack(side="right", padx=(0, 6))
        self._timer_icon.bind("<Button-1>", lambda e: self._toggle_timer_popup())
        self._timer_icon.bind("<Enter>", lambda e: self._timer_icon.config(fg=ACCENT))
        self._timer_icon.bind("<Leave>", lambda e: self._timer_icon.config(
            fg=ACCENT if self._timer_popup else FG_DIM
        ))

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

    def _toggle_timer_popup(self):
        """タイマーポップアップの開閉"""
        if self._timer_popup and self._timer_popup.win.winfo_exists():
            self._timer_popup.close()
            self._timer_icon.config(fg=FG_DIM)
        else:
            self._timer_popup = TimerAlertPopup(self.root, self)
            self._timer_icon.config(fg=ACCENT)

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
