"""新規メール・フォローメールの一括送信ジョブ."""

from __future__ import annotations

import smtplib
import threading
from dataclasses import dataclass, field
from typing import Callable

from .config import Settings, is_demo
from .db import (
    KIND_FOLLOW, KIND_NEW, RESULT_DRY_RUN, RESULT_FAILED, RESULT_SENT, STATUS_ERROR, Database,
)
from .mailer import DryRunSender, SmtpSender, build_message, compose, render, build_context, signature


@dataclass
class SendOptions:
    kind: str                      # KIND_NEW / KIND_FOLLOW
    template: dict
    dry_run: bool = False          # True: 実際には送らず履歴に「テスト」として記録
    use_ai: bool = False           # Claude で文面を個別化
    thread_reply: bool = False     # フォロー時、前回メールへの返信（Re:）として送る
    interval_sec: float = 30
    daily_limit: int = 100
    max_follow: int | None = None


@dataclass
class SendReport:
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    stopped: bool = False
    aborted_reason: str = ""
    errors: list[str] = field(default_factory=list)


def prepare_mail(company: dict, settings: Settings, opts: SendOptions) -> tuple[str, str]:
    """件名・本文を作る。AI 個別化が有効なら署名以外の本文を Claude で書き換える."""
    if not opts.use_ai:
        return compose(opts.template, company, settings, thread_reply=opts.thread_reply)
    from .ai import personalize_email

    context = build_context(company, settings)
    subject = render(opts.template.get("subject", ""), context)
    body = render(opts.template.get("body", ""), context)
    subject, body = personalize_email(settings.anthropic_api_key, settings.ai_model, subject, body, company)
    if opts.thread_reply and company.get("last_subject"):
        last = company["last_subject"]
        subject = last if last.lower().startswith("re:") else f"Re: {last}"
    return subject, body.rstrip() + "\n" + signature(settings)


def run_send_job(
    db: Database,
    settings: Settings,
    companies: list[dict],
    opts: SendOptions,
    stop: threading.Event,
    progress: Callable[[int, int, str], None],
    sender=None,
) -> SendReport:
    """companies に順番に送信する。

    送信直前に毎回「まだ送信対象か」（送付済み・契約済み・返信あり等になっていないか）と
    1日の送信上限を確認する。
    """
    report = SendReport()
    total = len(companies)
    if is_demo():  # テスト環境では、画面の設定にかかわらず実際には送信しない
        opts.dry_run = True
        sender = None
    if sender is None:
        sender = DryRunSender() if opts.dry_run else SmtpSender(settings)
    try:
        if not opts.dry_run:
            try:
                sender.connect()
            except smtplib.SMTPAuthenticationError as e:
                report.aborted_reason = f"SMTP 認証に失敗しました（ユーザー名・アプリパスワードを確認）: {e}"
                return report
            except (smtplib.SMTPException, OSError) as e:
                report.aborted_reason = f"SMTP サーバーに接続できません: {e}"
                return report

        for index, company in enumerate(companies, 1):
            if stop.is_set():
                report.stopped = True
                break
            name = company.get("name", "")
            if not opts.dry_run and db.count_sent_today() >= opts.daily_limit:
                report.aborted_reason = f"1日の送信上限（{opts.daily_limit}通）に達したため停止しました"
                break
            if not db.is_still_eligible(company["id"], opts.kind, opts.max_follow):
                report.skipped += 1
                progress(index, total, f"スキップ（対象外になっています）: {name}")
                continue
            fresh = db.get_company(company["id"]) or company
            try:
                subject, body = prepare_mail(fresh, settings, opts)
            except Exception as e:  # AI エラーなど
                report.failed += 1
                report.errors.append(f"{name}: {e}")
                progress(index, total, f"文面作成エラー: {name} - {e}")
                continue

            in_reply_to = fresh.get("last_message_id", "") if (opts.kind == KIND_FOLLOW and opts.thread_reply) else ""
            step = int(fresh.get("follow_count") or 0) + 1 if opts.kind == KIND_FOLLOW else 0
            try:
                msg = build_message(settings, fresh["email"], subject, body, in_reply_to=in_reply_to)
                sender.send(msg)
            except smtplib.SMTPRecipientsRefused as e:
                db.record_send(fresh["id"], fresh["email"], opts.kind, subject, body, RESULT_FAILED,
                               error=str(e), step=step, company_name=name)
                db.set_status([fresh["id"]], STATUS_ERROR)
                report.failed += 1
                report.errors.append(f"{name}: 宛先拒否 {e}")
                progress(index, total, f"宛先エラー（送信エラーに変更）: {name}")
                continue
            except smtplib.SMTPAuthenticationError as e:
                report.aborted_reason = f"SMTP 認証エラー: {e}"
                break
            except (smtplib.SMTPException, OSError, ValueError) as e:
                db.record_send(fresh["id"], fresh["email"], opts.kind, subject, body, RESULT_FAILED,
                               error=str(e), step=step, company_name=name)
                report.failed += 1
                report.errors.append(f"{name}: {e}")
                progress(index, total, f"送信エラー: {name} - {e}")
                continue

            result = RESULT_DRY_RUN if opts.dry_run else RESULT_SENT
            db.record_send(fresh["id"], fresh["email"], opts.kind, subject, body, result,
                           message_id=msg["Message-ID"], step=step, company_name=name)
            report.sent += 1
            label = "テスト記録" if opts.dry_run else "送信完了"
            progress(index, total, f"{label}: {name} <{fresh['email']}>")

            if index < total and not opts.dry_run and stop.wait(opts.interval_sec):
                report.stopped = True
                break
    finally:
        sender.close()
    return report


def send_test_mail(settings: Settings, template: dict, company: dict, use_ai: bool = False,
                   thread_reply: bool = False, kind: str = KIND_NEW) -> str:
    """選択中の企業向け文面を、自分のアドレス宛てにテスト送信する."""
    if is_demo():
        raise ValueError("テスト環境では実際のメールは送信しません（本番の画面で「自分宛テスト」をお使いください）")
    to = settings.effective_from_email
    if not to:
        raise ValueError("送信元メールアドレスが設定されていません")
    opts = SendOptions(kind=kind, template=template, use_ai=use_ai, thread_reply=thread_reply)
    subject, body = prepare_mail(company, settings, opts)
    msg = build_message(settings, to, f"[テスト] {subject}", body)
    with SmtpSender(settings) as sender:
        sender.send(msg)
    return to
