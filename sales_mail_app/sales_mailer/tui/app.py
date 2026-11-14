"""ターミナル版のメイン画面（デスクトップのアイコンから起動）."""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from .. import APP_TITLE, __version__
from ..config import Settings, data_dir, load_settings, save_settings
from ..db import Database
from ..services import stats_text
from .dialogs import DIALOG_CSS, ConfirmDialog, MessageDialog
from .panes import (
    BasePane, CompaniesPane, FollowMailPane, HistoryPane, NewMailPane, ResearchPane, SettingsPane, TemplatesPane,
)

APP_CSS = """
Screen { layout: vertical; }
#stats { height: 1; padding: 0 1; background: $boost; color: $text; }
TabbedContent { height: 1fr; }
TabPane { padding: 0 1; }
BasePane { height: 1fr; }
.pane { height: 1fr; }
.left { width: 34; height: 1fr; padding-right: 1; }
.right { width: 1fr; height: 1fr; }
.bar { height: auto; margin-top: 1; }
.bar > * { margin-right: 2; }
.bar > Button { width: auto; min-width: 6; }
.row > Button { width: auto; min-width: 6; margin-right: 1; }
.bar > Select { width: 34; }
.bar > Static { width: auto; color: $text-muted; }
.row { height: auto; margin-top: 1; }
.tight { margin-top: 0; }
.row > Label { width: auto; }
.label { color: $accent; margin-top: 1; text-style: bold; }
.help { color: $text-muted; margin-top: 1; height: auto; }
.wide { width: 100%; margin-top: 1; }
Input.num { width: 7; }
#search { width: 30; }
MarkTable { height: 1fr; min-height: 5; margin-top: 1; }
PrefPicker { height: 1fr; min-height: 6; }
PrefPicker.short { height: 1fr; min-height: 5; }
RichLog.log { height: 5; margin-top: 1; background: $surface-darken-1; }
RichLog.small { height: 3; }
TextArea.preview { height: 9; margin-top: 1; }
TextArea.detail { height: 10; margin-top: 1; }
TextArea.body { height: 1fr; }
TextArea.optout { height: 5; }
ProgressBar { width: 1fr; }
Grid.form { grid-size: 2; grid-columns: 16 1fr; grid-rows: auto; height: auto; grid-gutter: 1 1; }
Grid.section { grid-size: 2; grid-columns: 20 1fr; grid-rows: auto; height: auto; grid-gutter: 0 1;
               border: round $primary; padding: 0 1; margin-bottom: 1; }
Vertical.section { height: auto; border: round $primary; padding: 0 1; }
.settings-cols { height: auto; }
.settings-scroll { margin-top: 1; }
.settings-col { width: 1fr; height: auto; margin-right: 1; }
#summary, #count { height: auto; }
"""

TABS = [
    ("companies", "F1 企業リスト", CompaniesPane),
    ("research", "F2 新規開拓", ResearchPane),
    ("newmail", "F3 新規メール", NewMailPane),
    ("follow", "F4 フォロー", FollowMailPane),
    ("templates", "F5 テンプレート", TemplatesPane),
    ("history", "F6 送信履歴", HistoryPane),
    ("settings", "F7 設定", SettingsPane),
]


