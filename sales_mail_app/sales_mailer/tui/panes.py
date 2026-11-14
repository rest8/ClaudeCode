"""ターミナル版の各タブ（企業リスト・新規開拓・新規メール・フォロー・テンプレート・送信履歴・設定）."""

from __future__ import annotations

import threading
from dataclasses import fields, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Grid, Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button, Checkbox, DataTable, Input, Label, ProgressBar, RichLog, Select, Static, TextArea,
)

from ..campaign import SendOptions, prepare_mail, run_send_job, send_test_mail
from ..config import Settings, data_dir, is_demo
from ..csv_io import read_companies_csv, write_companies_csv, write_rows_csv
from ..db import (
    KIND_FOLLOW, KIND_NEW, RESULT_DRY_RUN, RESULT_FAILED, RESULT_SENT, STATUS_CONTRACTED, STATUS_ERROR,
    STATUS_LABELS, STATUS_NEW, STATUS_OPTED_OUT, STATUS_REPLIED, STATUS_SENT,
)
from ..mailer import PLACEHOLDERS, days_since, format_date_jp, signature
from ..regions import PREFECTURES
from ..research import Prospect
from ..services import (
    ADDED, METHOD_CLAUDE, METHOD_GOOGLE, METHOD_LABELS, add_prospects, judge_label, missing_sender_info,
    run_research, send_confirmation,
)
from ..shortcut import create_desktop_shortcut, desktop_dir
from .dialogs import ChoiceDialog, CompanyForm, ConfirmDialog, ImportDialog, InputDialog, MessageDialog
from .widgets import MarkTable, PrefPicker, clean_path, split_list


class BasePane(Container):
    """各タブの共通処理（バックグラウンド実行など）."""

    busy = False

    def on_show(self) -> None:
        pass

    @property
    def db(self):
        return self.app.db

    @property
    def settings(self) -> Settings:
        return self.app.settings

    def run_bg(self, work_fn: Callable[[], object], done: Callable[[object], None] | None = None,
               error: Callable[[Exception], None] | None = None) -> None:
        """重い処理を別スレッドで実行し、結果を画面スレッドで受け取る."""

        def runner() -> None:
            try:
                result = work_fn()
            except Exception as e:  # noqa: BLE001
                self.app.call_from_thread(self._failed, e, error)
                return
            if done:
                self.app.call_from_thread(done, result)

        self.run_worker(runner, thread=True, exit_on_error=False)

    def _failed(self, e: Exception, error: Callable[[Exception], None] | None) -> None:
        if error:
            error(e)
        else:
            self.app.push_screen(MessageDialog(str(e), "エラー"))

    def need_ai_key(self) -> bool:
        if self.app.has_ai_key():
            return True
        self.notify("設定タブ（F7）で Anthropic API キーを入力してください（AI機能で使用します）", severity="warning")
        return False


# ======================================================================= 企業リスト
COMPANY_FILTERS = [
    ("有効（契約済・停止を除く）", "active"), ("未送付", STATUS_NEW), ("送付済み", STATUS_SENT),
    ("返信あり", STATUS_REPLIED), ("契約済み（除外中）", STATUS_CONTRACTED), ("配信停止（除外中）", STATUS_OPTED_OUT),
    ("送信エラー", STATUS_ERROR), ("すべて", "all"),
]
COMPANY_COLUMNS = [
    ("id", "ID"), ("name", "会社名"), ("status", "ステータス"), ("email", "メールアドレス"), ("prefecture", "都道府県"),
    ("city", "市区町村"), ("industry", "業種"), ("first", "初回送信"), ("last", "最終送信"), ("follow", "フォロー"),
    ("phone", "電話番号"), ("website", "Webサイト"),
]


def company_values(c: dict) -> list:
    return [c["id"], c["name"], STATUS_LABELS.get(c["status"], c["status"]), c["email"], c["prefecture"],
            c["city"], c["industry"], format_date_jp(c["first_sent_at"]), format_date_jp(c["last_sent_at"]),
            c["follow_count"], c["phone"], c["website"]]


def company_style(c: dict) -> str:
    if c["status"] in (STATUS_CONTRACTED, STATUS_OPTED_OUT):
        return "muted"
    if c["status"] == STATUS_ERROR or not c["email"]:
        return "warn"
    return "ok" if c["status"] == STATUS_REPLIED else ""


