"""テンプレート編集タブ."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ..db import KIND_FOLLOW, KIND_NEW
from ..mailer import PLACEHOLDERS, signature

KIND_LABELS = {KIND_NEW: "新規メール", KIND_FOLLOW: "フォローメール"}
LABEL_KINDS = {v: k for k, v in KIND_LABELS.items()}


class TemplatesTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        self.current_id: int | None = None

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned, padding=(0, 0, 8, 0))
        right = ttk.Frame(paned)
        paned.add(left, weight=0)
        paned.add(right, weight=1)

        self.listbox = ttk.Treeview(left, columns=("kind",), show="tree headings", height=18, selectmode="browse")
        self.listbox.heading("#0", text="テンプレート名")
        self.listbox.heading("kind", text="種類")
        self.listbox.column("#0", width=200)
        self.listbox.column("kind", width=110)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<TreeviewSelect>>", lambda _e: self.load_selected())
        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="新規作成", command=self.new).pack(side="left")
        ttk.Button(btns, text="複製", command=self.duplicate).pack(side="left", padx=4)
        ttk.Button(btns, text="削除", command=self.delete).pack(side="left")

        form = ttk.Frame(right)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="テンプレート名").grid(row=0, column=0, sticky="w", pady=3)
        self.name_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.name_var).grid(row=0, column=1, sticky="we", pady=3)
        ttk.Label(form, text="種類").grid(row=1, column=0, sticky="w", pady=3)
        self.kind_var = tk.StringVar(value=KIND_LABELS[KIND_NEW])
        ttk.Combobox(form, textvariable=self.kind_var, values=list(KIND_LABELS.values()), state="readonly",
                     width=16).grid(row=1, column=1, sticky="w", pady=3)
        ttk.Label(form, text="件名").grid(row=2, column=0, sticky="w", pady=3)
        self.subject_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.subject_var).grid(row=2, column=1, sticky="we", pady=3)
        ttk.Label(right, text="本文").pack(anchor="w", pady=(6, 0))
        self.body = tk.Text(right, wrap="word", height=16, undo=True)
        self.body.pack(fill="both", expand=True)

        help_text = "差し込み項目（クリックで本文に挿入）:"
        ttk.Label(right, text=help_text).pack(anchor="w", pady=(6, 2))
        chips = ttk.Frame(right)
        chips.pack(fill="x")
        for i, (key, desc) in enumerate(PLACEHOLDERS.items()):
            b = ttk.Button(chips, text=f"{{{key}}}", command=lambda k=key: self._insert(k))
            b.grid(row=i // 6, column=i % 6, sticky="we", padx=2, pady=2)
        ttk.Label(right, text="※ 署名と配信停止の案内（特定電子メール法の表示）は、設定タブの送信者情報から自動で末尾に付きます。",
                  foreground="#555").pack(anchor="w", pady=(6, 0))
        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=(6, 0))
        ttk.Button(actions, text="保存", style="Accent.TButton", command=self.save).pack(side="right")
        ttk.Button(actions, text="署名を確認", command=self.show_signature).pack(side="right", padx=6)
        self.reload()

    def on_show(self) -> None:
        self.reload(keep=self.current_id)

    def reload(self, keep: int | None = None) -> None:
        self.listbox.delete(*self.listbox.get_children())
        templates = self.app.db.list_templates()
        for t in templates:
            self.listbox.insert("", "end", iid=str(t["id"]), text=t["name"], values=(KIND_LABELS.get(t["kind"]),))
        target = keep or (templates[0]["id"] if templates else None)
        if target and self.listbox.exists(str(target)):
            self.listbox.selection_set(str(target))

    def load_selected(self) -> None:
        sel = self.listbox.selection()
        if not sel:
            return
        t = self.app.db.get_template(int(sel[0]))
        if not t:
            return
        self.current_id = t["id"]
        self.name_var.set(t["name"])
        self.kind_var.set(KIND_LABELS.get(t["kind"], KIND_LABELS[KIND_NEW]))
        self.subject_var.set(t["subject"])
        self.body.delete("1.0", "end")
        self.body.insert("1.0", t["body"])

    def _insert(self, key: str) -> None:
        self.body.insert("insert", f"{{{key}}}")
        self.body.focus_set()

    def new(self) -> None:
        self.current_id = None
        self.listbox.selection_set(())
        self.name_var.set("新しいテンプレート")
        self.subject_var.set("")
        self.body.delete("1.0", "end")
        self.body.insert("1.0", "{会社名}\n{担当者名}様\n\n")

    def duplicate(self) -> None:
        if not self.current_id:
            return
        self.current_id = None
        self.name_var.set(self.name_var.get() + "（コピー）")
        self.save()

    def save(self) -> None:
        try:
            self.current_id = self.app.db.save_template(
                self.current_id, self.name_var.get().strip(), LABEL_KINDS.get(self.kind_var.get(), KIND_NEW),
                self.subject_var.get(), self.body.get("1.0", "end").rstrip(),
            )
        except ValueError as e:
            messagebox.showerror("保存", str(e), parent=self)
            return
        self.reload(keep=self.current_id)
        messagebox.showinfo("保存", "テンプレートを保存しました。", parent=self)

    def delete(self) -> None:
        if not self.current_id:
            return
        if not messagebox.askyesno("削除", f"「{self.name_var.get()}」を削除しますか？", parent=self):
            return
        self.app.db.delete_template(self.current_id)
        self.current_id = None
        self.reload()

    def show_signature(self) -> None:
        messagebox.showinfo("自動で付く署名", signature(self.app.settings).strip() or "（未設定）", parent=self)