class SalesMailerTUI(App):
    TITLE = APP_TITLE
    SUB_TITLE = f"ターミナル版 v{__version__}"
    CSS = APP_CSS + DIALOG_CSS
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        *[Binding(f"f{i}", f"show_tab('{tab_id}')", label.split(" ", 1)[1], show=False, priority=True)
          for i, (tab_id, label, _cls) in enumerate(TABS, 1)],
        Binding("ctrl+q", "quit_app", "終了", priority=True),
    ]

    def __init__(self, db_path: str | Path | None = None, first_run_prompts: bool = True,
                 initial_tab: str | None = None):
        super().__init__()
        self.settings: Settings = load_settings()
        self.db = Database(db_path or data_dir() / "sales_mailer.db")
        self.first_run_prompts = first_run_prompts
        self.initial_tab = initial_tab

    def compose(self) -> ComposeResult:
        yield Header(icon="✉")
        yield Static("", id="stats", markup=False)
        initial = self.initial_tab if self.initial_tab in {t[0] for t in TABS} else "companies"
        with TabbedContent(id="tabs", initial=initial):
            for tab_id, label, cls in TABS:
                with TabPane(label, id=tab_id):
                    yield cls(id=f"pane-{tab_id}")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_stats()
        if self.initial_tab in {t[0] for t in TABS}:
            self.action_show_tab(self.initial_tab)
        if self.first_run_prompts:
            self.first_run()

    @work
    async def first_run(self) -> None:
        if sys.platform == "darwin":  # Mac の F1〜F7 は既定で画面の明るさなどに割り当てられている
            self.notify("タブはマウスでクリックして切り替えられます（キーボードでは fn + F1〜F7）。", timeout=12)
        if not self.settings.smtp_user:
            self.action_show_tab("settings")
            self.notify("はじめに、メール送信（SMTP）と送信者情報を設定してください。", timeout=10)
        if self.settings.shortcut_prompted:
            return
        from ..shortcut import shortcut_exists

        self.settings.shortcut_prompted = True
        save_settings(self.settings)
        if shortcut_exists():
            return
        if await self.push_screen_wait(ConfirmDialog(
                "デスクトップにアイコンを作成しますか？\n\n次回からはアイコンをクリックするだけで、"
                "ターミナルが開いてこの画面が起動します。\n（設定タブの「デスクトップにアイコンを作成」からいつでも作れます）",
                "デスクトップアイコン", ok="作成する", cancel="今はしない")):
            self.create_shortcut()

    def create_shortcut(self) -> None:
        from ..shortcut import create_desktop_shortcut

        try:
            path = create_desktop_shortcut()
        except Exception as e:  # noqa: BLE001
            message = f"アイコンを作成できませんでした:\n{e}"
            if sys.platform == "darwin" and isinstance(e, PermissionError):
                message += ("\n\nMac の「システム設定」→「プライバシーとセキュリティ」→「ファイルとフォルダ」→"
                            "「ターミナル」で「デスクトップフォルダ」をオンにしてから、もう一度お試しください。")
            self.push_screen(MessageDialog(message, "デスクトップアイコン"))
            return
        self.push_screen(MessageDialog(f"デスクトップにアイコンを作成しました。\n{path}\n\n"
                                       "次回からはこのアイコンをダブルクリックすると、ターミナルでこの画面が開きます。",
                                       "デスクトップアイコン"))

    # ---------------------------------------------------------------- 共通
    def refresh_stats(self) -> None:
        self.query_one("#stats", Static).update(stats_text(self.db, self.settings))

    def data_changed(self) -> None:
        self.refresh_stats()
        self.query_one(CompaniesPane).reload()

    def update_settings(self, settings: Settings) -> None:
        self.settings = settings
        save_settings(settings)
        self.refresh_stats()

    def has_ai_key(self) -> bool:
        return bool(self.settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def action_show_tab(self, tab_id: str) -> None:
        # 非表示になるタブの中にフォーカスが残っていると元のタブに戻されるため、先に外す
        self.screen.set_focus(None)
        self.query_one(TabbedContent).active = tab_id
        self.call_after_refresh(self._focus_pane, tab_id)

    def _focus_pane(self, tab_id: str) -> None:
        pane = self.query_one(f"#pane-{tab_id}", BasePane)
        for selector in ("MarkTable", "PrefPicker", "Input"):  # 表 → 地域 → 入力欄 の順で最初の部品に合わせる
            for widget in pane.query(selector):
                if widget.focusable:
                    widget.focus()
                    return

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        for pane in event.pane.query(BasePane):
            pane.on_show()
        self.refresh_stats()

    @work
    async def action_quit_app(self) -> None:
        busy = any(p.busy for p in self.query(BasePane))
        if busy and not await self.push_screen_wait(ConfirmDialog(
                "送信または調査を実行中です。終了すると途中で止まります。終了しますか？", "終了の確認")):
            return
        self.exit()


MIN_COLS, MIN_ROWS = 120, 30


def prepare_terminal(title: str) -> None:
    """ウィンドウのタイトルを設定し、画面が小さければ広げるよう端末に依頼する（対応していない端末では無視される）."""
    if not (sys.stdout and sys.stdout.isatty()):
        return
    sys.stdout.write(f"\x1b]0;{title}\x07")
    size = shutil.get_terminal_size((MIN_COLS, MIN_ROWS))
    if size.columns < MIN_COLS or size.lines < MIN_ROWS:  # macOS のターミナル.app などは既定が 80x24
        sys.stdout.write(f"\x1b[8;{max(size.lines, MIN_ROWS + 4)};{max(size.columns, MIN_COLS + 10)}t")
        sys.stdout.flush()
        time.sleep(0.3)
    sys.stdout.flush()


def main(initial_tab: str | None = None) -> None:
    prepare_terminal(APP_TITLE)
    SalesMailerTUI(initial_tab=initial_tab).run()