class CompaniesPane(BasePane):
    BINDINGS = [
        Binding("a", "add", "追加"), Binding("e", "edit", "編集"), Binding("c", "contract", "契約済みに"),
        Binding("s", "status", "ステータス変更"), Binding("delete", "delete", "削除"),
        Binding("i", "import_csv", "CSV取込"), Binding("x", "export_csv", "CSV出力"),
        Binding("slash", "focus_search", "検索", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(classes="bar"):
            yield Input(placeholder="検索（Enterで実行）", id="search", compact=True)
            yield Select(COMPANY_FILTERS, value="active", allow_blank=False, id="filter", compact=True)
            yield Select([(p, p) for p in PREFECTURES], prompt="都道府県: すべて", id="pref", compact=True)
            yield Static("", id="count", markup=False)
        with Horizontal(classes="bar tight"):
            yield Button("追加(a)", id="add", compact=True)
            yield Button("編集(e)", id="edit", compact=True)
            yield Button("削除(Del)", id="delete", compact=True)
            yield Button("契約済みにする＝除外(c)", id="contract", variant="warning", compact=True)
            yield Button("ステータス変更(s)", id="status", compact=True)
            yield Button("CSV取込(i)", id="import", compact=True)
            yield Button("CSV出力(x)", id="export", compact=True)
        yield MarkTable(COMPANY_COLUMNS, id="table")
        yield Static("Space: チェック　Ctrl+A: 全チェック　Enter: 編集　※ 操作はチェックした企業（無ければカーソル行）が対象。"
                     "契約済み・配信停止は既定の表示とすべての送信対象から除外されます。", classes="help", markup=False)

    def on_mount(self) -> None:
        self.reload()

    def on_show(self) -> None:
        self.reload()

    @property
    def table(self) -> MarkTable:
        return self.query_one("#table", MarkTable)

    def reload(self) -> None:
        pref = self.query_one("#pref", Select).value
        rows = self.db.list_companies(
            status_filter=self.query_one("#filter", Select).value,
            prefectures=None if pref is Select.NULL else [pref],
            search=self.query_one("#search", Input).value,
        )
        self.table.set_rows(rows, company_values, style=company_style)
        self._update_count()

    def _update_count(self) -> None:
        marked = len(self.table.marked)
        self.query_one("#count", Static).update(
            f"{self.table.row_count} 件" + (f"（チェック {marked} 件）" if marked else ""))

    def on_mark_table_marks_changed(self, _event: MarkTable.MarksChanged) -> None:
        self._update_count()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self.reload()
            self.table.focus()

    def on_select_changed(self, _event: Select.Changed) -> None:
        if self.is_mounted:
            self.reload()

    def on_data_table_row_selected(self, _event: DataTable.RowSelected) -> None:
        self.action_edit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {"add": self.action_add, "edit": self.action_edit, "delete": self.action_delete,
                   "contract": self.action_contract, "status": self.action_status,
                   "import": self.action_import_csv, "export": self.action_export_csv}
        if event.button.id in actions:
            actions[event.button.id]()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_reload(self) -> None:
        self.reload()

    @work
    async def action_add(self) -> None:
        data = await self.app.push_screen_wait(CompanyForm())
        if not data:
            return
        dup = self.db.find_duplicate(data["name"], data["email"], data["website"], "", data["prefecture"])
        if dup and not await self.app.push_screen_wait(ConfirmDialog(
                f"「{dup['name']}」（{STATUS_LABELS.get(dup['status'])}）と重複している可能性があります。\n"
                "それでも追加しますか？", "重複の可能性")):
            return
        data["source"] = "manual"
        self.db.add_company(data)
        self.app.data_changed()
        self.notify(f"「{data['name']}」を追加しました", markup=False)

    @work
    async def action_edit(self) -> None:
        row = self.table.current()
        if not row:
            return
        company = self.db.get_company(row["id"])
        data = await self.app.push_screen_wait(CompanyForm(company))
        if not data:
            return
        self.db.update_company(row["id"], data)
        self.app.data_changed()
        self.notify("保存しました")

    @work
    async def action_delete(self) -> None:
        rows = self.table.marked_or_current()
        if not rows:
            return
        if not await self.app.push_screen_wait(ConfirmDialog(
                f"{len(rows)} 件の企業を削除しますか？\n\n※ 既存顧客をリストから外したい場合は、削除ではなく"
                "「契約済みにする」を使うと、再調査しても重複登録・誤送信されません。", "削除")):
            return
        self.db.delete_companies([r["id"] for r in rows])
        self.table.marked.clear()
        self.app.data_changed()

    async def _change_status(self, status: str) -> None:
        rows = self.table.marked_or_current()
        if not rows:
            return
        names = "、".join(r["name"] for r in rows[:5]) + (" ほか" if len(rows) > 5 else "")
        message = f"{len(rows)} 件（{names}）を「{STATUS_LABELS[status]}」にしますか？"
        if status == STATUS_CONTRACTED:
            message += "\n\n契約済みの企業は一覧の既定表示と、新規・フォローすべての送信対象から除外されます。"
        if not await self.app.push_screen_wait(ConfirmDialog(message, "ステータス変更")):
            return
        self.db.set_status([r["id"] for r in rows], status)
        self.table.marked.clear()
        self.app.data_changed()
        self.notify(f"{len(rows)} 件を「{STATUS_LABELS[status]}」にしました")

    @work
    async def action_contract(self) -> None:
        await self._change_status(STATUS_CONTRACTED)

    @work
    async def action_status(self) -> None:
        choice = await self.app.push_screen_wait(ChoiceDialog(
            "ステータスを選んでください", [(f"{v}にする", k) for k, v in STATUS_LABELS.items()]))
        if choice:
            await self._change_status(choice)

    @work
    async def action_import_csv(self) -> None:
        result = await self.app.push_screen_wait(ImportDialog())
        if not result:
            return
        path, status = clean_path(result[0]), result[1]
        try:
            rows, recognized = read_companies_csv(path)
        except (OSError, ValueError) as e:
            await self.app.push_screen_wait(MessageDialog(str(e), "CSV取り込みエラー"))
            return
        for row in rows:
            row.setdefault("source", "csv")
        res = self.db.import_rows(rows, status=status)
        self.app.data_changed()
        await self.app.push_screen_wait(MessageDialog(
            f"認識した列: {'、'.join(recognized)}\n\n追加: {res.added} 件\n既存企業のステータス更新: {res.updated} 件\n"
            f"スキップ（重複・会社名なし）: {res.skipped} 件", "CSV取り込み"))

    @work
    async def action_export_csv(self) -> None:
        default = desktop_dir() / f"企業リスト_{datetime.now():%Y%m%d}.csv"
        path = await self.app.push_screen_wait(InputDialog("書き出し先のファイル", str(default), ok="書き出す",
                                                          hint="現在の表示（絞り込み結果）を書き出します。"))
        if not path:
            return
        rows = list(self.table.data.values())
        try:
            write_companies_csv(clean_path(path), rows)
        except OSError as e:
            self.notify(f"書き出せませんでした: {e}", severity="error", markup=False)
            return
        self.notify(f"{len(rows)} 件を書き出しました: {clean_path(path)}", markup=False, timeout=8)


# ======================================================================= 新規開拓
RESEARCH_COLUMNS = [("judge", "判定"), ("name", "会社名"), ("email", "メールアドレス"), ("prefecture", "都道府県"),
                    ("city", "市区町村"), ("industry", "業種"), ("phone", "電話番号"), ("website", "Webサイト")]


def prospect_values(p: Prospect) -> list:
    return [judge_label(p), p.name, p.email, p.prefecture, p.city, p.industry, p.phone, p.website]


def prospect_style(p: Prospect) -> str:
    if p.existing_status == ADDED:
        return "ok"
    if p.existing_status:
        return "muted"
    return "" if p.email else "warn"


class ResearchPane(BasePane):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.prospects: list[Prospect] = []
        self.stop_event = threading.Event()

    def compose(self) -> ComposeResult:
        with Horizontal(classes="pane"):
            with Vertical(classes="left"):
                yield Label("調査地域（Space/クリックで選択）", classes="label")
                yield PrefPicker(id="prefs")
                yield Label("市区町村（任意・カンマ区切り）", classes="label")
                yield Input(id="cities", placeholder="例: 仙台市, 名取市", compact=True)
                yield Label("業種・キーワード（カンマ区切り）", classes="label")
                yield Input(id="keywords", placeholder="例: 製造業, 建設会社", compact=True)
                yield Label("調査方法", classes="label")
                yield Select([(v, k) for k, v in METHOD_LABELS.items()], value=METHOD_GOOGLE, allow_blank=False,
                             id="method", compact=True)
                with Horizontal(classes="row"):
                    yield Label("1検索の最大件数 ")
                    yield Input("20", type="integer", id="max", compact=True, classes="num")
                yield Checkbox("公式サイトからメール取得", True, id="crawl", compact=True)
                yield Checkbox("選択地域外の結果を除外", True, id="restrict", compact=True)
                with Horizontal(classes="row"):
                    yield Button("▶ 調査開始", id="start", variant="primary", compact=True)
                    yield Button("停止", id="stop", disabled=True, compact=True)
            with Vertical(classes="right"):
                yield Static("調査結果: まだありません（登録済み＝送付済み・契約済みなどの企業は自動で対象外）",
                             id="summary", markup=False)
                yield MarkTable(RESEARCH_COLUMNS, id="table")
                with Horizontal(classes="bar"):
                    yield Button("新規をすべてチェック", id="mark-new", compact=True)
                    yield Checkbox("メール未取得も追加", id="include", compact=True)
                    yield Button("チェックした企業をリストに追加", id="add", variant="primary", compact=True)
                yield RichLog(id="log", classes="log", wrap=True)

    @property
    def table(self) -> MarkTable:
        return self.query_one("#table", MarkTable)

    def render_results(self) -> None:
        self.table.set_rows(self.prospects, prospect_values, key=lambda p: str(self.prospects.index(p)),
                            style=prospect_style)
        self.update_summary()

    def update_summary(self) -> None:
        if not self.prospects:
            return
        new = [p for p in self.prospects if not p.existing_status]
        with_mail = sum(1 for p in new if p.email)
        self.query_one("#summary", Static).update(
            f"調査結果 {len(self.prospects)} 件（新規 {len(new)} 件／うちメール取得 {with_mail} 件、"
            f"登録済みのため対象外 {len(self.prospects) - len(new)} 件）　チェック {len(self.table.marked)} 件")

    def on_mark_table_marks_changed(self, _event) -> None:
        self.update_summary()

    def write_log(self, text: str) -> None:
        self.query_one("#log", RichLog).write(text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "start":
            self.start()
        elif bid == "stop":
            self.stop_event.set()
            self.write_log("停止しています…")
        elif bid == "mark-new":
            include = self.query_one("#include", Checkbox).value
            self.table.set_marks(str(i) for i, p in enumerate(self.prospects)
                                 if not p.existing_status and (p.email or include))
        elif bid == "add":
            self.add_marked()

    @work
    async def start(self) -> None:
        if self.busy:
            return
        prefs = self.query_one("#prefs", PrefPicker).prefectures()
        cities = split_list(self.query_one("#cities", Input).value)
        keywords = split_list(self.query_one("#keywords", Input).value)
        method = self.query_one("#method", Select).value
        if not prefs and not cities:
            self.notify("調査する都道府県を選ぶか、市区町村を入力してください", severity="warning")
            return
        if not keywords:
            self.notify("業種・キーワードを入力してください（例: 製造業）", severity="warning")
            return
        if not is_demo():  # テスト環境は API を使わずサンプル結果を表示する
            if method == METHOD_GOOGLE and not self.settings.google_api_key:
                self.notify("設定タブ（F7）で Google Places API キーを入力してください", severity="warning")
                return
            if method == METHOD_CLAUDE and not self.need_ai_key():
                return
        searches = len(keywords) * max(1, len(cities) or len(prefs))
        if searches > 20 and not is_demo() and not await self.app.push_screen_wait(ConfirmDialog(
                f"{searches} 回の検索を行います（API利用料がかかります）。続けますか？")):
            return
        try:
            max_per_query = max(1, int(self.query_one("#max", Input).value or 20))
        except ValueError:
            max_per_query = 20
        crawl = self.query_one("#crawl", Checkbox).value
        restrict = self.query_one("#restrict", Checkbox).value
        self.busy = True
        self.stop_event.clear()
        self.prospects = []
        self.render_results()
        self.query_one("#log", RichLog).clear()
        self.query_one("#start", Button).disabled = True
        self.query_one("#stop", Button).disabled = False

        def progress(text: str) -> None:
            self.app.call_from_thread(self.write_log, text)

        def show(prospects: list[Prospect]) -> None:
            self.prospects = prospects
            self.render_results()

        def updated(p: Prospect) -> None:
            def ui() -> None:
                self.table.redraw_row(str(self.prospects.index(p)))
                self.update_summary()
            self.app.call_from_thread(ui)

        def work_fn():
            return run_research(self.db, self.settings, method, keywords, prefs, cities, max_per_query, restrict,
                                crawl, progress, self.stop_event,
                                on_results=lambda ps: self.app.call_from_thread(show, ps), on_update=updated)

        def finished(_result=None) -> None:
            self.busy = False
            self.query_one("#start", Button).disabled = False
            self.query_one("#stop", Button).disabled = True
            self.render_results()

        def failed(e: Exception) -> None:
            finished()
            self.write_log(f"エラー: {e}")
            self.app.push_screen(MessageDialog(str(e), "調査エラー"))

        self.run_bg(work_fn, finished, failed)

    def add_marked(self) -> None:
        rows = self.table.marked_rows()
        if not rows:
            self.notify("リストに追加する企業をチェック（Space）してください", severity="warning")
            return
        result = add_prospects(self.db, rows, self.query_one("#include", Checkbox).value)
        self.table.marked.clear()
        self.render_results()
        self.app.data_changed()
        self.notify(result.text(), timeout=8)


# ======================================================================= 送信（共通）
class BaseSendPane(BasePane):
    kind = KIND_NEW
    kind_label = "新規"
    columns: list[tuple[str, str]] = []

    def __init__(self, **kw):
        super().__init__(**kw)
        self.stop_event = threading.Event()
        self.templates: list[dict] = []

    def compose(self) -> ComposeResult:
        with Horizontal(classes="pane"):
            with Vertical(classes="left"):
                yield from self.compose_conditions()
            with Vertical(classes="right"):
                yield Static("左の条件で「対象を抽出」を押してください", id="count", markup=False)
                yield MarkTable(self.columns, id="table")
                yield TextArea("", read_only=True, id="preview", classes="preview")
                with Horizontal(classes="bar"):
                    yield Select([], prompt="テンプレート", id="template", compact=True)
                    yield Checkbox("AI個別化", id="ai", compact=True)
                    yield from self.compose_extra_options()
                    yield Checkbox("テストモード", id="dry", compact=True, tooltip="実際には送信せず履歴に記録だけします")
                with Horizontal(classes="bar tight"):
                    yield Button(f"▶ {self.kind_label}メールを送信", id="send", variant="primary", compact=True)
                    yield Button("停止", id="stop", disabled=True, compact=True)
                    yield Button("自分宛テスト", id="test", compact=True)
                    yield Button("AIプレビュー", id="ai-preview", compact=True)
                    yield ProgressBar(id="progress", show_eta=False)
                yield RichLog(id="log", classes="log small", wrap=True)

    def compose_conditions(self) -> ComposeResult:
        raise NotImplementedError

    def compose_extra_options(self) -> ComposeResult:
        return iter(())

    def fetch_targets(self) -> list[dict]:
        raise NotImplementedError

    def row_values(self, c: dict) -> list:
        raise NotImplementedError

    def options(self) -> SendOptions:
        s = self.settings
        return SendOptions(kind=self.kind, template=self.current_template() or {},
                           dry_run=is_demo() or self.query_one("#dry", Checkbox).value,
                           use_ai=self.query_one("#ai", Checkbox).value,
                           interval_sec=s.send_interval_sec, daily_limit=s.daily_limit)

    @property
    def table(self) -> MarkTable:
        return self.query_one("#table", MarkTable)

    def on_mount(self) -> None:
        self.load_templates()
        if is_demo():  # テスト環境では常にテストモード（送信しない）
            dry = self.query_one("#dry", Checkbox)
            dry.value = True
            dry.disabled = True

    def on_show(self) -> None:
        self.load_templates()

    def load_templates(self) -> None:
        select = self.query_one("#template", Select)
        current = select.value
        self.templates = self.db.list_templates(self.kind)
        with self.prevent(Select.Changed):
            select.set_options([(t["name"], t["id"]) for t in self.templates])
            ids = [t["id"] for t in self.templates]
            if current in ids:
                select.value = current
            elif ids:
                select.value = ids[0]

    def current_template(self) -> dict | None:
        value = self.query_one("#template", Select).value
        return next((t for t in self.templates if t["id"] == value), None)

    def write_log(self, text: str) -> None:
        self.query_one("#log", RichLog).write(text)

    def extract(self) -> None:
        targets = self.fetch_targets()
        self.table.set_rows(targets, self.row_values, mark_all=True)
        self.update_count()
        self.update_preview()
        if self.table.row_count:
            self.table.focus()

    def update_count(self) -> None:
        remaining = max(0, self.settings.daily_limit - self.db.count_sent_today())
        self.query_one("#count", Static).update(
            f"送信対象 {self.table.row_count} 社（チェック {len(self.table.marked)} 社）　"
            f"本日の残り送信可能数 {remaining} 通")

    def on_mark_table_marks_changed(self, _event) -> None:
        self.update_count()

    def on_data_table_row_highlighted(self, _event: DataTable.RowHighlighted) -> None:
        self.update_preview()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "template":
            self.update_preview()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id in ("ai", "thread"):
            self.update_preview()

    def update_preview(self) -> None:
        row = self.table.current()
        template = self.current_template()
        preview = self.query_one("#preview", TextArea)
        if not row or not template:
            preview.load_text("")
            return
        opts = self.options()
        opts.use_ai = False
        subject, body = prepare_mail(row, self.settings, opts)
        note = "※ AI個別化は送信時に企業ごとに適用されます（「AIプレビュー」で確認できます）\n" if \
            self.query_one("#ai", Checkbox).value else ""
        preview.load_text(f"{note}件名: {subject}\n{'─' * 40}\n{body}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "send":
            self.send()
        elif bid == "stop":
            self.stop_event.set()
            self.write_log("停止しています…（送信中の1通が終わると止まります）")
        elif bid == "test":
            self.test_send()
        elif bid == "ai-preview":
            self.ai_preview()
        elif bid == "extract":
            self.extract()
        else:
            self.on_other_button(bid)

    def on_other_button(self, bid: str | None) -> None:
        pass

    def ai_preview(self) -> None:
        row = self.table.current()
        if not row or not self.current_template() or not self.need_ai_key():
            return
        opts = self.options()
        opts.use_ai = True
        preview = self.query_one("#preview", TextArea)
        preview.load_text("AIで文面を作成しています…")
        settings = self.settings

        def done(result) -> None:
            preview.load_text(f"件名: {result[0]}\n{'─' * 40}\n{result[1]}")

        self.run_bg(lambda: prepare_mail(row, settings, opts), done)

    def test_send(self) -> None:
        template = self.current_template()
        settings = self.settings
        if not template:
            return
        if is_demo():
            self.notify("テスト環境では実際のメールは送信しません。本番の画面で「自分宛テスト」をお使いください。",
                        severity="warning", timeout=8)
            return
        if not settings.smtp_user:
            self.notify("設定タブ（F7）で SMTP（送信）設定を入力してください", severity="warning")
            return
        opts = self.options()
        if opts.use_ai and not self.need_ai_key():
            return
        company = self.table.current() or {"name": "（テスト株式会社）", "follow_count": 0}
        self.write_log("テストメールを送信しています…")
        self.run_bg(
            lambda: send_test_mail(settings, template, company, use_ai=opts.use_ai, thread_reply=opts.thread_reply,
                                   kind=self.kind),
            lambda to: (self.write_log(f"{to} にテストメールを送信しました"), self.notify(f"{to} に送信しました")),
        )

    @work
    async def send(self) -> None:
        if self.busy:
            return
        rows = self.table.marked_rows()
        template = self.current_template()
        settings = self.settings
        if not rows:
            self.notify("送信する企業をチェック（Space）してください", severity="warning")
            return
        if not template:
            self.notify("テンプレートを選択してください", severity="warning")
            return
        opts = self.options()
        if opts.use_ai and not self.need_ai_key():
            return
        if not opts.dry_run and not settings.smtp_user:
            self.notify("設定タブ（F7）で SMTP（送信）設定を入力してください", severity="warning")
            return
        if missing_sender_info(settings) and not await self.app.push_screen_wait(ConfirmDialog(
                "設定の「会社名」「送信者名」が未入力です。\n特定電子メール法で必要な送信者の表示が不足します。"
                "このまま送信しますか？", "送信者情報")):
            return
        remaining = max(0, settings.daily_limit - self.db.count_sent_today())
        message = send_confirmation(self.kind_label, len(rows), template["name"], opts.use_ai, opts.dry_run,
                                    settings, remaining)
        if not await self.app.push_screen_wait(ConfirmDialog(message + "\n\nよろしいですか？", "送信の確認",
                                                             ok="送信する", cancel="やめる")):
            return

        self.busy = True
        self.stop_event.clear()
        self.query_one("#send", Button).disabled = True
        self.query_one("#stop", Button).disabled = False
        bar = self.query_one("#progress", ProgressBar)
        bar.update(total=len(rows), progress=0)
        self.query_one("#log", RichLog).clear()

        def progress(index: int, total: int, text: str) -> None:
            def ui() -> None:
                bar.update(progress=index)
                self.write_log(f"[{index}/{total}] {text}")
                self.app.refresh_stats()
            self.app.call_from_thread(ui)

        def done(report) -> None:
            self.busy = False
            self.query_one("#send", Button).disabled = False
            self.query_one("#stop", Button).disabled = True
            lines = [f"送信: {report.sent} 件", f"失敗: {report.failed} 件",
                     f"スキップ（対象外になっていた企業）: {report.skipped} 件"]
            if report.stopped:
                lines.append("※ 途中で停止しました")
            if report.aborted_reason:
                lines.append(f"※ {report.aborted_reason}")
            if report.errors:
                lines += ["", "エラー内容:"] + report.errors[:10]
            self.write_log(" / ".join(lines[:3]))
            self.app.data_changed()
            self.extract()
            self.app.push_screen(MessageDialog("\n".join(lines), "送信結果"))

        def failed(e: Exception) -> None:
            self.busy = False
            self.query_one("#send", Button).disabled = False
            self.query_one("#stop", Button).disabled = True
            self.app.push_screen(MessageDialog(str(e), "送信エラー"))

        self.run_bg(lambda: run_send_job(self.db, settings, rows, opts, self.stop_event, progress), done, failed)


class NewMailPane(BaseSendPane):
    kind = KIND_NEW
    kind_label = "新規"
    columns = [("name", "会社名"), ("email", "メールアドレス"), ("prefecture", "都道府県"), ("city", "市区町村"),
               ("industry", "業種"), ("contact", "担当者")]

    def compose_conditions(self) -> ComposeResult:
        yield Label("対象地域（未選択＝すべて）", classes="label")
        yield PrefPicker(id="prefs")
        yield Label("業種・キーワードで絞り込み（任意）", classes="label")
        yield Input(id="keywords", placeholder="例: 製造業", compact=True)
        yield Button("対象を抽出", id="extract", variant="primary", compact=True, classes="wide")
        yield Static("自動で除外：送付済み・返信あり・契約済み・配信停止・送信エラー、過去に送ったアドレスや同じ会社ドメイン、"
                     "メール未登録の企業", classes="help", markup=False)

    def fetch_targets(self) -> list[dict]:
        return self.db.new_targets(self.query_one("#prefs", PrefPicker).prefectures(),
                                   split_list(self.query_one("#keywords", Input).value))

    def row_values(self, c: dict) -> list:
        return [c["name"], c["email"], c["prefecture"], c["city"], c["industry"], c["contact_name"]]


FOLLOW_COUNT_FILTER = [("すべて", -1), ("0回（初回フォロー）", 0), ("1回済み", 1), ("2回済み", 2), ("3回済み", 3)]


class FollowMailPane(BaseSendPane):
    kind = KIND_FOLLOW
    kind_label = "フォロー"
    columns = [("name", "会社名"), ("email", "メールアドレス"), ("first", "初回送信"), ("last", "最終送信"),
               ("days", "経過日数"), ("follow", "フォロー回数"), ("subject", "前回の件名")]

    def compose_conditions(self) -> ComposeResult:
        s = self.settings
        with Horizontal(classes="row tight"):
            yield Label("前回送信から ")
            yield Input(str(s.follow_after_days), type="integer", id="days", compact=True, classes="num")
            yield Label(" 日以上")
        with Horizontal(classes="row tight"):
            yield Label("フォロー上限 ")
            yield Input(str(s.max_follow_count), type="integer", id="max", compact=True, classes="num")
            yield Label(" 回まで")
        with Horizontal(classes="row tight"):
            yield Label("対象 ")
            yield Select(FOLLOW_COUNT_FILTER, value=-1, allow_blank=False, id="count-filter", compact=True)
        yield Label("対象地域（未選択＝すべて）", classes="label")
        yield PrefPicker(id="prefs", classes="short")
        yield Button("対象を抽出", id="extract", variant="primary", compact=True, classes="wide")
        yield Static("返信あり・契約済み・配信停止・送信エラーは自動で除外", classes="help", markup=False)
        yield Label("返信チェック（受信トレイ）", classes="label")
        with Horizontal(classes="row tight"):
            yield Label("過去 ")
            yield Input("30", type="integer", id="inbox-days", compact=True, classes="num")
            yield Label(" 日分")
        yield Button("受信トレイを確認（IMAP）", id="inbox", compact=True, classes="wide")

    def compose_extra_options(self) -> ComposeResult:
        yield Checkbox("Re:で返信", True, id="thread", compact=True, tooltip="前回メールへの返信としてスレッド化します")

    def _int(self, selector: str, default: int) -> int:
        try:
            return int(self.query_one(selector, Input).value)
        except ValueError:
            return default

    def options(self) -> SendOptions:
        opts = super().options()
        opts.thread_reply = self.query_one("#thread", Checkbox).value
        opts.max_follow = self._int("#max", self.settings.max_follow_count)
        return opts

    def fetch_targets(self) -> list[dict]:
        count = self.query_one("#count-filter", Select).value
        count = None if count == -1 else count
        targets = self.db.follow_targets(self._int("#days", self.settings.follow_after_days),
                                         self._int("#max", self.settings.max_follow_count),
                                         self.query_one("#prefs", PrefPicker).prefectures(), count)
        if count is not None and count < len(self.templates):  # フォロー回数に合ったテンプレートを自動選択
            self.query_one("#template", Select).value = self.templates[count]["id"]
        return targets

    def row_values(self, c: dict) -> list:
        return [c["name"], c["email"], format_date_jp(c["first_sent_at"]), format_date_jp(c["last_sent_at"]),
                days_since(c["last_sent_at"]), c["follow_count"], c["last_subject"]]

    def on_other_button(self, bid: str | None) -> None:
        if bid == "inbox":
            self.check_inbox()

    def check_inbox(self) -> None:
        settings = self.settings
        if is_demo():
            from ..demo import simulate_inbox

            result = simulate_inbox(self.db)
            self.app.data_changed()
            if self.table.row_count:
                self.extract()
            names = "、".join(result.replied) or "（送付済みの企業がありません）"
            self.app.push_screen(MessageDialog(
                "テスト環境のため、受信トレイの代わりに例として次の企業を「返信あり」にしました。\n"
                f"{names}\n\n返信があった企業はフォローメールの対象から自動で外れます。", "返信チェック（テスト環境）"))
            return
        if not settings.effective_imap_user:
            self.notify("設定タブ（F7）で IMAP（受信）設定を入力してください", severity="warning")
            return
        days = self._int("#inbox-days", 30)
        self.write_log("受信トレイを確認しています…")

        def work_fn():
            from ..replies import check_replies

            return check_replies(settings, self.db, days)

        def done(result) -> None:
            lines = [f"確認したメール: {result.scanned} 件",
                     f"返信あり: {len(result.replied)} 件 {'、'.join(result.replied[:10])}",
                     f"配信停止: {len(result.opted_out)} 件 {'、'.join(result.opted_out[:10])}",
                     f"不達（送信エラー）: {len(result.bounced)} 件 {'、'.join(result.bounced[:10])}"]
            self.write_log(" / ".join(lines))
            self.app.data_changed()
            if self.table.row_count:
                self.extract()
            self.app.push_screen(MessageDialog("\n".join(lines), "返信チェック"))

        self.run_bg(work_fn, done)


# ======================================================================= テンプレート
KIND_LABELS = {KIND_NEW: "新規メール", KIND_FOLLOW: "フォローメール"}


class TemplatesPane(BasePane):
    BINDINGS = [Binding("ctrl+s", "save", "保存")]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.current_id: int | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="pane"):
            with Vertical(classes="left"):
                yield Label("テンプレート一覧", classes="label")
                yield MarkTable([("name", "テンプレート名"), ("kind", "種類")], markable=False, id="list")
                with Horizontal(classes="row"):
                    yield Button("新規", id="new", compact=True)
                    yield Button("複製", id="copy", compact=True)
                    yield Button("削除", id="delete", compact=True)
            with Vertical(classes="right"):
                with Grid(classes="form"):
                    yield Label("テンプレート名")
                    yield Input(id="name", compact=True)
                    yield Label("種類")
                    yield Select([(v, k) for k, v in KIND_LABELS.items()], value=KIND_NEW, allow_blank=False,
                                 id="kind", compact=True)
                    yield Label("件名")
                    yield Input(id="subject", compact=True)
                yield Label("本文", classes="label")
                yield TextArea(id="body", classes="body")
                with Horizontal(classes="bar"):
                    yield Select([(f"{{{k}}}  {v}", k) for k, v in PLACEHOLDERS.items()],
                                 prompt="差し込み項目を挿入", id="placeholder", compact=True)
                    yield Button("署名を確認", id="signature", compact=True)
                    yield Button("保存 (Ctrl+S)", id="save", variant="primary", compact=True)
                yield Static("署名と配信停止の案内（特定電子メール法の表示）は、設定タブの送信者情報から自動で末尾に付きます。",
                             classes="help", markup=False)

    def on_mount(self) -> None:
        self.reload()

    def on_show(self) -> None:
        self.reload(keep=self.current_id)

    def reload(self, keep: int | None = None) -> None:
        table = self.query_one("#list", MarkTable)
        templates = self.db.list_templates()
        table.set_rows(templates, lambda t: [t["name"], KIND_LABELS.get(t["kind"], t["kind"])])
        target = keep if keep is not None else (templates[0]["id"] if templates else None)
        if target is not None and str(target) in table.data:
            table.move_cursor(row=table.get_row_index(str(target)))
            self.load(target)

    def load(self, template_id: int) -> None:
        t = self.db.get_template(template_id)
        if not t:
            return
        self.current_id = t["id"]
        self.query_one("#name", Input).value = t["name"]
        self.query_one("#kind", Select).value = t["kind"]
        self.query_one("#subject", Input).value = t["subject"]
        self.query_one("#body", TextArea).load_text(t["body"])

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key and event.row_key.value:
            self.load(int(event.row_key.value))

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "placeholder" and event.value is not Select.NULL:
            body = self.query_one("#body", TextArea)
            body.insert(f"{{{event.value}}}")
            event.select.clear()
            body.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "new":
            self.current_id = None
            self.query_one("#name", Input).value = "新しいテンプレート"
            self.query_one("#subject", Input).value = ""
            self.query_one("#body", TextArea).load_text("{会社名}\n{担当者名}様\n\n")
            self.query_one("#name", Input).focus()
        elif bid == "copy" and self.current_id:
            self.current_id = None
            self.query_one("#name", Input).value += "（コピー）"
            self.action_save()
        elif bid == "delete":
            self.delete()
        elif bid == "save":
            self.action_save()
        elif bid == "signature":
            self.app.push_screen(MessageDialog(signature(self.settings).strip() or "（未設定）", "自動で付く署名"))

    def action_save(self) -> None:
        try:
            self.current_id = self.db.save_template(
                self.current_id, self.query_one("#name", Input).value.strip(), self.query_one("#kind", Select).value,
                self.query_one("#subject", Input).value, self.query_one("#body", TextArea).text.rstrip())
        except ValueError as e:
            self.notify(str(e), severity="warning")
            return
        self.reload(keep=self.current_id)
        self.notify("テンプレートを保存しました")

    @work
    async def delete(self) -> None:
        if not self.current_id:
            return
        name = self.query_one("#name", Input).value
        if not await self.app.push_screen_wait(ConfirmDialog(f"「{name}」を削除しますか？", "削除")):
            return
        self.db.delete_template(self.current_id)
        self.current_id = None
        self.reload()


# ======================================================================= 送信履歴
HISTORY_KIND = {KIND_NEW: "新規", KIND_FOLLOW: "フォロー", "test": "テスト"}
HISTORY_RESULT = {RESULT_SENT: "送信済み", RESULT_FAILED: "失敗", RESULT_DRY_RUN: "テスト（未送信）"}


def history_kind(r: dict) -> str:
    label = HISTORY_KIND.get(r["kind"], r["kind"])
    return f"{label}{r['step']}回目" if r["kind"] == KIND_FOLLOW and r["step"] else label


class HistoryPane(BasePane):
    def compose(self) -> ComposeResult:
        with Horizontal(classes="bar"):
            yield Select([("新規", KIND_NEW), ("フォロー", KIND_FOLLOW)], prompt="種別: すべて", id="kind",
                         compact=True)
            yield Select([(v, k) for k, v in HISTORY_RESULT.items()], prompt="結果: すべて", id="result",
                         compact=True)
            yield Button("更新", id="reload", compact=True)
            yield Button("CSV出力", id="export", compact=True)
            yield Static("", id="count", markup=False)
        yield MarkTable([("sent_at", "日時"), ("kind", "種別"), ("company", "会社名"), ("email", "宛先"),
                         ("subject", "件名"), ("result", "結果"), ("error", "エラー")], markable=False, id="table")
        yield TextArea("", read_only=True, id="detail", classes="detail")

    def on_mount(self) -> None:
        self.reload()

    def on_show(self) -> None:
        self.reload()

    def reload(self) -> None:
        kind = self.query_one("#kind", Select).value
        result = self.query_one("#result", Select).value
        rows = self.db.list_send_log(None if kind is Select.NULL else kind,
                                     None if result is Select.NULL else result)
        self.query_one("#table", MarkTable).set_rows(
            rows,
            lambda r: [r["sent_at"], history_kind(r), r["company_name"], r["email"], r["subject"],
                       HISTORY_RESULT.get(r["result"], r["result"]), r["error"]],
            style=lambda r: "warn" if r["result"] == RESULT_FAILED else ("muted" if r["result"] == RESULT_DRY_RUN
                                                                         else ""),
        )
        self.query_one("#count", Static).update(f"{len(rows)} 件")

    def on_select_changed(self, _event: Select.Changed) -> None:
        if self.is_mounted:
            self.reload()

    def on_data_table_row_highlighted(self, _event: DataTable.RowHighlighted) -> None:
        r = self.query_one("#table", MarkTable).current()
        self.query_one("#detail", TextArea).load_text(
            f"件名: {r['subject']}\n宛先: {r['email']}\n{'─' * 40}\n{r['body']}" if r else "")

    @work
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "reload":
            self.reload()
            return
        default = desktop_dir() / f"送信履歴_{datetime.now():%Y%m%d}.csv"
        path = await self.app.push_screen_wait(InputDialog("書き出し先のファイル", str(default), ok="書き出す"))
        if not path:
            return
        rows = list(self.query_one("#table", MarkTable).data.values())
        write_rows_csv(clean_path(path), ["日時", "種別", "会社名", "宛先", "件名", "結果", "エラー"],
                       [[r["sent_at"], history_kind(r), r["company_name"], r["email"], r["subject"],
                         HISTORY_RESULT.get(r["result"], r["result"]), r["error"]] for r in rows])
        self.notify(f"{len(rows)} 件を書き出しました: {clean_path(path)}", markup=False, timeout=8)


# ======================================================================= 設定
SETTINGS_SECTIONS: list[tuple[str, list[tuple]]] = [
    ("メール送信（SMTP）", [
        ("smtp_host", "SMTPサーバー", "text", "smtp.gmail.com"),
        ("smtp_port", "ポート", "int", "587"),
        ("smtp_security", "暗号化", "select", [("STARTTLS", "starttls"), ("SSL", "ssl"), ("なし", "none")]),
        ("smtp_user", "ユーザー名", "text", "通常はメールアドレス"),
        ("smtp_password", "パスワード", "password", "Gmailはアプリパスワード"),
    ]),
    ("返信チェック（IMAP 受信）", [
        ("imap_host", "IMAPサーバー", "text", "imap.gmail.com"),
        ("imap_port", "ポート", "int", "993"),
        ("imap_user", "ユーザー名", "text", "空欄ならSMTPと同じ"),
        ("imap_password", "パスワード", "password", "空欄ならSMTPと同じ"),
    ]),
    ("送信ルール", [
        ("send_interval_sec", "送信間隔（秒）", "int", "30秒以上推奨"),
        ("daily_limit", "1日の上限（通）", "int", "Gmail無料版は500通/日"),
        ("follow_after_days", "フォローまで（日）", "int", "前回送信からの日数"),
        ("max_follow_count", "フォロー上限（回）", "int", ""),
    ]),
    ("送信者情報（署名・特定電子メール法の表示）", [
        ("from_name", "送信者名", "text", "例: 山田 太郎"),
        ("sender_company", "会社名", "text", ""),
        ("from_email", "送信元アドレス", "text", "空欄ならSMTPユーザー名"),
        ("reply_to", "返信先(Reply-To)", "text", "任意"),
        ("sender_address", "住所", "text", ""),
        ("sender_phone", "電話番号", "text", ""),
        ("sender_url", "WebサイトURL", "text", ""),
    ]),
    ("企業調査・AI", [
        ("google_api_key", "Google Places", "password", "APIキー（地域調査で使用）"),
        ("anthropic_api_key", "Anthropic", "password", "APIキー（AI個別化・AI調査で使用）"),
        ("ai_model", "AIモデル", "select", [("claude-opus-5-5", "claude-opus-5-5"),
                                         ("claude-sonnet-5-5", "claude-sonnet-5-5"),
                                         ("claude-haiku-5-5", "claude-haiku-5-5")]),
        ("crawl_max_pages", "巡回ページ数", "int", "1社あたり"),
        ("crawl_timeout_sec", "タイムアウト(秒)", "int", ""),
    ]),
]


class SettingsPane(BasePane):
    BINDINGS = [Binding("ctrl+s", "save", "保存")]

    def compose(self) -> ComposeResult:
        with Horizontal(classes="bar tight"):
            yield Button("設定を保存 (Ctrl+S)", id="save", variant="primary", compact=True)
            yield Button("SMTP接続テスト", id="smtp", compact=True)
            yield Button("IMAP接続テスト", id="imap", compact=True)
            if is_demo():
                yield Button("テスト環境のアイコンを作成", id="shortcut", compact=True)
                yield Button("サンプルデータを初期状態に戻す", id="demo-reset", variant="warning", compact=True)
            else:
                yield Button("デスクトップにアイコンを作成", id="shortcut", compact=True)
                yield Button("テスト環境を開く", id="demo-open", variant="success", compact=True)
        with VerticalScroll(classes="settings-scroll"):
            with Horizontal(classes="settings-cols"):
                for column in (SETTINGS_SECTIONS[:3], SETTINGS_SECTIONS[3:]):
                    with Vertical(classes="settings-col"):
                        for title, items in column:
                            with Grid(classes="section") as grid:
                                grid.border_title = title
                                for name, label, kind, extra in items:
                                    yield Label(label)
                                    if kind == "select":
                                        yield Select(extra, allow_blank=False, id=f"s-{name}", compact=True)
                                    else:
                                        yield Input(id=f"s-{name}", placeholder=extra, password=kind == "password",
                                                    type="integer" if kind == "int" else "text", compact=True)
                        if title.startswith("企業調査"):
                            with Vertical(classes="section") as box:
                                box.border_title = "配信停止の案内文（メール末尾に自動で付きます）"
                                yield TextArea(id="s-optout", classes="optout")
            yield Static("Gmail: SMTP smtp.gmail.com / 587 / STARTTLS、IMAP imap.gmail.com / 993。Googleアカウントで"
                         "2段階認証を有効にし「アプリパスワード」を発行して入力してください。", classes="help", markup=False)
            yield Static(f"データ保存先: {data_dir()}（企業リスト・送信履歴・設定。パスワード類も含むため取扱いに注意）",
                         classes="help", markup=False)

    def on_mount(self) -> None:
        self.load()

    def load(self) -> None:
        s = self.settings
        for _title, items in SETTINGS_SECTIONS:
            for name, _label, kind, _extra in items:
                widget = self.query_one(f"#s-{name}")
                value = getattr(s, name)
                if kind == "select":
                    widget.value = value
                else:
                    widget.value = str(value)
        self.query_one("#s-optout", TextArea).load_text(s.optout_text)

    def collect(self) -> Settings:
        values: dict = {}
        types = {f.name: f.type for f in fields(Settings)}
        for _title, items in SETTINGS_SECTIONS:
            for name, label, kind, _extra in items:
                raw = self.query_one(f"#s-{name}").value
                if types[name] in ("int", int):
                    try:
                        values[name] = int(str(raw).strip())
                    except ValueError as e:
                        raise ValueError(f"「{label}」には数字を入力してください") from e
                else:
                    values[name] = str(raw).strip()
        values["optout_text"] = self.query_one("#s-optout", TextArea).text.strip()
        return replace(self.settings, **values)

    def action_save(self) -> None:
        try:
            settings = self.collect()
        except ValueError as e:
            self.notify(str(e), severity="warning")
            return
        self.app.update_settings(settings)
        self.notify("設定を保存しました")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "save":
            self.action_save()
        elif bid in ("smtp", "imap"):
            try:
                settings = self.collect()
            except ValueError as e:
                self.notify(str(e), severity="warning")
                return
            if bid == "smtp":
                from ..mailer import check_smtp_connection as check
            else:
                from ..replies import check_imap_connection as check
            title = "SMTP接続テスト" if bid == "smtp" else "IMAP接続テスト"
            self.notify("接続しています…")
            self.run_bg(lambda: check(settings), lambda msg: self.app.push_screen(MessageDialog(msg, title)),
                        lambda e: self.app.push_screen(MessageDialog(f"接続に失敗しました:\n{e}", title)))
        elif bid == "shortcut":
            self.app.create_shortcut()
        elif bid == "demo-open":
            self.open_test_environment()
        elif bid == "demo-reset":
            self.reset_demo()

    def open_test_environment(self) -> None:
        from ..shortcut import open_test_environment

        try:
            open_test_environment()
        except Exception as e:  # noqa: BLE001
            self.app.push_screen(MessageDialog(f"テスト環境を開けませんでした:\n{e}", "テスト環境"))
            return
        self.notify("テスト環境を別のウィンドウで開きました（サンプルデータ・メールは送信されません）", timeout=8)

    @work
    async def reset_demo(self) -> None:
        if not await self.app.push_screen_wait(ConfirmDialog(
                "テスト環境の企業リストと送信履歴を、最初のサンプルの状態に戻しますか？\n（本番のデータには影響しません）",
                "サンプルデータを戻す")):
            return
        from ..demo import reset

        reset(self.db)
        self.app.data_changed()
        self.notify("サンプルデータを初期状態に戻しました")


def default_export_dir() -> Path:
    return desktop_dir()
