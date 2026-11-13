"""新規開拓（地域調査）タブ."""

from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from ..db import STATUS_LABELS
from ..research import (
    EmailCrawler, Prospect, ResearchError, build_queries, enrich_emails, run_places_research,
)
from .widgets import DataTable, LogBox, RegionSelector, split_list

COLUMNS = [
    ("judge", "判定", 150), ("name", "会社名", 220), ("email", "メールアドレス", 210), ("prefecture", "都道府県", 80),
    ("city", "市区町村", 100), ("industry", "業種", 120), ("phone", "電話番号", 120), ("website", "Webサイト", 220),
]

METHOD_GOOGLE = "google"
METHOD_CLAUDE = "claude"


def judge_label(p: Prospect) -> str:
    if p.existing_status == "added":
        return "✓ リストに追加済み"
    if p.existing_status:
        return f"登録済み（{STATUS_LABELS.get(p.existing_status, p.existing_status)}）"
    return "新規" if p.email else "新規（メール未取得）"


class ResearchTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        self.prospects: list[Prospect] = []
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned, padding=(0, 0, 8, 0))
        right = ttk.Frame(paned)
        paned.add(left, weight=0)
        paned.add(right, weight=1)

        # ---- 条件
        self.region = RegionSelector(left, height=12)
        self.region.pack(fill="both", expand=True)

        form = ttk.Frame(left)
        form.pack(fill="x", pady=(8, 0))
        ttk.Label(form, text="市区町村（任意・カンマ区切り）").pack(anchor="w")
        self.cities_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.cities_var).pack(fill="x")
        ttk.Label(form, text="業種・キーワード（カンマ区切り）").pack(anchor="w", pady=(6, 0))
        self.keywords_var = tk.StringVar(value="")
        ttk.Entry(form, textvariable=self.keywords_var).pack(fill="x")
        ttk.Label(form, text="例: 製造業, 建設会社, 税理士事務所", foreground="#666").pack(anchor="w")

        ttk.Label(form, text="調査方法").pack(anchor="w", pady=(8, 0))
        self.method_var = tk.StringVar(value=METHOD_GOOGLE)
        ttk.Radiobutton(form, text="Google マップ（Places API）", value=METHOD_GOOGLE,
                        variable=self.method_var).pack(anchor="w")
        ttk.Radiobutton(form, text="AI Web検索（Claude）", value=METHOD_CLAUDE,
                        variable=self.method_var).pack(anchor="w")

        opts = ttk.Frame(form)
        opts.pack(fill="x", pady=(6, 0))
        ttk.Label(opts, text="1検索あたりの最大件数").pack(side="left")
        self.max_var = tk.IntVar(value=20)
        ttk.Spinbox(opts, from_=5, to=60, increment=5, textvariable=self.max_var, width=5).pack(side="left", padx=4)
        self.crawl_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text="公式サイトからメールアドレスを取得する", variable=self.crawl_var).pack(anchor="w")
        self.restrict_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text="選択した都道府県以外の結果を除外する", variable=self.restrict_var).pack(anchor="w")

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(10, 0))
        self.start_btn = ttk.Button(btns, text="▶ 調査開始", style="Accent.TButton", command=self.start)
        self.start_btn.pack(side="left", fill="x", expand=True)
        self.stop_btn = ttk.Button(btns, text="停止", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(4, 0))

        # ---- 結果
        top = ttk.Frame(right)
        top.pack(fill="x")
        self.result_label = ttk.Label(top, text="調査結果（登録済み＝送付済み・契約済みなどの企業は自動で対象外になります）")
        self.result_label.pack(side="left")
        self.table = DataTable(right, COLUMNS, height=18)
        self.table.pack(fill="both", expand=True, pady=(6, 6))
        self.table.tree.bind("<Double-1>", self._open_site)
        actions = ttk.Frame(right)
        actions.pack(fill="x")
        ttk.Button(actions, text="新規の企業をすべて選択", command=self.select_new).pack(side="left")
        self.include_no_email = tk.BooleanVar(value=False)
        ttk.Checkbutton(actions, text="メール未取得の企業も追加する", variable=self.include_no_email).pack(
            side="left", padx=10)
        ttk.Button(actions, text="選択した企業をリストに追加", style="Accent.TButton",
                   command=self.add_selected).pack(side="right")
        self.log = LogBox(right, height=7)
        self.log.pack(fill="x", pady=(6, 0))

    # ---------------------------------------------------------------- 表示
    def _render(self) -> None:
        self.table.set_rows(
            self.prospects,
            lambda p: [judge_label(p), p.name, p.email, p.prefecture, p.city, p.industry, p.phone, p.website],
            iid_key="",
            tags=lambda p: ["muted"] if p.existing_status else ([] if p.email else ["warn"]),
        )
        new = sum(1 for p in self.prospects if not p.existing_status)
        with_mail = sum(1 for p in self.prospects if not p.existing_status and p.email)
        self.result_label.configure(
            text=f"調査結果 {len(self.prospects)} 件（新規 {new} 件／うちメール取得 {with_mail} 件、"
                 f"登録済みのため対象外 {len(self.prospects) - new} 件）")

    def _open_site(self, _event=None) -> None:
        rows = self.table.selected()
        if rows and rows[0].website:
            webbrowser.open(rows[0].website)

    def _mark_existing(self, prospects: list[Prospect]) -> None:
        db = self.app.db
        for p in prospects:
            dup = db.find_duplicate(p.name, p.email, p.website, p.place_id, p.prefecture)
            if dup:
                p.existing_status, p.existing_id = dup["status"], dup["id"]

    # ---------------------------------------------------------------- 実行
    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        prefs = self.region.get()
        cities = split_list(self.cities_var.get())
        keywords = split_list(self.keywords_var.get())
        if not prefs and not cities:
            messagebox.showwarning("地域の選択", "調査する都道府県を選択するか、市区町村を入力してください", parent=self)
            return
        if not keywords:
            messagebox.showwarning("業種・キーワード", "業種・キーワードを入力してください（例: 製造業）", parent=self)
            return
        settings = self.app.settings
        method = self.method_var.get()
        if method == METHOD_GOOGLE and not settings.google_api_key:
            messagebox.showwarning("APIキー", "設定タブで Google Places API キーを入力してください", parent=self)
            return
        if method == METHOD_CLAUDE and not self.app.ensure_ai_key(self):
            return
        queries = build_queries(keywords, prefs, cities)
        max_per_query = max(1, int(self.max_var.get() or 20))
        if method == METHOD_CLAUDE:
            max_per_query = min(max_per_query, 20)
        if len(queries) > 20 and not messagebox.askyesno(
            "確認", f"{len(queries)} 回の検索を行います（API利用料がかかります）。続けますか？", parent=self):
            return

        self.stop_event.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.log.clear()
        self.prospects = []
        self._render()
        crawl = self.crawl_var.get()
        restrict = self.restrict_var.get()

        def progress(text: str) -> None:
            self.app.call_in_ui(self.log.append, text)

        def work():
            if method == METHOD_GOOGLE:
                prospects = run_places_research(settings.google_api_key, keywords, prefs, cities, max_per_query,
                                                restrict, progress, self.stop_event)
            else:
                from ..ai import research_with_claude

                def exclude_names(pref: str) -> list[str]:
                    rows = self.app.db.list_companies(status_filter="all", prefectures=[pref] if pref else None,
                                                      limit=150)
                    return [r["name"] for r in rows]

                prospects = research_with_claude(settings.anthropic_api_key, settings.ai_model, queries,
                                                 max_per_query, exclude_names, progress, self.stop_event)
                if restrict and prefs:
                    prospects = [p for p in prospects if not p.prefecture or p.prefecture in prefs]
            self._mark_existing(prospects)
            self.app.call_in_ui(self._show_results, prospects)
            if crawl and not self.stop_event.is_set():
                crawler = EmailCrawler(settings.crawl_max_pages, settings.crawl_timeout_sec)

                def on_found(p: Prospect) -> None:
                    dup = self.app.db.find_duplicate(p.name, p.email, p.website, p.place_id, p.prefecture)
                    if dup:
                        p.existing_status, p.existing_id = dup["status"], dup["id"]
                    self.app.call_in_ui(self._render)

                enrich_emails(prospects, crawler, progress, self.stop_event, on_found)
            return prospects

        def done(prospects) -> None:
            self._finish("調査を停止しました" if self.stop_event.is_set() else "調査が完了しました")
            self._render()

        def error(e: Exception) -> None:
            self._finish(f"エラー: {e}")
            messagebox.showerror("調査エラー", str(e), parent=self)

        self.worker = self.app.run_background(work, done, error)

    def _show_results(self, prospects: list[Prospect]) -> None:
        self.prospects = prospects
        self._render()
        self.log.append(f"{len(prospects)} 件見つかりました。")

    def _finish(self, message: str) -> None:
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.log.append(message)

    def stop(self) -> None:
        self.stop_event.set()
        self.log.append("停止しています…")

    # ---------------------------------------------------------------- 追加
    def select_new(self) -> None:
        tree = self.table.tree
        iids = [iid for iid, p in self.table.rows.items()
                if not p.existing_status and (p.email or self.include_no_email.get())]
        tree.selection_set(iids)

    def add_selected(self) -> None:
        selected = self.table.selected()
        if not selected:
            messagebox.showinfo("追加", "追加する企業を選択してください", parent=self)
            return
        db = self.app.db
        added = skipped_existing = skipped_no_mail = 0
        for p in selected:
            if p.existing_status:
                skipped_existing += 1
                continue
            if not p.email and not self.include_no_email.get():
                skipped_no_mail += 1
                continue
            dup = db.find_duplicate(p.name, p.email, p.website, p.place_id, p.prefecture)
            if dup:
                p.existing_status, p.existing_id = dup["status"], dup["id"]
                skipped_existing += 1
                continue
            p.existing_id = db.add_company(p.to_company())
            p.existing_status = "added"
            added += 1
        self._render()
        self.app.data_changed()
        messagebox.showinfo(
            "追加",
            f"リストに追加: {added} 件\n登録済みのためスキップ: {skipped_existing} 件\n"
            f"メール未取得のためスキップ: {skipped_no_mail} 件",
            parent=self,
        )
