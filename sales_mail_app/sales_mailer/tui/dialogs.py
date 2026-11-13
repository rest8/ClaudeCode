"""ターミナル版のダイアログ（確認・メッセージ・選択・入力・企業編集・CSV取り込み）."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, RadioButton, RadioSet, Select, Static, TextArea
from textual.widgets.option_list import Option

from ..db import STATUS_CONTRACTED, STATUS_LABELS, STATUS_NEW, STATUS_OPTED_OUT, STATUS_SENT, normalize_email
from ..mailer import format_date_jp
from ..regions import PREFECTURES

DIALOG_CSS = """
.dialog {
    width: 76;
    max-width: 95%;
    height: auto;
    max-height: 90%;
    border: thick $accent;
    background: $panel;
    padding: 1 2;
}
.dialog .title { text-style: bold; margin-bottom: 1; }
.dialog .buttons { height: auto; margin-top: 1; align-horizontal: right; }
.dialog .buttons Button { margin-left: 1; }
.dialog .body { height: auto; max-height: 24; }
.dialog .hint { color: $text-muted; }
ModalScreen { align: center middle; }
#company-form { width: 90; }
#company-form Grid { grid-size: 2; grid-columns: 16 1fr; grid-rows: auto; height: auto; grid-gutter: 0 1; }
#company-form Grid Label { padding-top: 0; }
#company-form TextArea { height: 4; }
"""


class ConfirmDialog(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", "キャンセル"), Binding("y", "ok", "はい", show=False)]

    def __init__(self, message: str, title: str = "確認", ok: str = "はい", cancel: str = "いいえ"):
        super().__init__()
        self.message, self.title_text, self.ok_label, self.cancel_label = message, title, ok, cancel

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_text, classes="title", markup=False)
            with VerticalScroll(classes="body"):
                yield Static(self.message, markup=False)
            with Horizontal(classes="buttons"):
                yield Button(self.cancel_label, id="cancel")
                yield Button(self.ok_label, id="ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#ok", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "ok")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_ok(self) -> None:
        self.dismiss(True)


class MessageDialog(ModalScreen[None]):
    BINDINGS = [Binding("escape,enter", "close", "閉じる")]

    def __init__(self, message: str, title: str = "お知らせ"):
        super().__init__()
        self.message, self.title_text = message, title

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_text, classes="title", markup=False)
            with VerticalScroll(classes="body"):
                yield Static(self.message, markup=False)
            with Horizontal(classes="buttons"):
                yield Button("OK", id="ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#ok", Button).focus()

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class ChoiceDialog(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "キャンセル")]

    def __init__(self, title: str, choices: list[tuple[str, str]]):
        super().__init__()
        self.title_text, self.choices = title, choices

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_text, classes="title", markup=False)
            yield OptionList(*[Option(label, id=value) for label, value in self.choices], markup=False)
            with Horizontal(classes="buttons"):
                yield Button("キャンセル", id="cancel")

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class InputDialog(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "キャンセル")]

    def __init__(self, title: str, value: str = "", hint: str = "", ok: str = "OK"):
        super().__init__()
        self.title_text, self.value, self.hint, self.ok_label = title, value, hint, ok

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_text, classes="title", markup=False)
            yield Input(self.value, id="value")
            if self.hint:
                yield Static(self.hint, classes="hint", markup=False)
            with Horizontal(classes="buttons"):
                yield Button("キャンセル", id="cancel")
                yield Button(self.ok_label, id="ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(self.query_one(Input).value if event.button.id == "ok" else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


IMPORT_CHOICES = [
    (STATUS_NEW, "未送付（新規メールの送信対象にする）"),
    (STATUS_SENT, "送付済み（過去に送った企業。新規は送らず、フォロー対象にする）"),
    (STATUS_CONTRACTED, "契約済み（既存顧客。リストと送信対象から除外する）"),
    (STATUS_OPTED_OUT, "配信停止（今後一切送らない）"),
]


class ImportDialog(ModalScreen[tuple[str, str] | None]):
    BINDINGS = [Binding("escape", "cancel", "キャンセル")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("CSV取り込み", classes="title")
            yield Static("CSVファイルのパス（ファイルをこの画面にドラッグ＆ドロップしても入力できます）", classes="hint")
            yield Input(id="path", placeholder="例: C:\\Users\\you\\Desktop\\企業リスト.csv")
            yield Label("取り込む企業の扱い")
            with RadioSet(id="status"):
                for i, (_value, label) in enumerate(IMPORT_CHOICES):
                    yield RadioButton(label, value=i == 0)
            yield Static("※「ステータス」列がある行はその値を優先します。登録済みの企業（同じメール・ドメイン・会社名）は"
                         "重複登録しません。契約済み／配信停止として取り込むと、登録済みの企業もそのステータスに更新します。",
                         classes="hint")
            with Horizontal(classes="buttons"):
                yield Button("キャンセル", id="cancel")
                yield Button("取り込む", id="ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#path", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "ok":
            self.dismiss(None)
            return
        index = self.query_one(RadioSet).pressed_index
        status = IMPORT_CHOICES[index if index >= 0 else 0][0]
        self.dismiss((self.query_one("#path", Input).value, status))

    def action_cancel(self) -> None:
        self.dismiss(None)


class CompanyForm(ModalScreen[dict | None]):
    """企業の追加・編集フォーム。保存すると入力値の dict を返す."""

    BINDINGS = [Binding("escape", "cancel", "キャンセル"), Binding("ctrl+s", "save", "保存")]
    FIELDS = [
        ("name", "会社名 *"), ("email", "メールアドレス"), ("contact_name", "担当者名"), ("website", "Webサイト"),
        ("phone", "電話番号"), ("address", "住所"), ("city", "市区町村"), ("industry", "業種"),
        ("description", "事業内容"),
    ]

    def __init__(self, company: dict | None = None):
        super().__init__()
        self.company = company or {}

    def compose(self) -> ComposeResult:
        c = self.company
        with Vertical(classes="dialog", id="company-form"):
            yield Label("企業の編集" if c.get("id") else "企業の追加", classes="title")
            with VerticalScroll(classes="body"):
                with Grid():
                    for key, label in self.FIELDS:
                        yield Label(label)
                        yield Input(str(c.get(key) or ""), id=f"f-{key}", compact=True)
                    yield Label("都道府県")
                    yield Select([(p, p) for p in PREFECTURES], value=c.get("prefecture") or Select.NULL,
                                 id="f-prefecture", prompt="（住所から自動判定）", compact=True)
                    yield Label("ステータス")
                    yield Select([(v, k) for k, v in STATUS_LABELS.items()], value=c.get("status") or STATUS_NEW,
                                 id="f-status", allow_blank=False, compact=True)
                    yield Label("備考")
                    yield TextArea(c.get("notes") or "", id="f-notes")
                if c.get("id"):
                    yield Static(f"初回送信: {format_date_jp(c.get('first_sent_at')) or '-'}　"
                                 f"最終送信: {format_date_jp(c.get('last_sent_at')) or '-'}　"
                                 f"フォロー: {c.get('follow_count', 0)} 回", classes="hint")
            with Horizontal(classes="buttons"):
                yield Button("キャンセル", id="cancel")
                yield Button("保存 (Ctrl+S)", id="ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#f-name", Input).focus()

    def collect(self) -> dict:
        data = {key: self.query_one(f"#f-{key}", Input).value.strip() for key, _ in self.FIELDS}
        pref = self.query_one("#f-prefecture", Select).value
        data["prefecture"] = "" if pref is Select.NULL else pref
        data["status"] = self.query_one("#f-status", Select).value
        data["notes"] = self.query_one("#f-notes", TextArea).text.strip()
        return data

    def action_save(self) -> None:
        data = self.collect()
        if not data["name"]:
            self.notify("会社名を入力してください", severity="warning")
            return
        if data["email"] and not normalize_email(data["email"]):
            self.notify("メールアドレスの形式が正しくありません", severity="warning")
            return
        self.dismiss(data)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self.action_save()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
