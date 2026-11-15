"""自動送信（取り込んだ企業への新規メールと、送付済み企業へのフォローメールをまとめて送る）.

費用がかからないよう、AI による文面の個別化は使わず、テンプレートの差し込みだけで送る。
1日の送信上限の範囲で、フォローメール（反応を待っている企業）を先に、残りで新規メールを送る。
返信あり・契約済み・配信停止・送信エラーの企業は自動で除外される。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from .campaign import SendOptions, run_send_job
from .config import Settings, is_demo
from .db import KIND_FOLLOW, KIND_NEW, Database


@dataclass
class AutoSendPlan:
    new_template: dict | None
    new_targets: list[dict]
    follow_groups: list[tuple[dict, list[dict]]]  # (テンプレート, 企業)
    remaining: int

    @property
    def follow_total(self) -> int:
        return sum(len(companies) for _, companies in self.follow_groups)

    def rows(self) -> list[dict]:
        """画面の一覧用（送る順）."""
        items = []
        budget = self.remaining
        for template, companies in self.follow_groups:
            for c in companies:
                items.append({"kind": f"フォロー{c['follow_count'] + 1}回目", "company": c, "template": template,
                              "within": budget > 0})
                budget -= 1
        for c in self.new_targets:
            items.append({"kind": "新規", "company": c, "template": self.new_template, "within": budget > 0})
            budget -= 1
        return items

    def summary(self) -> str:
        within = min(self.remaining, self.follow_total + len(self.new_targets))
        text = (f"送信予定: フォロー {self.follow_total} 社・新規 {len(self.new_targets)} 社"
                f"（本日の残り {self.remaining} 通 → 今日送るのは {within} 通）")
        if not self.new_template:
            text += "　※ 新規メールのテンプレートがありません"
        return text


@dataclass
class AutoSendResult:
    sent_follow: int = 0
    sent_new: int = 0
    failed: int = 0
    skipped: int = 0
    stopped: bool = False
    aborted_reason: str = ""
    inbox_message: str = ""
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    def text(self) -> str:
        label = "テスト記録" if self.dry_run else "送信"
        lines = [f"{label}: フォロー {self.sent_follow} 通・新規 {self.sent_new} 通", f"失敗: {self.failed} 件",
                 f"スキップ（対象外になっていた企業）: {self.skipped} 件"]
        if self.inbox_message:
            lines.insert(0, self.inbox_message)
        if self.stopped:
            lines.append("※ 途中で停止しました")
        if self.aborted_reason:
            lines.append(f"※ {self.aborted_reason}")
        if self.errors:
            lines += ["", "エラー内容:"] + self.errors[:10]
        return "\n".join(lines)


def new_template(db: Database, settings: Settings) -> dict | None:
    templates = db.list_templates(KIND_NEW)
    chosen = next((t for t in templates if t["id"] == settings.auto_new_template_id), None)
    return chosen or (templates[0] if templates else None)


def make_plan(db: Database, settings: Settings) -> AutoSendPlan:
    remaining = max(0, settings.daily_limit - db.count_sent_today())
    template = new_template(db, settings)
    new_targets = db.new_targets() if template else []
    groups: list[tuple[dict, list[dict]]] = []
    if settings.auto_follow:
        follow_templates = db.list_templates(KIND_FOLLOW)
        if follow_templates:
            by_step: dict[int, list[dict]] = {}
            for c in db.follow_targets(settings.follow_after_days, settings.max_follow_count):
                by_step.setdefault(min(int(c["follow_count"]), len(follow_templates) - 1), []).append(c)
            groups = [(follow_templates[i], cs) for i, cs in sorted(by_step.items())]
    return AutoSendPlan(template, new_targets, groups, remaining)


def run_auto_send(db: Database, settings: Settings, progress: Callable[[str], None],
                  stop: threading.Event | None = None, dry_run: bool = False, sender_factory=None) -> AutoSendResult:
    """自動送信を1回実行する（画面の「今すぐ実行」と、タスク スケジューラからの起動で共通）."""
    stop = stop or threading.Event()
    dry_run = dry_run or is_demo()
    result = AutoSendResult(dry_run=dry_run)

    if settings.auto_check_inbox and settings.effective_imap_user and not is_demo():
        progress("受信トレイを確認しています（返信・配信停止・不達の企業を除外）…")
        try:
            from .replies import check_replies

            inbox = check_replies(settings, db, 30)
            result.inbox_message = (f"受信トレイ: 返信あり {len(inbox.replied)} 件・配信停止 {len(inbox.opted_out)} 件・"
                                    f"不達 {len(inbox.bounced)} 件を反映しました")
            progress(result.inbox_message)
        except Exception as e:  # noqa: BLE001 - 受信確認に失敗しても送信は続ける
            progress(f"受信トレイを確認できませんでした（送信は続けます）: {e}")

    plan = make_plan(db, settings)
    progress(plan.summary())
    budget = plan.remaining
    if budget <= 0:
        result.aborted_reason = f"本日の送信上限（{settings.daily_limit}通）に達しているため送りません"
        return result

    jobs: list[tuple[str, dict, list[dict]]] = [(KIND_FOLLOW, t, cs) for t, cs in plan.follow_groups]
    if plan.new_template and plan.new_targets:
        jobs.append((KIND_NEW, plan.new_template, plan.new_targets))

    first = True
    for kind, template, companies in jobs:
        if budget <= 0 or stop.is_set():
            break
        batch = companies[:budget]
        if not first and stop.wait(settings.send_interval_sec):
            result.stopped = True
            break
        first = False
        label = "フォロー" if kind == KIND_FOLLOW else "新規"
        progress(f"{label}メール（テンプレート「{template['name']}」）を {len(batch)} 社に送ります")
        opts = SendOptions(kind=kind, template=template, dry_run=dry_run, use_ai=False,
                           thread_reply=kind == KIND_FOLLOW, interval_sec=settings.send_interval_sec,
                           daily_limit=settings.daily_limit, max_follow=settings.max_follow_count)
        report = run_send_job(db, settings, batch, opts, stop, lambda i, n, msg: progress(f"  [{i}/{n}] {msg}"),
                              sender=sender_factory() if sender_factory else None)
        if kind == KIND_FOLLOW:
            result.sent_follow += report.sent
        else:
            result.sent_new += report.sent
        result.failed += report.failed
        result.skipped += report.skipped
        result.errors += report.errors
        budget -= report.sent
        if report.stopped:
            result.stopped = True
            break
        if report.aborted_reason:
            result.aborted_reason = report.aborted_reason
            break
    progress("自動送信が終わりました: " + result.text().replace("\n", " / "))
    return result
