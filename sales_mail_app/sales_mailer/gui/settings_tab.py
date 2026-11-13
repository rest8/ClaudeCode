"""設定タブ."""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from dataclasses import fields, replace
from tkinter import messagebox, ttk

from ..config import Settings, data_dir
from ..mailer import check_smtp_connection
from ..replies import check_imap_connection
from .widgets import labeled_entry

AI_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]


class SettingsTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        self.vars: dict[str, tk.Variable] = {}

        canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: self._wheel(canvas, e), add="+")

        inner.columnconfigure(0, weight=1)
        inner.columnconfigure(1, weight=1)
        left = ttk.Frame(inner)
        right = ttk.Frame(inner)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right.grid(row=0, column=1, sticky="nsew")

        # ---- SMTP
        smtp = self._section(left, "メール送信（SMTP）")
        labeled_entry(smtp, 0, "SMTPサーバー", self._var("smtp_host"), 28)
        labeled_entry(smtp, 1, "ポート", self._var("smtp_port"), 8)
        ttk.Label(smtp, text="暗号化").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Combobox(smtp, textvariable=self._var("smtp_security"), values=["starttls", "ssl", "none"],
                     state="readonly", width=10).grid(row=2, column=1, sticky="w", pady=3)
        labeled_entry(smtp, 3, "ユーザー名", self._var("smtp_user"), 28, hint="通常はメールアドレス")
        labeled_entry(smtp, 4, "パスワード", self._var("smtp_password"), 28, show="•")
        ttk.Label(smtp, text="Gmail の場合: smtp.gmail.com / 587 / starttls。Googleアカウントで2段階認証を有効にし、"
                             "「アプリパスワード」を発行して入力してください（通常のパスワードは使えません）。",
                  foreground="#666", justify="left", wraplength=520).grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Button(smtp, text="接続テスト", command=self.test_smtp).grid(row=6, column=0, sticky="w", pady=(6, 0))

        # ---- IMAP
        imap = self._section(left, "返信チェック（IMAP 受信）")
        labeled_entry(imap, 0, "IMAPサーバー", self._var("imap_host"), 28)
        labeled_entry(imap, 1, "ポート", self._var("imap_port"), 8, hint="SSL（通常 993）")
        labeled_entry(imap, 2, "ユーザー名", self._var("imap_user"), 28, hint="空欄ならSMTPと同じ")
        labeled_entry(imap, 3, "パスワード", self._var("imap_password"), 28, show="•", hint="空欄ならSMTPと同じ")
        ttk.Button(imap, text="接続テスト", command=self.test_imap).grid(row=4, column=0, sticky="w", pady=(6, 0))

        # ---- 送信ルール
        rule = self._section(left, "送信ルール")
        labeled_entry(rule, 0, "送信間隔（秒）", self._var("send_interval_sec"), 8, hint="迷惑メール判定を避けるため30秒以上推奨")
        labeled_entry(rule, 1, "1日の送信上限（通）", self._var("daily_limit"), 8, hint="Gmail無料版は1日500通が上限")
        labeled_entry(rule, 2, "フォローまでの日数", self._var("follow_after_days"), 8, hint="前回送信からこの日数後に対象")
        labeled_entry(rule, 3, "フォロー上限（回）", self._var("max_follow_count"), 8)

        # ---- 送信者情報
        sender = self._section(right, "送信者情報（署名・特定電子メール法の表示）")
        labeled_entry(sender, 0, "送信者名", self._var("from_name"), 30, hint="例: 山田 太郎")
        labeled_entry(sender, 1, "会社名", self._var("sender_company"), 30)
        labeled_entry(sender, 2, "送信元アドレス", self._var("from_email"), 30, hint="空欄ならSMTPユーザー名")
        labeled_entry(sender, 3, "返信先（Reply-To）", self._var("reply_to"), 30, hint="任意")
        labeled_entry(sender, 4, "住所", self._var("sender_address"), 30)
        labeled_entry(sender, 5, "電話番号", self._var("sender_phone"), 30)
        labeled_entry(sender, 6, "WebサイトURL", self._var("sender_url"), 30)
        ttk.Label(sender, text="配信停止の案内文").grid(row=7, column=0, sticky="nw", pady=3)
        self.optout_text = tk.Text(sender, height=4, width=46, wrap="word")
        self.optout_text.grid(row=7, column=1, columnspan=2, sticky="we", pady=3)

        # ---- API
        api = self._section(right, "企業調査・AI")
        labeled_entry(api, 0, "Google Places APIキー", self._var("google_api_key"), 30, show="•",
                      hint="地域調査（Googleマップ）で使用")
        labeled_entry(api, 1, "Anthropic APIキー", self._var("anthropic_api_key"), 30, show="•",
                      hint="AI個別化・AI Web調査で使用")
        ttk.Label(api, text="AIモデル").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Combobox(api, textvariable=self._var("ai_model"), values=AI_MODELS, width=22).grid(
            row=2, column=1, sticky="w", pady=3)
        labeled_entry(api, 3, "サイト巡回ページ数", self._var("crawl_max_pages"), 8, hint="1社あたり（メール取得時）")
        labeled_entry(api, 4, "タイムアウト（秒）", self._var("crawl_timeout_sec"), 8)

        # ---- データ
        data = self._section(right, "データ")
        ttk.Label(data, text=str(data_dir()), foreground="#555").grid(row=0, column=0, sticky="w")
        ttk.Button(data, text="フォルダを開く", command=self.open_data_dir).grid(row=0, column=1, sticky="e", padx=8)
        ttk.Label(data, text="企業リスト・送信履歴（sales_mailer.db）と設定（settings.json）を保存しています。\n"
                             "バックアップはこのフォルダをコピーしてください。パスワード類も含まれるため取扱いに注意してください。",
                  foreground="#666", justify="left", wraplength=560).grid(row=1, column=0, columnspan=2, sticky="w",
                                                                          pady=(4, 0))

        bottom = ttk.Frame(inner)
        bottom.grid(row=1, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bottom, text="設定を保存", style="Accent.TButton", command=self.save).pack(side="right")
        self.load()

    @staticmethod
    def _wheel(canvas: tk.Canvas, event) -> None:
        if str(event.widget).startswith(str(canvas)):
            canvas.yview_scroll(int(-event.delta / 120) or (-1 if event.delta > 0 else 1), "units")

    @staticmethod
    def _section(parent, title: str) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text=title, padding=10)
        frame.pack(fill="x", pady=(0, 10))
        frame.columnconfigure(1, weight=1)
        return frame

    def _var(self, name: str) -> tk.Variable:
        if name not in self.vars:
            self.vars[name] = tk.StringVar()
        return self.vars[name]

    def load(self) -> None:
        s = self.app.settings
        for name, var in self.vars.items():
            var.set(str(getattr(s, name)))
        self.optout_text.delete("1.0", "end")
        self.optout_text.insert("1.0", s.optout_text)

    def collect(self) -> Settings:
        values = {}
        for f in fields(Settings):
            if f.name not in self.vars:
                continue
            raw = self.vars[f.name].get().strip()
            if f.type in ("int", int):
                try:
                    values[f.name] = int(raw)
                except ValueError as e:
                    raise ValueError(f"数値を入力してください: {raw!r}") from e
            else:
                values[f.name] = raw
        values["optout_text"] = self.optout_text.get("1.0", "end").strip()
        return replace(self.app.settings, **values)

    def save(self) -> bool:
        try:
            settings = self.collect()
        except ValueError as e:
            messagebox.showerror("設定", str(e), parent=self)
            return False
        self.app.update_settings(settings)
        messagebox.showinfo("設定", "設定を保存しました。", parent=self)
        return True

    def _test(self, fn, title: str) -> None:
        try:
            settings = self.collect()
        except ValueError as e:
            messagebox.showerror(title, str(e), parent=self)
            return
        self.app.run_background(
            lambda: fn(settings),
            lambda msg: messagebox.showinfo(title, msg, parent=self),
            lambda e: messagebox.showerror(title, f"接続に失敗しました:\n{e}", parent=self),
        )

    def test_smtp(self) -> None:
        self._test(check_smtp_connection, "SMTP接続テスト")

    def test_imap(self) -> None:
        self._test(check_imap_connection, "IMAP接続テスト")

    def open_data_dir(self) -> None:
        path = str(data_dir())
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
