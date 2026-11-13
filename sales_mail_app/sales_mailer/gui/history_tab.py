"""送信履歴タブ."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..csv_io import write_rows_csv
from ..db import KIND_FOLLOW, KIND_NEW, KIND_TEST, RESULT_DRY_RUN, RESULT_FAILED, RESULT_SENT
from .widgets import DataTable

KIND_LABELS = {KIND_NEW: "新規", KIND_FOLLOW: "フォロー", KIND_TEST: "テスト"}
RESULT_LABELS = {RESULT_SENT: "送信済み", RESULT_FAILED: "失敗", RESULT_DRY_RUN: "テスト（未送信）"}
COLUMNS = [
    ("sent_at", "日時", 150), ("kind", "種別", 90), ("company", "会社名", 200), ("email", "宛先", 210),
    ("subject", "件名", 280), ("result", "結果", 110), ("error", "エラー", 200),
]


def kind_label(row: dict) -> str:
    label = KIND_LABELS.get(row["kind"], row["kind"])
    return f"{label}{row['step']}回目" if row["kind"] == KIND_FOLLOW and row["step"] else label


class HistoryTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Label(bar, text="種別").pack(side="left")
        self.kind_var = tk.StringVar(value="すべて")
        combo = ttk.Combobox(bar, textvariable=self.kind_var, values=["すべて", "新規", "フォロー"], state="readonly",
                             width=10)
        combo.pack(side="left", padx=(4, 12))
        combo.bind("<<ComboboxSelected>>", lambda _e: self.reload())
        ttk.Label(bar, text="結果").pack(side="left")
        self.result_var = tk.StringVar(value="すべて")
        combo2 = ttk.Combobox(bar, textvariable=self.result_var, values=["すべて", *RESULT_LABELS.values()],
                              state="readonly", width=16)
        combo2.pack(side="left", padx=(4, 12))
        combo2.bind("<<ComboboxSelected>>", lambda _e: self.reload())
        ttk.Button(bar, text="更新", command=self.reload).pack(side="left")
        ttk.Button(bar, text="CSV書き出し", command=self.export).pack(side="right")
        self.count_label = ttk.Label(bar, text="")
        self.count_label.pack(side="right", padx=12)

        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(fill="both", expand=True, pady=(8, 0))
        self.table = DataTable(paned, COLUMNS, height=16, selectmode="browse")
        self.table.tree.bind("<<TreeviewSelect>>", lambda _e: self.show_body())
        paned.add(self.table, weight=3)
        self.body = tk.Text(paned, height=10, wrap="word", state="disabled")
        paned.add(self.body, weight=1)
        self.reload()

    def on_show(self) -> None:
        self.reload()

    def reload(self) -> None:
        kind = {"新規": KIND_NEW, "フォロー": KIND_FOLLOW}.get(self.kind_var.get())
        result = {v: k for k, v in RESULT_LABELS.items()}.get(self.result_var.get())
        rows = self.app.db.list_send_log(kind, result)
        self.table.set_rows(
            rows,
            lambda r: [r["sent_at"], kind_label(r), r["company_name"], r["email"], r["subject"],
                       RESULT_LABELS.get(r["result"], r["result"]), r["error"]],
            tags=lambda r: ["warn"] if r["result"] == RESULT_FAILED else (["muted"] if r["result"] == RESULT_DRY_RUN
                                                                          else []),
        )
        self.count_label.configure(text=f"{len(rows)} 件")

    def show_body(self) -> None:
        rows = self.table.selected()
        self.body.configure(state="normal")
        self.body.delete("1.0", "end")
        if rows:
            r = rows[0]
            self.body.insert("1.0", f"件名: {r['subject']}\n宛先: {r['email']}\n\n{r['body']}")
        self.body.configure(state="disabled")

    def export(self) -> None:
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile="送信履歴.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        rows = list(self.table.rows.values())
        write_rows_csv(path, ["日時", "種別", "会社名", "宛先", "件名", "結果", "エラー"],
                       [[r["sent_at"], kind_label(r), r["company_name"], r["email"], r["subject"],
                         RESULT_LABELS.get(r["result"], r["result"]), r["error"]] for r in rows])
        messagebox.showinfo("CSV書き出し", f"{len(rows)} 件を書き出しました。", parent=self)
