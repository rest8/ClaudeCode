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

# すべてのシンボル名→ティッカーの逆引き
ALL_ALERT_SYMBOLS = {}
for _name, _sym in FX_SYMBOLS.items():
    ALL_ALERT_SYMBOLS[_name] = _sym
ALL_ALERT_SYMBOLS["Platinum"] = PLATINUM_SYMBOL
for _name, _sym in STOCK_SYMBOLS.items():
    ALL_ALERT_SYMBOLS[_name] = _sym

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

# --- フォント ---
FONT_TITLE = ("Segoe UI", 10, "bold")
FONT_SECTION = ("Segoe UI", 8, "bold")
FONT_LABEL = ("Segoe UI", 8)
FONT_VALUE = ("Consolas", 9)
FONT_VALUE_BOLD = ("Consolas", 9, "bold")
FONT_STATUS = ("Segoe UI", 7)
FONT_CLOSE = ("Segoe UI", 9)
FONT_TIMER_DISPLAY = ("Consolas", 18, "bold")
FONT_TIMER_BTN = ("Segoe UI", 8)
FONT_ICON = ("Segoe UI", 9)


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
# Timer / Alert Popup
# ============================================================

class TimerAlertPopup:
    """タイマー＆プライスアラートのポップアップウィンドウ"""

    def __init__(self, parent, dashboard):
        self.dashboard = dashboard
        self.win = tk.Toplevel(parent)
        self.win.title("Timer & Alerts")
        self.win.configure(bg=BG)
        self.win.attributes("-topmost", True)
        self.win.overrideredirect(True)
        self.win.resizable(False, False)

        # 親ウィンドウの近くに配置
        px = parent.winfo_x() + parent.winfo_width() + 4
        py = parent.winfo_y()
        self.win.geometry(f"+{px}+{py}")

        # ドラッグ
        self._drag_data = {"x": 0, "y": 0}
        self.win.bind("<Button-1>", self._on_drag_start)
        self.win.bind("<B1-Motion>", self._on_drag_motion)

        # タイマー状態
        self._timer_seconds = 0
        self._timer_running = False
        self._timer_after_id = None

        # アラート一覧: [{symbol_name, ticker, condition, threshold, active}]
        self._alerts = []
        self._alert_widgets = []

        self._build_ui()

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
        border = tk.Frame(self.win, bg=CARD_BORDER, padx=1, pady=1)
        border.pack(fill="both", expand=True)
        main = tk.Frame(border, bg=BG, padx=0, pady=0)
        main.pack(fill="both", expand=True)

        # ヘッダー
        hdr = tk.Frame(main, bg=BG, padx=10, pady=5)
        hdr.pack(fill="x")
        tk.Label(hdr, text="TIMER & ALERTS", font=FONT_SECTION,
                 bg=BG, fg=ACCENT).pack(side="left")
        close_btn = tk.Label(hdr, text="\u2715", font=FONT_STATUS,
                             bg=BG, fg=CLOSE_FG, cursor="hand2")
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda e: self.close())
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg=CLOSE_HOVER))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg=CLOSE_FG))

        tk.Frame(main, bg=ACCENT, height=1).pack(fill="x", padx=6)

        # --- タイマーセクション ---
        self._build_timer_section(main)

        tk.Frame(main, bg=CARD_BORDER, height=1).pack(fill="x", padx=6, pady=2)

        # --- アラートセクション ---
        self._build_alert_section(main)

    def _build_timer_section(self, parent):
        card_outer = tk.Frame(parent, bg=CARD_BORDER, padx=1, pady=1)
        card_outer.pack(fill="x", padx=6, pady=3)
        card = tk.Frame(card_outer, bg=CARD_BG, padx=10, pady=6)
        card.pack(fill="x")

        tk.Label(card, text="TIMER", font=FONT_SECTION,
                 bg=CARD_BG, fg=FG_DIM).pack(anchor="w")

        # 時間表示
        self._timer_display = tk.Label(
            card, text="00:00:00", font=FONT_TIMER_DISPLAY,
            bg=CARD_BG, fg=ACCENT
        )
        self._timer_display.pack(pady=(4, 6))

        # プリセットボタン
        preset_frame = tk.Frame(card, bg=CARD_BG)
        preset_frame.pack(fill="x", pady=(0, 4))
        for label, secs in [("1m", 60), ("5m", 300), ("15m", 900), ("30m", 1800), ("1h", 3600)]:
            btn = tk.Label(
                preset_frame, text=label, font=FONT_TIMER_BTN,
                bg=CARD_BORDER, fg=FG, padx=6, pady=1, cursor="hand2"
            )
            btn.pack(side="left", padx=2)
            btn.bind("<Button-1>", lambda e, s=secs: self._set_timer(s))
            btn.bind("<Enter>", lambda e, b=btn: b.config(bg=FG_DIM))
            btn.bind("<Leave>", lambda e, b=btn: b.config(bg=CARD_BORDER))

        # カスタム入力行
        custom_frame = tk.Frame(card, bg=CARD_BG)
        custom_frame.pack(fill="x", pady=(0, 4))
        tk.Label(custom_frame, text="Min:", font=FONT_STATUS,
                 bg=CARD_BG, fg=FG_DIM).pack(side="left")
        self._custom_min_entry = tk.Entry(
            custom_frame, width=5, font=FONT_STATUS,
            bg=CARD_BORDER, fg=FG, insertbackground=FG,
            relief="flat", bd=2
        )
        self._custom_min_entry.pack(side="left", padx=2)
        set_btn = tk.Label(
            custom_frame, text="Set", font=FONT_TIMER_BTN,
            bg=CARD_BORDER, fg=ACCENT, padx=6, pady=1, cursor="hand2"
        )
        set_btn.pack(side="left", padx=2)
        set_btn.bind("<Button-1>", lambda e: self._set_timer_custom())
        set_btn.bind("<Enter>", lambda e: set_btn.config(bg=FG_DIM))
        set_btn.bind("<Leave>", lambda e: set_btn.config(bg=CARD_BORDER))

        # コントロールボタン
        ctrl_frame = tk.Frame(card, bg=CARD_BG)
        ctrl_frame.pack(fill="x")

        self._start_btn = self._make_ctrl_btn(ctrl_frame, "Start", UP_COLOR, self._start_timer)
        self._start_btn.pack(side="left", padx=2)

        self._pause_btn = self._make_ctrl_btn(ctrl_frame, "Pause", WARN_COLOR, self._pause_timer)
        self._pause_btn.pack(side="left", padx=2)

        self._reset_btn = self._make_ctrl_btn(ctrl_frame, "Reset", FG_DIM, self._reset_timer)
        self._reset_btn.pack(side="left", padx=2)

    def _make_ctrl_btn(self, parent, text, color, command):
        btn = tk.Label(
            parent, text=text, font=FONT_TIMER_BTN,
            bg=CARD_BORDER, fg=color, padx=8, pady=2, cursor="hand2"
        )
        btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e: btn.config(bg=FG_DIM))
        btn.bind("<Leave>", lambda e: btn.config(bg=CARD_BORDER))
        return btn

    def _set_timer(self, seconds):
        self._timer_running = False
        self._timer_seconds = seconds
        self._update_timer_display()

    def _set_timer_custom(self):
        try:
            mins = float(self._custom_min_entry.get())
            self._set_timer(int(mins * 60))
        except ValueError:
            pass

    def _start_timer(self):
        if self._timer_seconds > 0 and not self._timer_running:
            self._timer_running = True
            self._tick_timer()

    def _pause_timer(self):
        self._timer_running = False

    def _reset_timer(self):
        self._timer_running = False
        self._timer_seconds = 0
        self._update_timer_display()
        self._timer_display.config(fg=ACCENT)

    def _tick_timer(self):
        if not self._timer_running:
            return
        if self._timer_seconds <= 0:
            self._timer_running = False
            self._timer_seconds = 0
            self._update_timer_display()
            self._on_timer_finished()
            return
        self._timer_seconds -= 1
        self._update_timer_display()
        # 残り10秒以下で警告色
        if self._timer_seconds <= 10:
            self._timer_display.config(fg=DOWN_COLOR)
        self._timer_after_id = self.win.after(1000, self._tick_timer)

    def _update_timer_display(self):
        h = self._timer_seconds // 3600
        m = (self._timer_seconds % 3600) // 60
        s = self._timer_seconds % 60
        self._timer_display.config(text=f"{h:02d}:{m:02d}:{s:02d}")

    def _on_timer_finished(self):
        """タイマー完了時のアラート"""
        self._timer_display.config(fg=DOWN_COLOR)
        self._flash_timer(0)

    def _flash_timer(self, count):
        """タイマー完了を点滅で通知"""
        if count >= 10:
            self._timer_display.config(fg=ACCENT)
            return
        color = DOWN_COLOR if count % 2 == 0 else BG
        self._timer_display.config(fg=color)
        self.win.after(400, lambda: self._flash_timer(count + 1))

    # --- アラートセクション ---
    def _build_alert_section(self, parent):
        card_outer = tk.Frame(parent, bg=CARD_BORDER, padx=1, pady=1)
        card_outer.pack(fill="x", padx=6, pady=3)
        self._alert_card = tk.Frame(card_outer, bg=CARD_BG, padx=10, pady=6)
        self._alert_card.pack(fill="x")

        tk.Label(self._alert_card, text="PRICE ALERTS", font=FONT_SECTION,
                 bg=CARD_BG, fg=FG_DIM).pack(anchor="w", pady=(0, 4))

        # 新規アラート追加行
        add_frame = tk.Frame(self._alert_card, bg=CARD_BG)
        add_frame.pack(fill="x", pady=(0, 4))

        # シンボル選択
        self._alert_symbol_var = tk.StringVar(value=list(ALL_ALERT_SYMBOLS.keys())[0])
        sym_menu = tk.OptionMenu(add_frame, self._alert_symbol_var,
                                 *ALL_ALERT_SYMBOLS.keys())
        sym_menu.config(
            font=FONT_STATUS, bg=CARD_BORDER, fg=FG,
            activebackground=FG_DIM, activeforeground=FG,
            highlightthickness=0, relief="flat", bd=0
        )
        sym_menu["menu"].config(
            bg=CARD_BG, fg=FG, activebackground=FG_DIM,
            activeforeground=FG, font=FONT_STATUS
        )
        sym_menu.pack(side="left")

        # 条件
        self._alert_cond_var = tk.StringVar(value=">=")
        cond_menu = tk.OptionMenu(add_frame, self._alert_cond_var, ">=", "<=")
        cond_menu.config(
            font=FONT_STATUS, bg=CARD_BORDER, fg=FG,
            activebackground=FG_DIM, activeforeground=FG,
            highlightthickness=0, relief="flat", bd=0, width=2
        )
        cond_menu["menu"].config(
            bg=CARD_BG, fg=FG, activebackground=FG_DIM,
            activeforeground=FG, font=FONT_STATUS
        )
        cond_menu.pack(side="left", padx=2)

        # 閾値
        self._alert_threshold_entry = tk.Entry(
            add_frame, width=8, font=FONT_STATUS,
            bg=CARD_BORDER, fg=FG, insertbackground=FG,
            relief="flat", bd=2
        )
        self._alert_threshold_entry.pack(side="left", padx=2)

        # 追加ボタン
        add_btn = tk.Label(
            add_frame, text="+Add", font=FONT_TIMER_BTN,
            bg=CARD_BORDER, fg=ACCENT, padx=6, pady=1, cursor="hand2"
        )
        add_btn.pack(side="left", padx=4)
        add_btn.bind("<Button-1>", lambda e: self._add_alert())
        add_btn.bind("<Enter>", lambda e: add_btn.config(bg=FG_DIM))
        add_btn.bind("<Leave>", lambda e: add_btn.config(bg=CARD_BORDER))

        # アラートリスト表示エリア
        self._alert_list_frame = tk.Frame(self._alert_card, bg=CARD_BG)
        self._alert_list_frame.pack(fill="x")

    def _add_alert(self):
        name = self._alert_symbol_var.get()
        cond = self._alert_cond_var.get()
        try:
            threshold = float(self._alert_threshold_entry.get())
        except ValueError:
            return

        ticker = ALL_ALERT_SYMBOLS[name]
        alert = {
            "symbol_name": name,
            "ticker": ticker,
            "condition": cond,
            "threshold": threshold,
            "active": True,
        }
        self._alerts.append(alert)
        self._render_alert_list()
        self._alert_threshold_entry.delete(0, tk.END)

    def _remove_alert(self, idx):
        if 0 <= idx < len(self._alerts):
            self._alerts.pop(idx)
            self._render_alert_list()

    def _render_alert_list(self):
        for w in self._alert_list_frame.winfo_children():
            w.destroy()

        for i, alert in enumerate(self._alerts):
            row = tk.Frame(self._alert_list_frame, bg=CARD_BG)
            row.pack(fill="x", pady=1)

            status_color = ACCENT if alert["active"] else FG_DIM
            cond_text = (
                f"{alert['symbol_name']} {alert['condition']} "
                f"{alert['threshold']:,.2f}"
            )
            tk.Label(
                row, text=cond_text, font=FONT_STATUS,
                bg=CARD_BG, fg=status_color, anchor="w"
            ).pack(side="left")

            del_btn = tk.Label(
                row, text="\u2715", font=("Segoe UI", 7),
                bg=CARD_BG, fg=CLOSE_FG, cursor="hand2"
            )
            del_btn.pack(side="right")
            del_btn.bind("<Button-1>", lambda e, idx=i: self._remove_alert(idx))

    def check_alerts(self, latest_prices):
        """最新価格でアラートをチェック（MarketDashboardから呼ばれる）"""
        for alert in self._alerts:
            if not alert["active"]:
                continue
            price_data = latest_prices.get(alert["ticker"])
            if price_data is None:
                continue
            price = price_data[0] if isinstance(price_data, tuple) else price_data
            if price is None:
                continue

            triggered = False
            if alert["condition"] == ">=" and price >= alert["threshold"]:
                triggered = True
            elif alert["condition"] == "<=" and price <= alert["threshold"]:
                triggered = True

            if triggered:
                alert["active"] = False
                self._render_alert_list()
                self._flash_alert_notification(alert, price)

    def _flash_alert_notification(self, alert, price):
        """アラート発火時の通知"""
        notif = tk.Toplevel(self.win)
        notif.overrideredirect(True)
        notif.attributes("-topmost", True)
        notif.configure(bg=WARN_COLOR)

        nx = self.win.winfo_x() + 10
        ny = self.win.winfo_y() - 50
        notif.geometry(f"+{nx}+{ny}")

        frame = tk.Frame(notif, bg=BG, padx=8, pady=4)
        frame.pack(padx=2, pady=2)

        msg = (
            f"{alert['symbol_name']} {alert['condition']} "
            f"{alert['threshold']:,.2f}  (now: {price:,.2f})"
        )
        tk.Label(
            frame, text="ALERT!", font=FONT_SECTION,
            bg=BG, fg=WARN_COLOR
        ).pack()
        tk.Label(
            frame, text=msg, font=FONT_STATUS,
            bg=BG, fg=FG
        ).pack()

        dismiss = tk.Label(
            frame, text="Dismiss", font=FONT_STATUS,
            bg=CARD_BORDER, fg=ACCENT, padx=6, cursor="hand2"
        )
        dismiss.pack(pady=(4, 0))
        dismiss.bind("<Button-1>", lambda e: notif.destroy())

        # 8秒後に自動で閉じる
        notif.after(8000, lambda: notif.destroy() if notif.winfo_exists() else None)

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
        self._latest_prices = {}

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

    def _check_alerts(self, data):
        """アラートチェックを実行"""
        self._latest_prices.update(data)
        if self._timer_popup and self._timer_popup.win.winfo_exists():
            self._timer_popup.check_alerts(self._latest_prices)

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
        self._check_alerts(data)

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
        self._check_alerts(data)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = MarketDashboard()
    app.run()
