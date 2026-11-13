"""ターミナル版の共通ウィジェット."""

from __future__ import annotations

from typing import Callable, Iterable, Sequence

from rich.text import Text
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable, SelectionList
from textual.widgets.selection_list import Selection

from ..regions import PREFECTURES, REGIONS

STYLES = {"muted": "#8a8a8a", "warn": "#e8a33d", "ok": "#5fbf6a", "": ""}
MARK_COLUMN = "_mark"


def cell(value, style: str = "") -> Text:
    """DataTable のセル。会社名などに含まれる [ ] がマークアップ扱いされないよう Text にする."""
    return Text("" if value is None else str(value), style=STYLES.get(style, style), no_wrap=True)


class MarkTable(DataTable):
    """スペースキーで行にチェック（✓）を付けられる表."""

    BINDINGS = [
        Binding("space", "toggle_mark", "チェック", show=True),
        Binding("ctrl+a", "mark_all", "全チェック", show=False),
    ]

    class MarksChanged(Message):
        def __init__(self, table: "MarkTable") -> None:
            super().__init__()
            self.table = table

        @property
        def control(self) -> "MarkTable":
            return self.table

    def __init__(self, columns: Sequence[tuple[str, str]], markable: bool = True, **kw):
        super().__init__(cursor_type="row", zebra_stripes=True, **kw)
        self._cols = list(columns)
        self.markable = markable
        self.data: dict[str, object] = {}
        self.marked: set[str] = set()
        self._values: Callable[[object], Sequence] = lambda r: []
        self._style: Callable[[object], str] | None = None

    def on_mount(self) -> None:
        if self.markable:
            self.add_column("✓", key=MARK_COLUMN, width=1)
        for key, label in self._cols:
            self.add_column(label, key=key)

    def check_action(self, action: str, parameters) -> bool | None:
        if action in ("toggle_mark", "mark_all") and not self.markable:
            return False
        return True

    # ---------------------------------------------------------------- データ
    def set_rows(self, rows: Iterable, values: Callable[[object], Sequence],
                 key: Callable[[object], str] = lambda r: str(r["id"]),
                 style: Callable[[object], str] | None = None, mark_all: bool = False) -> None:
        current = self.current_key()
        self._values, self._style = values, style
        self.clear()
        self.data = {}
        for row in rows:
            k = key(row)
            if k not in self.data:
                self.data[k] = row
        self.marked = set(self.data) if mark_all else {k for k in self.marked if k in self.data}
        for k, row in self.data.items():
            self.add_row(*self._cells(k, row), key=k)
        if current in self.data:
            self.move_cursor(row=self.get_row_index(current))
        self.post_message(self.MarksChanged(self))

    def _cells(self, k: str, row) -> list[Text]:
        st = self._style(row) if self._style else ""
        cells = [cell(v, st) for v in self._values(row)]
        if self.markable:
            cells.insert(0, cell("✓" if k in self.marked else "", "bold green"))
        return cells

    def redraw_row(self, k: str) -> None:
        if k not in self.data:
            return
        cells = self._cells(k, self.data[k])
        keys = ([MARK_COLUMN] if self.markable else []) + [c[0] for c in self._cols]
        for col, value in zip(keys, cells):
            self.update_cell(k, col, value)

    def current_key(self) -> str | None:
        if not self.row_count:
            return None
        try:
            row_key, _ = self.coordinate_to_cell_key(Coordinate(self.cursor_row, 0))
        except Exception:
            return None
        return row_key.value

    def current(self):
        k = self.current_key()
        return self.data.get(k) if k else None

    def marked_rows(self) -> list:
        return [row for k, row in self.data.items() if k in self.marked]

    def marked_or_current(self) -> list:
        """チェックした行。チェックが無ければカーソル行."""
        rows = self.marked_rows()
        if rows:
            return rows
        row = self.current()
        return [row] if row is not None else []

    # ---------------------------------------------------------------- チェック
    def set_marks(self, keys: Iterable[str]) -> None:
        self.marked = {k for k in keys if k in self.data}
        for k in self.data:
            self.update_cell(k, MARK_COLUMN, cell("✓" if k in self.marked else "", "bold green"))
        self.post_message(self.MarksChanged(self))

    def action_toggle_mark(self) -> None:
        k = self.current_key()
        if not k:
            return
        self.marked.symmetric_difference_update({k})
        self.update_cell(k, MARK_COLUMN, cell("✓" if k in self.marked else "", "bold green"))
        self.post_message(self.MarksChanged(self))
        if self.cursor_row < self.row_count - 1:
            self.move_cursor(row=self.cursor_row + 1)

    def action_mark_all(self) -> None:
        self.set_marks(set() if len(self.marked) == len(self.data) else set(self.data))


class PrefPicker(SelectionList):
    """地方 → 都道府県 の複数選択リスト。地方の行を選ぶとまとめて選択／解除する."""

    def __init__(self, **kw):
        items: list[Selection] = []
        for region, prefs in REGIONS.items():
            if prefs == [region]:  # 北海道
                items.append(Selection(region, region))
                continue
            items.append(Selection(f"■ {region}（まとめて）", f"@{region}"))
            for pref in prefs:
                items.append(Selection(f"   {pref}", pref))
        super().__init__(*items, **kw)

    def on_selection_list_selection_toggled(self, event: SelectionList.SelectionToggled) -> None:
        value = event.selection.value
        selected = set(self.selected)
        if value.startswith("@"):
            prefs = REGIONS[value[1:]]
            for pref in prefs:
                (self.select if value in selected else self.deselect)(pref)
        else:
            for region, prefs in REGIONS.items():
                if value in prefs and prefs != [region]:
                    all_on = all(p in selected for p in prefs)
                    (self.select if all_on else self.deselect)(f"@{region}")

    def prefectures(self) -> list[str]:
        selected = set(self.selected)
        return [p for p in PREFECTURES if p in selected]

    def set_prefectures(self, prefectures: Iterable[str]) -> None:
        self.deselect_all()
        for pref in prefectures:
            self.select(pref)
        for region, prefs in REGIONS.items():
            if prefs != [region] and all(p in prefectures for p in prefs):
                self.select(f"@{region}")


def split_list(text: str) -> list[str]:
    import re

    return [t.strip() for t in re.split(r"[,、，\n]+", text or "") if t.strip()]


def clean_path(text: str) -> str:
    """ドラッグ＆ドロップで入力されたパスの前後の引用符・空白を取り除く."""
    return (text or "").strip().strip("'\"").strip()
