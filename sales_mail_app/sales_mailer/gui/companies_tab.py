"""企業リストタブ（登録・編集・CSV・ステータス変更・契約済みの除外）."""

from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from ..csv_io import read_companies_csv, write_companies_csv
from ..db import (
    STATUS_CONTRACTED, STATUS_ERROR, STATUS_LABELS, STATUS_NEW, STATUS_OPTED_OUT, STATUS_REPLIED, STATUS_SENT,
)
from ..db import normalize_email
from ..mailer import format_date_jp
from ..regions import PREFECTURES
from .widgets import DataTable

FILTERS = [
    ("active", "有効な企業（契約済み・配信停止を除く）"),
    (STATUS_NEW, "未送付"),
    (STATUS_SENT, "送付済み"),
    (STATUS_REPLIED, "返信あり"),
    (STATUS_CONTRACTED, "契約済み（除外中）"),
    (STATUS_OPTED_OUT, "配信停止（除外中）"),
    (STATUS_ERROR, "送信エラー"),
    ("all", "すべて"),
]

COLUMNS = [
    ("id", "ID", 50), ("name", "会社名", 220), ("status", "ステータス", 80), ("email", "メールアドレス", 210),
    ("prefecture", "都道府県", 80), ("city", "市区町村", 100), ("industry", "業種", 120),
    ("first_sent", "初回送信", 90), ("last_sent", "最終送信", 90), ("follow", "フォロー", 60),
    ("phone", "電話番号", 120), ("website", "Webサイト", 200), ("source", "取得元", 100),
]

SOURCE_LABELS = {"google_places": "Google調査", "claude_web": "AI Web調査", "csv": "CSV", "manual": "手入力"}


def company_values(c: dict) -> list:
    return [
        c["id"], c["name"], STATUS_LABELS.get(c["status"], c["status"]), c["email"], c["prefecture"], c["city"],
        c["industry"], format_date_jp(c["first_sent_at"]), format_date_jp(c["last_sent_at"]), c["follow_count"],
        c["phone"], c["website"], SOURCE_LABELS.get(c["source"], c["source"]),
    ]


def company_tags(c: dict) -> list[str]:
    if c["status"] in (STATUS_CONTRACTED, STATUS_OPTED_OUT):
        return ["muted"]
    if c["status"] == STATUS_ERROR or not c["email"]:
        return ["warn"]
    if c["status"] == STATUS_REPLIED:
        return ["ok"]
    return []


class CompaniesTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app

        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Label(bar, text="検索").pack(side="left")
        self.search_var = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.search_var, width=24)
        entry.pack(side="left", padx=(4, 12))
        entry.bind("<Return>", lambda _e: self.reload())
        ttk.Label(bar, text="表示").pack(side="left")
        self.filter_var = tk.StringVar(value=FILTERS[0][1])
        combo = ttk.Combobox(bar, textvariable=self.filter_var, values=[f[1] for f in FILTERS],
                             state="readonly", width=42)
        combo.pack(side="left", padx=(4, 12))
        combo.bind("<<ComboboxSelected>>", lambda _e: self.reload())
        ttk.Label(bar, text="都道府県").pack(side="left")
        self.pref_var = tk.StringVar(value="すべて")
        pcombo = ttk.Combobox(bar, textvariable=self.pref_var, values=["すべて", *PREFECTURES],
                              state="readonly", width=10)
        pcombo.pack(side="left", padx=(4, 12))
        pcombo.bind("<<ComboboxSelected>>", lambda _e: self.reload())
        ttk.Button(bar, text="検索・更新", command=self.reload).pack(side="left")
        self.count_label = ttk.Label(bar, text="")
        self.count_label.pack(side="right")

        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=(8, 6))
        ttk.Button(actions, text="＋ 企業を追加", command=self.add).pack(side="left")
        ttk.Button(actions, text="編集", command=self.edit).pack(side="left", padx=4)
        ttk.Button(actions, text="削除", command=self.delete).pack(side="left")
        ttk.Separator(actions, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(actions, text="契約済みにする（リストから除外）", style="Accent.TButton",
                   command=lambda: self.change_status(STATUS_CONTRACTED)).pack(side="left")
        status_menu = tk.Menu(self, tearoff=False)
        for status in (STATUS_REPLIED, STATUS_OPTED_OUT, STATUS_SENT, STATUS_NEW, STATUS_ERROR):
            status_menu.add_command(label=f"{STATUS_LABELS[status]}にする",
                                    command=lambda s=status: self.change_status(s))
        mb = ttk.Menubutton(actions, text="その他のステータス変更 ▾", menu=status_menu)
        mb.pack(side="left", padx=4)
        ttk.Separator(actions, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(actions, text="CSV取り込み", command=self.import_csv).pack(side="left")
        ttk.Button(actions, text="CSV書き出し", command=self.export_csv).pack(side="left", padx=4)

        self.table = DataTable(self, COLUMNS, height=20)
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<Double-1>", lambda _e: self.edit())
        ttk.Label(
            self,
            text="※ 契約済み・配信停止の企業は既定の表示と、すべての送信対象（新規・フォロー）から自動的に除外されます。"
                 "同じドメインの企業を後から調査・登録しても対象になりません。",
            foreground="#555",
        ).pack(fill="x", pady=(6, 0))
        self.reload()

    def on_show(self) -> None:
        self.reload()

    def _filter_key(self) -> str:
        label = self.filter_var.get()
        return next((k for k, v in FILTERS if v == label), "active")

    def reload(self) -> None:
        pref = self.pref_var.get()
        rows = self.app.db.list_companies(
            status_filter=self._filter_key(),
            prefectures=[pref] if pref and pref != "すべて" else None,
            search=self.search_var.get(),
        )
        self.table.set_rows(rows, company_values, tags=company_tags)
        self.count_label.configure(text=f"{len(rows)} 件")

    def _selected_ids(self) -> list[int]:
        return [r["id"] for r in self.table.selected()]

    def add(self) -> None:
        CompanyDialog(self, self.app, None)

    def edit(self) -> None:
        rows = self.table.selected()
        if not rows:
            messagebox.showinfo("編集", "編集する企業を選択してください", parent=self)
            return
        CompanyDialog(self, self.app, rows[0]["id"])

    def delete(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        if not messagebox.askyesno(
            "削除",
            f"{len(ids)} 件の企業を削除しますか？\n\n"
            "※ 既存顧客をリストから外したい場合は、削除ではなく「契約済みにする」を使うと、"
            "再調査しても重複登録・誤送信されません。",
            parent=self,
        ):
            return
        self.app.db.delete_companies(ids)
        self.app.data_changed()

    def change_status(self, status: str) -> None:
        ids = self._selected_ids()
        if not ids:
            messagebox.showinfo("ステータス変更", "企業を選択してください（複数選択可）", parent=self)
            return
        label = STATUS_LABELS[status]
        msg = f"{len(ids)} 件を「{label}」にしますか？"
        if status == STATUS_CONTRACTED:
            msg += "\n\n契約済みの企業は一覧の既定表示とすべての送信対象から除外されます。"
        if not messagebox.askyesno("ステータス変更", msg, parent=self):
            return
        self.app.db.set_status(ids, status)
        self.app.data_changed()

    def import_csv(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="CSVを選択",
                                          filetypes=[("CSV", "*.csv"), ("すべて", "*.*")])
        if not path:
            return
        try:
            rows, recognized = read_companies_csv(path)
        except (OSError, ValueError) as e:
            messagebox.showerror("CSV取り込み", str(e), parent=self)
            return
        ImportDialog(self, self.app, rows, recognized)

    def export_csv(self) -> None:
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile="企業リスト.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        rows = list(self.table.rows.values())
        write_companies_csv(path, rows)
        messagebox.showinfo("CSV書き出し", f"{len(rows)} 件を書き出しました。", parent=self)


class ImportDialog(tk.Toplevel):
    def __init__(self, master, app, rows: list[dict], recognized: list[str]):
        super().__init__(master)
        self.app = app
        self.rows = rows
        self.title("CSV取り込み")
        self.transient(master)
        self.resizable(False, False)
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"{len(rows)} 行を読み込みました。").pack(anchor="w")
        ttk.Label(body, text="認識した列: " + "、".join(recognized), foreground="#555",
                  wraplength=460).pack(anchor="w", pady=(2, 10))
        ttk.Label(body, text="取り込む企業の扱い").pack(anchor="w")
        self.status_var = tk.StringVar(value=STATUS_NEW)
        options = [
            (STATUS_NEW, "未送付（新規メールの送信対象にする）"),
            (STATUS_SENT, "送付済み（過去に送った企業。新規は送らず、フォロー対象にする）"),
            (STATUS_CONTRACTED, "契約済み（既存顧客。リストと送信対象から除外する）"),
            (STATUS_OPTED_OUT, "配信停止（今後一切送らない）"),
        ]
        for value, text in options:
            ttk.Radiobutton(body, text=text, value=value, variable=self.status_var).pack(anchor="w", pady=1)
        ttk.Label(body, text="※ 「ステータス」列がある行はその値を優先します。\n"
                             "※ 既に登録済みの企業（同じメール・ドメイン・会社名）は重複登録しません。\n"
                             "   契約済み／配信停止として取り込むと、登録済みの企業もそのステータスに更新します。",
                  foreground="#555", justify="left").pack(anchor="w", pady=(10, 10))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="取り込む", style="Accent.TButton", command=self.run).pack(side="right")
        ttk.Button(buttons, text="キャンセル", command=self.destroy).pack(side="right", padx=6)
        self.grab_set()

    def run(self) -> None:
        for row in self.rows:
            row.setdefault("source", "csv")
        result = self.app.db.import_rows(self.rows, status=self.status_var.get())
        self.destroy()
        self.app.data_changed()
        messagebox.showinfo(
            "CSV取り込み",
            f"追加: {result.added} 件\n既存企業のステータス更新: {result.updated} 件\n"
            f"スキップ（重複・会社名なし）: {result.skipped} 件",
            parent=self.app,
        )


class CompanyDialog(tk.Toplevel):
    FIELDS = [
        ("name", "会社名 *"), ("email", "メールアドレス"), ("contact_name", "担当者名"), ("website", "Webサイト"),
        ("phone", "電話番号"), ("address", "住所"), ("prefecture", "都道府県"), ("city", "市区町村"),
        ("industry", "業種"), ("description", "事業内容"),
    ]

    def __init__(self, master, app, company_id: int | None):
        super().__init__(master)
        self.app = app
        self.company_id = company_id
        company = app.db.get_company(company_id) if company_id else {}
        self.title("企業の編集" if company_id else "企業の追加")
        self.transient(master)
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        self.vars: dict[str, tk.StringVar] = {}
        for i, (key, label) in enumerate(self.FIELDS):
            ttk.Label(body, text=label).grid(row=i, column=0, sticky="w", pady=3, padx=(0, 8))
            var = tk.StringVar(value=str(company.get(key) or ""))
            self.vars[key] = var
            if key == "prefecture":
                widget = ttk.Combobox(body, textvariable=var, values=["", *PREFECTURES], width=48)
            else:
                widget = ttk.Entry(body, textvariable=var, width=50)
            widget.grid(row=i, column=1, sticky="we", pady=3)
            if key == "website":
                ttk.Button(body, text="開く", width=5,
                           command=lambda v=var: v.get() and webbrowser.open(v.get())).grid(row=i, column=2, padx=4)
        row = len(self.FIELDS)
        ttk.Label(body, text="ステータス").grid(row=row, column=0, sticky="w", pady=3)
        self.status_var = tk.StringVar(value=STATUS_LABELS.get(company.get("status", STATUS_NEW)))
        ttk.Combobox(body, textvariable=self.status_var, values=list(STATUS_LABELS.values()),
                     state="readonly", width=20).grid(row=row, column=1, sticky="w", pady=3)
        ttk.Label(body, text="備考").grid(row=row + 1, column=0, sticky="nw", pady=3)
        self.notes = tk.Text(body, width=50, height=4, wrap="word")
        self.notes.grid(row=row + 1, column=1, sticky="we", pady=3)
        self.notes.insert("1.0", company.get("notes") or "")
        if company_id:
            info = (f"初回送信: {format_date_jp(company.get('first_sent_at')) or '-'}　"
                    f"最終送信: {format_date_jp(company.get('last_sent_at')) or '-'}　"
                    f"フォロー: {company.get('follow_count', 0)} 回")
            ttk.Label(body, text=info, foreground="#555").grid(row=row + 2, column=0, columnspan=3, sticky="w",
                                                              pady=(6, 0))
        buttons = ttk.Frame(body)
        buttons.grid(row=row + 3, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="キャンセル", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="保存", style="Accent.TButton", command=self.save).pack(side="right", padx=6)
        self.grab_set()

    def save(self) -> None:
        data = {k: v.get().strip() for k, v in self.vars.items()}
        data["notes"] = self.notes.get("1.0", "end").strip()
        data["status"] = self.status_var.get()
        if not data["name"]:
            messagebox.showwarning("入力エラー", "会社名を入力してください", parent=self)
            return
        if data["email"] and not normalize_email(data["email"]):
            messagebox.showwarning("入力エラー", "メールアドレスの形式が正しくありません", parent=self)
            return
        db = self.app.db
        try:
            if self.company_id:
                db.update_company(self.company_id, data)
            else:
                dup = db.find_duplicate(data["name"], data["email"], data["website"], "", data["prefecture"])
                if dup and not messagebox.askyesno(
                    "重複の可能性",
                    f"「{dup['name']}」（{STATUS_LABELS.get(dup['status'])}）と重複している可能性があります。\n"
                    "それでも追加しますか？",
                    parent=self,
                ):
                    return
                data["source"] = "manual"
                db.add_company(data)
        except ValueError as e:
            messagebox.showerror("保存エラー", str(e), parent=self)
            return
        self.destroy()
        self.app.data_changed()
