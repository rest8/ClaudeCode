"""画面（ターミナル版・ウィンドウ版）から共通で使う処理."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Settings, is_demo
from .db import (
    STATUS_CONTRACTED, STATUS_ERROR, STATUS_LABELS, STATUS_NEW, STATUS_OPTED_OUT, STATUS_REPLIED, STATUS_SENT,
    Database,
)
from .research import EmailCrawler, Prospect, ResearchError, build_queries, enrich_emails, run_places_research

METHOD_GOOGLE = "google"
METHOD_CLAUDE = "claude"
METHOD_LABELS = {METHOD_GOOGLE: "Google マップ（Places API）", METHOD_CLAUDE: "AI Web検索（Claude）"}
ADDED = "added"  # 調査画面で「リストに追加」した企業の印


def judge_label(p: Prospect) -> str:
    if p.existing_status == ADDED:
        return "✓ 追加済み"
    if p.existing_status:
        return f"登録済み（{STATUS_LABELS.get(p.existing_status, p.existing_status)}）"
    return "新規" if p.email else "新規（メール未取得）"


def mark_existing(db: Database, prospect: Prospect) -> None:
    """登録済み（送付済み・契約済みなど）の企業なら印を付ける."""
    dup = db.find_duplicate(prospect.name, prospect.email, prospect.website, prospect.place_id, prospect.prefecture)
    if dup:
        prospect.existing_status, prospect.existing_id = dup["status"], dup["id"]


def run_research(
    db: Database,
    settings: Settings,
    method: str,
    keywords: list[str],
    prefectures: list[str],
    cities: list[str],
    max_per_query: int,
    restrict_to_region: bool,
    crawl: bool,
    progress: Callable[[str], None],
    stop: threading.Event,
    on_results: Callable[[list[Prospect]], None] | None = None,
    on_update: Callable[[Prospect], None] | None = None,
) -> list[Prospect]:
    """地域×業種で企業を調査し、登録済みかどうかを判定、必要ならメールアドレスも取得する."""
    if not prefectures and not cities:
        raise ResearchError("調査する都道府県を選ぶか、市区町村を入力してください")
    if not keywords:
        raise ResearchError("業種・キーワードを入力してください（例: 製造業）")
    if is_demo():
        from . import demo

        progress("テスト環境のため、API を使わずにサンプルの調査結果を表示します（費用はかかりません）")
        prospects = demo.sample_prospects(db, keywords, prefectures, cities, min(max_per_query, 8))
        for p in prospects:
            mark_existing(db, p)
        progress(f"{len(prospects)} 件見つかりました（登録済み {sum(1 for p in prospects if p.existing_status)} 件）")
        if on_results:
            on_results(prospects)
        progress("調査が完了しました")
        return prospects
    if method == METHOD_GOOGLE:
        prospects = run_places_research(settings.google_api_key, keywords, prefectures, cities, max_per_query,
                                        restrict_to_region, progress, stop)
    else:
        from .ai import research_with_claude

        def exclude_names(pref: str) -> list[str]:
            rows = db.list_companies(status_filter="all", prefectures=[pref] if pref else None, limit=150)
            return [r["name"] for r in rows]

        queries = build_queries(keywords, prefectures, cities)
        prospects = research_with_claude(settings.anthropic_api_key, settings.ai_model, queries,
                                         min(max_per_query, 20), exclude_names, progress, stop)
        if restrict_to_region and prefectures:
            prospects = [p for p in prospects if not p.prefecture or p.prefecture in prefectures]
    for p in prospects:
        mark_existing(db, p)
    progress(f"{len(prospects)} 件見つかりました（登録済み {sum(1 for p in prospects if p.existing_status)} 件）")
    if on_results:
        on_results(prospects)
    if crawl and not stop.is_set():
        crawler = EmailCrawler(settings.crawl_max_pages, settings.crawl_timeout_sec)

        def found(p: Prospect) -> None:
            mark_existing(db, p)  # 取得したアドレスが登録済み企業のものなら対象外にする
            if on_update:
                on_update(p)

        enrich_emails(prospects, crawler, progress, stop, found)
    progress("調査を停止しました" if stop.is_set() else "調査が完了しました")
    return prospects


@dataclass
class AddResult:
    added: int = 0
    skipped_existing: int = 0
    skipped_no_mail: int = 0

    def text(self) -> str:
        return (f"リストに追加: {self.added} 件 / 登録済みのためスキップ: {self.skipped_existing} 件 / "
                f"メール未取得のためスキップ: {self.skipped_no_mail} 件")


def add_prospects(db: Database, prospects: list[Prospect], include_no_email: bool = False) -> AddResult:
    result = AddResult()
    for p in prospects:
        if p.existing_status:
            result.skipped_existing += 1
            continue
        if not p.email and not include_no_email:
            result.skipped_no_mail += 1
            continue
        mark_existing(db, p)
        if p.existing_status:
            result.skipped_existing += 1
            continue
        p.existing_id = db.add_company(p.to_company())
        p.existing_status = ADDED
        result.added += 1
    return result


def stats_text(db: Database, settings: Settings) -> str:
    s = db.stats()
    prefix = "【テスト環境・送信なし】 " if is_demo() else ""
    return (f"{prefix}未送付 {s[STATUS_NEW]}  送付済み {s[STATUS_SENT]}  返信あり {s[STATUS_REPLIED]}  "
            f"契約済み {s[STATUS_CONTRACTED]}  配信停止 {s[STATUS_OPTED_OUT]}  エラー {s[STATUS_ERROR]}  │  "
            f"本日の送信 {s['today']}/{settings.daily_limit}通")


def send_confirmation(kind_label: str, count: int, template_name: str, use_ai: bool, dry_run: bool,
                      settings: Settings, remaining: int) -> str:
    minutes = count * settings.send_interval_sec / 60
    lines = []
    if dry_run:
        lines.append("【テストモード：実際には送信しません】")
    lines += [
        f"{count} 社に{kind_label}メールを送信します。",
        "",
        f"テンプレート: {template_name}",
        f"AI個別化: {'あり' if use_ai else 'なし'}",
        f"送信間隔: {settings.send_interval_sec} 秒（所要時間の目安 約{minutes:.0f}分）",
        f"本日の残り送信可能数: {remaining} 通",
    ]
    if not dry_run and remaining < count:
        lines += ["", f"※ 上限に達した時点（{remaining}通）で停止します。"]
    return "\n".join(lines)


def missing_sender_info(settings: Settings) -> bool:
    return not settings.sender_company or not settings.from_name


@dataclass
class ImportReport:
    recognized: list[str] = field(default_factory=list)
    total: int = 0
    added: int = 0
    updated: int = 0
    skipped: int = 0
    no_email: int = 0
    bad_domain: list[str] = field(default_factory=list)
    domain_unchecked: bool = False

    def text(self) -> str:
        lines = [f"読み込んだ行: {self.total} 件（認識した列: {'、'.join(self.recognized)}）", "",
                 f"追加: {self.added} 件", f"既存企業のステータス更新: {self.updated} 件",
                 f"スキップ（登録済み・会社名なし）: {self.skipped} 件"]
        if self.no_email:
            lines.append(f"メールアドレスが無い・形式が正しくない: {self.no_email} 件（送信対象外）")
        if self.bad_domain:
            lines.append(f"存在しないドメインのため送信対象外: {len(self.bad_domain)} 件")
            lines += [f"  ・{x}" for x in self.bad_domain[:10]]
            if len(self.bad_domain) > 10:
                lines.append(f"  ほか {len(self.bad_domain) - 10} 件")
        if self.domain_unchecked:
            lines.append("※ インターネットに接続できなかったため、ドメインの確認はしていません。")
        return "\n".join(lines)


def import_companies(db: Database, path: str | Path, status: str = STATUS_NEW, check_domains: bool = True,
                     progress: Callable[[str], None] | None = None, checker=None) -> ImportReport:
    """Excel / CSV を取り込む。

    未送付として取り込むときは、メールアドレスのドメインが存在するかを無料で確認し、
    存在しないもの（AI が作った架空のアドレスなど）は「送信エラー」にして送信対象から外す。
    """
    from .csv_io import read_companies_file
    from .db import STATUS_ERROR, normalize_email

    path = Path(path)
    rows, recognized = read_companies_file(path)
    report = ImportReport(recognized=recognized, total=len(rows))
    source = "excel" if path.suffix.lower() in (".xlsx", ".xlsm") else "csv"
    for row in rows:
        row.setdefault("source", source)
    emails = [normalize_email(r.get("email")) for r in rows]
    report.no_email = sum(1 for r, e in zip(rows, emails) if r.get("name") and not e)
    if check_domains and status == STATUS_NEW and not is_demo():
        from .email_check import DomainChecker

        checker = checker or DomainChecker()
        if progress:
            progress("メールアドレスのドメインを確認しています…")
        results = checker.check_emails([e for e in emails if e],
                                       (lambda i, n: progress(f"ドメインの確認 {i}/{n}")) if progress else None)
        report.domain_unchecked = not checker.online()
        for row, email in zip(rows, emails):
            if email and results.get(email) is False and not row.get("status"):
                row["status"] = STATUS_ERROR
                note = "メールのドメインが存在しないため送信対象外（取り込み時の確認）"
                row["notes"] = f"{row['notes']} / {note}" if row.get("notes") else note
                report.bad_domain.append(f"{row.get('name', '')} <{email}>")
    result = db.import_rows(rows, status=status)
    report.added, report.updated, report.skipped = result.added, result.updated, result.skipped
    return report
