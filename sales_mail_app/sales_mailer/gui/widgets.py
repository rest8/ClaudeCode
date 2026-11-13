"""共通ウィジェット."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable, Iterable, Sequence

from ..regions import REGIONS

UNCHECKED, CHECKED, PARTIAL = "☐", "☑", "◩"


class RegionSelector(ttk.Frame):
    """地方 → 都道府県 のチェックボックス付きツリー."""

    def __init__(self, master, height: int = 14, on_change: Callable[[], None] | None = None, **kw):
        super().__init__(master, **kw)
        self.on_change = on_change
        self._checked: set[str] = set()
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Label(bar, text="調査・対象地域").pack(side="left")
        ttk.Button(bar, text="全解除", width=6, command=self.clear).pack(side="right")
        ttk.Button(bar, text="全選択", width=6, command=self.select_all).pack(side="right", padx=2)
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, pady=(4, 0))
        self.tree = ttk.Treeview(frame, show="tree", height=height, selectmode="none")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for region, prefs in REGIONS.items():
            rid = self.tree.insert("", "end", iid=f"r:{region}", text=f"{UNCHECKED} {region}", open=False)
            for pref in prefs:
                if region == pref:  # 北海道
                    continue
                self.tree.insert(rid, "end", iid=f"p:{pref}", text=f"{UNCHECKED} {pref}")
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<space>", self._on_space)
        self.summary = ttk.Label(self, text="未選択（すべての地域）", foreground="#555")
        self.summary.pack(fill="x", pady=(4, 0))

    def _prefs_of(self, iid: str) -> list[str]:
        if iid.startswith("p:"):
            return [iid[2:]]
        return list(REGIONS[iid[2:]])

    def _toggle(self, iid: str) -> None:
        prefs = self._prefs_of(iid)
        if all(p in self._checked for p in prefs):
            self._checked.difference_update(prefs)
        else:
            self._checked.update(prefs)
        self._redraw()

    def _on_click(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        element = self.tree.identify_element(event.x, event.y)
        if not iid or "indicator" in element:
            return
        self._toggle(iid)

    def _on_space(self, _event) -> None:
        iid = self.tree.focus()
        if iid:
            self._toggle(iid)

    def _redraw(self) -> None:
        for region, prefs in REGIONS.items():
            n = sum(p in self._checked for p in prefs)
            mark = CHECKED if n == len(prefs) else PARTIAL if n else UNCHECKED
            self.tree.item(f"r:{region}", text=f"{mark} {region}")
            for pref in prefs:
                if self.tree.exists(f"p:{pref}"):
                    mark = CHECKED if pref in self._checked else UNCHECKED
                    self.tree.item(f"p:{pref}", text=f"{mark} {pref}")
        selected = self.get()
        if not selected:
            self.summary.configure(text="未選択（すべての地域）")
        elif len(selected) <= 4:
            self.summary.configure(text="選択中: " + "、".join(selected))
        else:
            self.summary.configure(text=f"選択中: {'、'.join(selected[:4])} ほか（計{len(selected)}）")
        if self.on_change:
            self.on_change()

    def get(self) -> list[str]:
        return [p for prefs in REGIONS.values() for p in prefs if p in self._checked]

    def set(self, prefectures: Iterable[str]) -> None:
        self._checked = set(prefectures)
        self._redraw()

    def clear(self) -> None:
        self.set([])

    def select_all(self) -> None:
        self.set([p for prefs in REGIONS.values() for p in prefs])


class DataTable(ttk.Frame):
    """スクロールバー付きの表."""

    def __init__(self, master, columns: Sequence[tuple[str, str, int]], height: int = 15,
                 selectmode: str = "extended", **kw):
        super().__init__(master, **kw)
        self.keys = [c[0] for c in columns]
        self.tree = ttk.Treeview(self, columns=self.keys, show="headings", height=height, selectmode=selectmode)
        for key, label, width in columns:
            self.tree.heading(key, text=label, command=lambda k=key: self._sort(k))
            self.tree.column(key, width=width, minwidth=40, stretch=width >= 200)
        ysb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rows: dict[str, dict] = {}
        self._sort_desc: dict[str, bool] = {}
        self.tree.tag_configure("muted", foreground="#999999")
        self.tree.tag_configure("warn", foreground="#b25000")
        self.tree.tag_configure("ok", foreground="#1a7f37")

    def set_rows(self, rows: Iterable[dict], values: Callable[[dict], Sequence], iid_key: str = "id",
                 tags: Callable[[dict], Sequence[str]] | None = None) -> None:
        selection = set(self.tree.selection())
        yview = self.tree.yview()[0]
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        for i, row in enumerate(rows):
            iid = str(row.get(iid_key, i)) if iid_key else str(i)
            self.rows[iid] = row
            self.tree.insert("", "end", iid=iid, values=[("" if v is None else v) for v in values(row)],
                             tags=tuple(tags(row)) if tags else ())
        keep = [i for i in selection if i in self.rows]
        if keep:
            self.tree.selection_set(keep)
        self.tree.yview_moveto(yview)

    def selected(self) -> list[dict]:
        return [self.rows[i] for i in self.tree.selection() if i in self.rows]

    def select_all(self) -> None:
        self.tree.selection_set(self.tree.get_children())

    def _sort(self, key: str) -> None:
        desc = not self._sort_desc.get(key, False)
        self._sort_desc[key] = desc
        items = [(self.tree.set(i, key), i) for i in self.tree.get_children("")]

        def sort_key(item):
            value = item[0]
            try:
                return (0, float(value), "")
            except ValueError:
                return (1, 0.0, value)

        items.sort(key=sort_key, reverse=desc)
        for pos, (_, iid) in enumerate(items):
            self.tree.move(iid, "", pos)


class LogBox(ScrolledText):
    def __init__(self, master, height: int = 8, **kw):
        super().__init__(master, height=height, state="disabled", wrap="word", **kw)

    def append(self, text: str) -> None:
        self.configure(state="normal")
        self.insert("end", text.rstrip() + "\n")
        self.see("end")
        self.configure(state="disabled")

    def clear(self) -> None:
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")


def labeled_entry(parent, row: int, label: str, var: tk.Variable, width: int = 40, show: str | None = None,
                  hint: str = "") -> ttk.Entry:
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
    entry = ttk.Entry(parent, textvariable=var, width=width, show=show or "")
    entry.grid(row=row, column=1, sticky="we", pady=3)
    if hint:
        ttk.Label(parent, text=hint, foreground="#666").grid(row=row, column=2, sticky="w", padx=(8, 0))
    return entry


def split_list(text: str) -> list[str]:
    """カンマ・読点・改行区切りの文字列をリストにする."""
    import re

    return [t.strip() for t in re.split(r"[,、，\n]+", text or "") if t.strip()]
