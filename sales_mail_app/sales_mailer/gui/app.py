"""メインウィンドウ."""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
import traceback
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Callable

from .. import APP_TITLE, __version__
from ..config import data_dir, load_settings, save_settings, Settings
from ..db import STATUS_CONTRACTED, STATUS_ERROR, STATUS_NEW, STATUS_OPTED_OUT, STATUS_REPLIED, STATUS_SENT, Database


class App(tk.Tk):
    def __init__(self, db_path: str | None = None):
        super().__init__()
        self.title(f"{APP_TITLE}  v{__version__}")
        self.geometry("1280x820")
        self.minsize(1024, 680)
        self._setup_style()

        self.settings: Settings = load_settings()
        self.db = Database(db_path or data_dir() / "sales_mailer.db")
        self._ui_queue: queue.Queue = queue.Queue()

        self._build_header()
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        from .companies_tab import CompaniesTab
        from .history_tab import HistoryTab
        from .research_tab import ResearchTab
        from .send_tabs import FollowMailTab, NewMailTab
        from .settings_tab import SettingsTab
        from .templates_tab import TemplatesTab

        self.companies_tab = CompaniesTab(self.notebook, self)
        self.research_tab = ResearchTab(self.notebook, self)
        self.new_mail_tab = NewMailTab(self.notebook, self)
        self.follow_tab = FollowMailTab(self.notebook, self)
        self.templates_tab = TemplatesTab(self.notebook, self)
        self.history_tab = HistoryTab(self.notebook, self)
        self.settings_tab = SettingsTab(self.notebook, self)
        for tab, label in (
            (self.companies_tab, "企業リスト"),
            (self.research_tab, "新規開拓（地域調査）"),
            (self.new_mail_tab, "新規メール送信"),
            (self.follow_tab, "フォローメール"),
            (self.templates_tab, "テンプレート"),
            (self.history_tab, "送信履歴"),
            (self.settings_tab, "設定"),
        ):
            self.notebook.add(tab, text=f"  {label}  ")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.refresh_stats()
        self.after(100, self._drain_ui_queue)
        if not self.settings.smtp_user:
            self.after(300, lambda: self.notebook.select(self.settings_tab))

    # ---------------------------------------------------------------- 見た目
    def _setup_style(self) -> None:
        style = ttk.Style(self)
        if sys.platform.startswith("linux") and "clam" in style.theme_names():
            style.theme_use("clam")
        families = set(tkfont.families(self))
        preferred = {
            "win32": ["Yu Gothic UI", "Meiryo UI", "Meiryo"],
            "darwin": ["Hiragino Sans", "Hiragino Kaku Gothic ProN"],
        }.get(sys.platform, ["Noto Sans CJK JP", "IPAexGothic", "IPAGothic", "TakaoGothic"])
        family = next((f for f in preferred if f in families), None)
        size = 10 if sys.platform != "darwin" else 13
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont",
                     "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont", "TkFixedFont"):
            try:
                f = tkfont.nametofont(name)
                if family:
                    f.configure(family=family)
                f.configure(size=size if name != "TkSmallCaptionFont" else size - 1)
            except tk.TclError:
                pass
        linespace = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        style.configure("Treeview", rowheight=linespace + 8)
        style.configure("Header.TLabel", font=(family or "TkDefaultFont", size + 6, "bold"))
        style.configure("Stat.TLabel", font=(family or "TkDefaultFont", size + 1))
        style.configure("Accent.TButton", font=(family or "TkDefaultFont", size, "bold"))

    def _build_header(self) -> None:
        header = ttk.Frame(self, padding=(12, 10, 12, 6))
        header.pack(fill="x")
        ttk.Label(header, text=APP_TITLE, style="Header.TLabel").pack(side="left")
        self.stats_label = ttk.Label(header, text="", style="Stat.TLabel")
        self.stats_label.pack(side="right")

    def refresh_stats(self) -> None:
        s = self.db.stats()
        self.stats_label.configure(
            text=(f"未送付 {s[STATUS_NEW]}　送付済み {s[STATUS_SENT]}　返信あり {s[STATUS_REPLIED]}　"
                  f"契約済み {s[STATUS_CONTRACTED]}　配信停止 {s[STATUS_OPTED_OUT]}　送信エラー {s[STATUS_ERROR]}"
                  f"　｜　本日の送信 {s['today']} / {self.settings.daily_limit} 通")
        )

    def data_changed(self) -> None:
        """企業データが変わったときに各タブを更新する."""
        self.refresh_stats()
        self.companies_tab.reload()

    def _on_tab_changed(self, _event=None) -> None:
        tab = self.nametowidget(self.notebook.select())
        if hasattr(tab, "on_show"):
            tab.on_show()

    def ensure_ai_key(self, parent) -> bool:
        """AI 機能を使う前に Anthropic API キーが設定されているか確認する."""
        if self.settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"):
            return True
        messagebox.showwarning("APIキー", "設定タブで Anthropic API キーを入力してください（AI機能で使用します）",
                               parent=parent)
        return False

    def update_settings(self, settings: Settings) -> None:
        self.settings = settings
        save_settings(settings)
        self.refresh_stats()

    # ---------------------------------------------------------------- スレッド
    def call_in_ui(self, fn: Callable, *args) -> None:
        """ワーカースレッドから UI を更新するときに使う."""
        self._ui_queue.put((fn, args))

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                fn, args = self._ui_queue.get_nowait()
                try:
                    fn(*args)
                except Exception:
                    traceback.print_exc()
        except queue.Empty:
            pass
        self.after(100, self._drain_ui_queue)

    def run_background(self, work: Callable[[], object], on_done: Callable[[object], None] | None = None,
                       on_error: Callable[[Exception], None] | None = None) -> threading.Thread:
        def runner():
            try:
                result = work()
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                if on_error:
                    self.call_in_ui(on_error, e)
                else:
                    self.call_in_ui(lambda err: messagebox.showerror("エラー", str(err), parent=self), e)
                return
            if on_done:
                self.call_in_ui(on_done, result)

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        return thread


def main() -> None:
    app = App()
    app.mainloop()
