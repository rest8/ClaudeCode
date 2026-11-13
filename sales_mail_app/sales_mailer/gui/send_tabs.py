"""新規メール送信タブ／フォローメールタブ."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from ..campaign import SendOptions, prepare_mail, run_send_job, send_test_mail
from ..db import KIND_FOLLOW, KIND_NEW
from ..mailer import days_since, format_date_jp
from .widgets import DataTable, LogBox, RegionSelector, split_list


class BaseSendTab(ttk.Frame):
    kind = KIND_NEW
    kind_label = "新規"
    columns: list[tuple[str, str, int]] = []

    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        self.templates: list[dict] = []
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        self.conditions = ttk.Frame(paned, padding=(0, 0, 8, 0))
        right = ttk.PanedWindow(paned, orient="vertical")
        paned.add(self.conditions, weight=0)
        paned.add(right, weight=1)

        table_frame = ttk.Frame(right)
        head = ttk.Frame(table_frame)
        head.pack(fill="x")
        self.count_label = ttk.Label(head, text="「対象を抽出」を押してください")
        self.count_label.pack(side="left")
        ttk.Button(head, text="選択解除", command=lambda: self.table.tree.selection_set(())).pack(side="right")
        ttk.Button(head, text="全選択", command=lambda: self.table.select_all()).pack(side="right", padx=4)
        self.table = DataTable(table_frame, self.columns, height=10)
        self.table.pack(fill="both", expand=True, pady=(4, 0))
        self.table.tree.bind("<<TreeviewSelect>>", lambda _e: self.update_preview())
        right.add(table_frame, weight=3)

        preview = ttk.LabelFrame(right, text="プレビュー（選択中の先頭の企業）", padding=6)
        self.preview_subject = tk.StringVar()
        ttk.Entry(preview, textvariable=self.preview_subject, state="readonly").pack(fill="x")
        self.preview_body = tk.Text(preview, height=12, wrap="word")
        self.preview_body.pack(fill="both", expand=True, pady=(4, 0))
        self.preview_body.configure(state="disabled")
        right.add(preview, weight=2)

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", pady=(8, 0))
        row1 = ttk.Frame(bottom)
        row1.pack(fill="x")
        ttk.Label(row1, text="テンプレート").pack(side="left")
        self.template_var = tk.StringVar()
        self.template_combo = ttk.Combobox(row1, textvariable=self.template_var, state="readonly", width=28)
        self.template_combo.pack(side="left", padx=(4, 12))
        self.template_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_preview())
        self.ai_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row1, text="AIで企業ごとに文面を個別化", variable=self.ai_var).pack(side="left")
        ttk.Button(row1, text="AIプレビュー", command=self.ai_preview).pack(side="left", padx=(4, 12))
        self.extra_options(row1)
        self.dry_run_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row1, text="テストモード（実際には送信しない）", variable=self.dry_run_var).pack(side="left")

        row2 = ttk.Frame(bottom)
        row2.pack(fill="x", pady=(6, 0))
        self.send_btn = ttk.Button(row2, text=f"▶ 選択した企業に{self.kind_label}メールを送信", style="Accent.TButton",
                                   command=self.send)
        self.send_btn.pack(side="left")
        self.stop_btn = ttk.Button(row2, text="停止", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        ttk.Button(row2, text="自分宛にテスト送信", command=self.test_send).pack(side="left", padx=(12, 0))
        self.progress = ttk.Progressbar(row2, mode="determinate", length=260)
        self.progress.pack(side="right")
        self.progress_label = ttk.Label(row2, text="")
        self.progress_label.pack(side="right", padx=8)
        self.log = LogBox(bottom, height=5)
        self.log.pack(fill="x", pady=(6, 0))

        self.build_conditions(self.conditions)
        self.load_templates()

    # ---- サブクラスで実装
    def build_conditions(self, frame: ttk.Frame) -> None:
        raise NotImplementedError

    def extra_options(self, row: ttk.Frame) -> None:
        pass

    def fetch_targets(self) -> list[dict]:
        raise NotImplementedError

    def row_values(self, c: dict) -> list:
        raise NotImplementedError

    def send_options(self) -> SendOptions:
        raise NotImplementedError

    # ---- 共通処理
    def on_show(self) -> None:
        self.load_templates()

    def load_templates(self) -> None:
        current = self.template_var.get()
        self.templates = self.app.db.list_templates(self.kind)
        names = [t["name"] for t in self.templates]
        self.template_combo.configure(values=names)
        if current in names:
            self.template_var.set(current)
        elif names:
            self.template_var.set(names[0])
        else:
            self.template_var.set("")

    def current_template(self) -> dict | None:
        name = self.template_var.get()
        return next((t for t in self.templates if t["name"] == name), None)

    def extract(self) -> None:
        targets = self.fetch_targets()
        self.table.set_rows(targets, self.row_values)
        self.table.select_all()
        remaining = max(0, self.app.settings.daily_limit - self.app.db.count_sent_today())
        self.count_label.configure(text=f"送信対象 {len(targets)} 社（本日の残り送信可能数 {remaining} 通）")
        self.update_preview()

    def _set_preview(self, subject: str, body: str) -> None:
        self.preview_subject.set(subject)
        self.preview_body.configure(state="normal")
        self.preview_body.delete("1.0", "end")
        self.preview_body.insert("1.0", body)
        self.preview_body.configure(state="disabled")

    def update_preview(self) -> None:
        rows = self.table.selected()
        template = self.current_template()
        if not rows or not template:
            self._set_preview("", "")
            return
        opts = self.send_options()
        opts.use_ai = False
        subject, body = prepare_mail(rows[0], self.app.settings, opts)
        if self.ai_var.get():
            body = "※ AI個別化は送信時に企業ごとに適用されます（「AIプレビュー」で確認できます）\n\n" + body
        self._set_preview(subject, body)

    def ai_preview(self) -> None:
        rows = self.table.selected()
        if not rows or not self.current_template() or not self.app.ensure_ai_key(self):
            return
        opts = self.send_options()
        opts.use_ai = True
        settings = self.app.settings
        self._set_preview("AIで文面を作成中…", "")

        def work():
            return prepare_mail(rows[0], settings, opts)

        def done(result):
            self._set_preview(*result)

        def error(e):
            self._set_preview("", "")
            messagebox.showerror("AIプレビュー", str(e), parent=self)

        self.app.run_background(work, done, error)

    def test_send(self) -> None:
        rows = self.table.selected()
        template = self.current_template()
        if not template:
            return
        settings = self.app.settings
        if not settings.smtp_user:
            messagebox.showwarning("設定", "設定タブで SMTP（送信）設定を入力してください", parent=self)
            return
        if self.ai_var.get() and not self.app.ensure_ai_key(self):
            return
        company = rows[0] if rows else {"name": "（テスト株式会社）", "follow_count": 0}
        opts = self.send_options()

        def work():
            return send_test_mail(settings, template, company, use_ai=self.ai_var.get(),
                                  thread_reply=opts.thread_reply, kind=self.kind)

        self.app.run_background(
            work,
            lambda to: messagebox.showinfo("テスト送信", f"{to} にテストメールを送信しました。", parent=self),
            lambda e: messagebox.showerror("テスト送信", str(e), parent=self),
        )

    def send(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        rows = self.table.selected()
        template = self.current_template()
        settings = self.app.settings
        if not rows:
            messagebox.showinfo("送信", "送信する企業を選択してください", parent=self)
            return
        if not template:
            messagebox.showwarning("送信", "テンプレートを選択してください", parent=self)
            return
        opts = self.send_options()
        if opts.use_ai and not self.app.ensure_ai_key(self):
            return
        if not opts.dry_run and not settings.smtp_user:
            messagebox.showwarning("設定", "設定タブで SMTP（送信）設定を入力してください", parent=self)
            return
        if not settings.sender_company or not settings.from_name:
            if not messagebox.askyesno(
                "送信者情報",
                "設定タブの「会社名」「送信者名」が未入力です。\n"
                "特定電子メール法で必要な送信者の表示が不足します。このまま送信しますか？",
                parent=self,
            ):
                return
        remaining = max(0, settings.daily_limit - self.app.db.count_sent_today())
        minutes = len(rows) * settings.send_interval_sec / 60
        mode = "【テストモード：実際には送信しません】\n" if opts.dry_run else ""
        msg = (f"{mode}{len(rows)} 社に{self.kind_label}メールを送信します。\n\n"
               f"テンプレート: {template['name']}\n"
               f"AI個別化: {'あり' if opts.use_ai else 'なし'}\n"
               f"送信間隔: {settings.send_interval_sec} 秒（所要時間の目安 約{minutes:.0f}分）\n"
               f"本日の残り送信可能数: {remaining} 通")
        if not opts.dry_run and remaining < len(rows):
            msg += f"\n\n※ 上限に達した時点（{remaining}通）で停止します。"
        if not messagebox.askyesno("送信の確認", msg + "\n\nよろしいですか？", parent=self):
            return

        self.stop_event.clear()
        self.send_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress.configure(maximum=len(rows), value=0)
        self.log.clear()

        def progress(index: int, total: int, text: str) -> None:
            def ui():
                self.progress.configure(value=index)
                self.progress_label.configure(text=f"{index}/{total}")
                self.log.append(text)
                self.app.refresh_stats()
            self.app.call_in_ui(ui)

        def work():
            return run_send_job(self.app.db, settings, rows, opts, self.stop_event, progress)

        def done(report):
            self.send_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            lines = [f"送信: {report.sent} 件", f"失敗: {report.failed} 件",
                     f"スキップ（対象外になっていた企業）: {report.skipped} 件"]
            if report.stopped:
                lines.append("※ 途中で停止しました")
            if report.aborted_reason:
                lines.append(f"※ {report.aborted_reason}")
            self.log.append(" / ".join(lines))
            self.app.data_changed()
            self.extract()
            show = messagebox.showwarning if (report.aborted_reason or report.failed) else messagebox.showinfo
            show("送信結果", "\n".join(lines), parent=self)

        def error(e):
            self.send_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            messagebox.showerror("送信エラー", str(e), parent=self)

        self.worker = self.app.run_background(work, done, error)

    def stop(self) -> None:
        self.stop_event.set()
        self.log.append("停止しています…（送信中の1通が終わると止まります）")


class NewMailTab(BaseSendTab):
    kind = KIND_NEW
    kind_label = "新規"
    columns = [
        ("name", "会社名", 220), ("email", "メールアドレス", 220), ("prefecture", "都道府県", 80),
        ("city", "市区町村", 100), ("industry", "業種", 140), ("contact", "担当者", 90),
    ]

    def build_conditions(self, frame: ttk.Frame) -> None:
        self.region = RegionSelector(frame, height=10)
        self.region.pack(fill="both", expand=True)
        ttk.Label(frame, text="業種・キーワードで絞り込み（任意）").pack(anchor="w", pady=(8, 0))
        self.keyword_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.keyword_var).pack(fill="x")
        ttk.Button(frame, text="対象を抽出", style="Accent.TButton", command=self.extract).pack(fill="x", pady=(10, 6))
        ttk.Label(
            frame,
            text="自動で除外される企業:\n・送付済み／返信あり\n・契約済み／配信停止\n・送信エラー\n"
                 "・過去に送信したアドレスや\n　同じ会社ドメインの企業\n・メールアドレス未登録",
            foreground="#555", justify="left",
        ).pack(anchor="w")

    def fetch_targets(self) -> list[dict]:
        return self.app.db.new_targets(self.region.get(), split_list(self.keyword_var.get()))

    def row_values(self, c: dict) -> list:
        return [c["name"], c["email"], c["prefecture"], c["city"], c["industry"], c["contact_name"]]

    def send_options(self) -> SendOptions:
        s = self.app.settings
        return SendOptions(kind=KIND_NEW, template=self.current_template() or {}, dry_run=self.dry_run_var.get(),
                           use_ai=self.ai_var.get(), interval_sec=s.send_interval_sec, daily_limit=s.daily_limit)


class FollowMailTab(BaseSendTab):
    kind = KIND_FOLLOW
    kind_label = "フォロー"
    columns = [
        ("name", "会社名", 200), ("email", "メールアドレス", 200), ("first", "初回送信", 90), ("last", "最終送信", 90),
        ("days", "経過日数", 70), ("follow", "フォロー回数", 80), ("subject", "前回の件名", 240),
    ]

    def build_conditions(self, frame: ttk.Frame) -> None:
        s = self.app.settings
        grid = ttk.Frame(frame)
        grid.pack(fill="x")
        ttk.Label(grid, text="前回送信から").grid(row=0, column=0, sticky="w")
        self.days_var = tk.IntVar(value=s.follow_after_days)
        ttk.Spinbox(grid, from_=0, to=365, textvariable=self.days_var, width=5).grid(row=0, column=1, padx=4)
        ttk.Label(grid, text="日以上経過").grid(row=0, column=2, sticky="w")
        ttk.Label(grid, text="フォロー上限").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.max_var = tk.IntVar(value=s.max_follow_count)
        ttk.Spinbox(grid, from_=1, to=10, textvariable=self.max_var, width=5).grid(row=1, column=1, padx=4,
                                                                                 pady=(4, 0))
        ttk.Label(grid, text="回まで").grid(row=1, column=2, sticky="w", pady=(4, 0))
        ttk.Label(grid, text="対象").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.count_filter = tk.StringVar(value="すべて")
        ttk.Combobox(grid, textvariable=self.count_filter, state="readonly", width=16,
                     values=["すべて", "0回（初回フォロー）", "1回済み", "2回済み", "3回済み"]).grid(
            row=2, column=1, columnspan=2, sticky="w", padx=4, pady=(4, 0))

        self.region = RegionSelector(frame, height=7)
        self.region.pack(fill="both", expand=True, pady=(8, 0))
        ttk.Button(frame, text="対象を抽出", style="Accent.TButton", command=self.extract).pack(fill="x", pady=(8, 4))
        ttk.Label(frame, text="返信あり・契約済み・配信停止・送信エラーの\n企業は自動で除外されます。",
                  foreground="#555", justify="left").pack(anchor="w")

        box = ttk.LabelFrame(frame, text="返信チェック", padding=6)
        box.pack(fill="x", pady=(8, 0))
        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Label(row, text="過去").pack(side="left")
        self.inbox_days = tk.IntVar(value=30)
        ttk.Spinbox(row, from_=1, to=365, textvariable=self.inbox_days, width=5).pack(side="left", padx=4)
        ttk.Label(row, text="日分の受信メール").pack(side="left")
        ttk.Button(box, text="受信トレイを確認（IMAP）", command=self.check_inbox).pack(fill="x", pady=(4, 0))
        ttk.Label(box, text="返信→「返信あり」、配信停止依頼→「配信停止」、\n不達→「送信エラー」に自動更新します。",
                  foreground="#555", justify="left").pack(anchor="w")

    def extra_options(self, row: ttk.Frame) -> None:
        self.thread_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="前回メールへの返信（Re:）として送る", variable=self.thread_var,
                        command=self.update_preview).pack(side="left", padx=(0, 12))

    def _count_filter_value(self) -> int | None:
        label = self.count_filter.get()
        return None if label == "すべて" else int(label[0])

    def fetch_targets(self) -> list[dict]:
        count = self._count_filter_value()
        targets = self.app.db.follow_targets(int(self.days_var.get()), int(self.max_var.get()),
                                             self.region.get(), count)
        # フォロー回数に応じたテンプレートを自動選択（フォロー1回目／2回目…）
        if count is not None and count < len(self.templates):
            self.template_var.set(self.templates[count]["name"])
        return targets

    def row_values(self, c: dict) -> list:
        return [c["name"], c["email"], format_date_jp(c["first_sent_at"]), format_date_jp(c["last_sent_at"]),
                days_since(c["last_sent_at"]), c["follow_count"], c["last_subject"]]

    def send_options(self) -> SendOptions:
        s = self.app.settings
        return SendOptions(kind=KIND_FOLLOW, template=self.current_template() or {}, dry_run=self.dry_run_var.get(),
                           use_ai=self.ai_var.get(), thread_reply=self.thread_var.get(),
                           interval_sec=s.send_interval_sec, daily_limit=s.daily_limit,
                           max_follow=int(self.max_var.get()))

    def check_inbox(self) -> None:
        settings = self.app.settings
        if not settings.effective_imap_user:
            messagebox.showwarning("設定", "設定タブで IMAP（受信）設定を入力してください", parent=self)
            return
        self.log.append("受信トレイを確認しています…")
        days = int(self.inbox_days.get())

        def work():
            from ..replies import check_replies

            return check_replies(settings, self.app.db, days)

        def done(result):
            lines = [f"確認したメール: {result.scanned} 件",
                     f"返信あり: {len(result.replied)} 件 {'、'.join(result.replied[:10])}",
                     f"配信停止: {len(result.opted_out)} 件 {'、'.join(result.opted_out[:10])}",
                     f"不達（送信エラー）: {len(result.bounced)} 件 {'、'.join(result.bounced[:10])}"]
            self.log.append(" / ".join(lines))
            self.app.data_changed()
            if self.table.rows:
                self.extract()
            messagebox.showinfo("返信チェック", "\n".join(lines), parent=self)

        self.app.run_background(work, done, lambda e: messagebox.showerror("返信チェック", str(e), parent=self))
