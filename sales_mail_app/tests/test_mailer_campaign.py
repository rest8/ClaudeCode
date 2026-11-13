import smtplib
import threading

from sales_mailer.campaign import SendOptions, run_send_job
from sales_mailer.db import (
    KIND_FOLLOW, KIND_NEW, RESULT_DRY_RUN, RESULT_FAILED, RESULT_SENT, STATUS_CONTRACTED, STATUS_ERROR,
    STATUS_NEW, STATUS_OPTED_OUT, STATUS_REPLIED, STATUS_SENT,
)
from sales_mailer.mailer import DryRunSender, build_message, compose, render
from sales_mailer.replies import InboxMail, classify, strip_quoted

TEMPLATE = {"subject": "{会社名}様へのご案内", "body": "{会社名}\n{担当者名}様\n\n{送信者会社名}の{送信者名}です。{未知}"}


def test_render_keeps_unknown_placeholders():
    assert render("{会社名}様 {未知}", {"会社名": "A社"}) == "A社様 {未知}"


def test_compose_adds_signature_and_optout(settings):
    subject, body = compose(TEMPLATE, {"name": "A社"}, settings)
    assert subject == "A社様へのご案内"
    assert body.startswith("A社\nご担当者様")
    assert "株式会社マイコープ" in body and "配信停止" in body and "TEL: 03-0000-0000" in body


def test_compose_thread_reply_subject(settings):
    subject, _ = compose(TEMPLATE, {"name": "A社", "last_subject": "ご案内"}, settings, thread_reply=True)
    assert subject == "Re: ご案内"
    subject, _ = compose(TEMPLATE, {"name": "A社", "last_subject": "Re: ご案内"}, settings, thread_reply=True)
    assert subject == "Re: ご案内"


def test_build_message_headers(settings):
    msg = build_message(settings, "info@a.co.jp", "件名", "本文", in_reply_to="<m1@x>")
    assert msg["To"] == "info@a.co.jp"
    assert "me@mycorp.co.jp" in msg["From"]
    assert msg["In-Reply-To"] == "<m1@x>"
    assert msg["Message-ID"].endswith("@mycorp.co.jp>")
    assert msg["List-Unsubscribe"].startswith("<mailto:me@mycorp.co.jp")


def _progress(*_):
    pass


def test_send_job_marks_sent_and_skips_ineligible(db, settings):
    a = db.add_company({"name": "A社", "email": "info@a.co.jp"})
    b = db.add_company({"name": "B社", "email": "info@b.co.jp"})
    targets = db.new_targets()
    db.set_status([b], STATUS_CONTRACTED)  # 抽出後に契約済みになった
    sender = DryRunSender()
    opts = SendOptions(kind=KIND_NEW, template=TEMPLATE, interval_sec=0)
    report = run_send_job(db, settings, targets, opts, threading.Event(), _progress, sender=sender)
    assert (report.sent, report.skipped) == (1, 1)
    assert [m["To"] for m in sender.sent] == ["info@a.co.jp"]
    assert db.get_company(a)["status"] == STATUS_SENT
    assert db.new_targets() == []  # 送付済みは次回から対象外


def test_dry_run_job_records_but_keeps_status(db, settings):
    a = db.add_company({"name": "A社", "email": "info@a.co.jp"})
    opts = SendOptions(kind=KIND_NEW, template=TEMPLATE, dry_run=True)
    report = run_send_job(db, settings, db.new_targets(), opts, threading.Event(), _progress)
    assert report.sent == 1
    assert db.get_company(a)["status"] == STATUS_NEW
    assert db.list_send_log()[0]["result"] == RESULT_DRY_RUN


def test_daily_limit_stops_job(db, settings):
    for i in range(3):
        db.add_company({"name": f"{i}社", "email": f"info@c{i}.co.jp"})
    opts = SendOptions(kind=KIND_NEW, template=TEMPLATE, interval_sec=0, daily_limit=2)
    report = run_send_job(db, settings, db.new_targets(), opts, threading.Event(), _progress, sender=DryRunSender())
    assert report.sent == 2
    assert "上限" in report.aborted_reason


class RefusingSender(DryRunSender):
    def send(self, msg):
        raise smtplib.SMTPRecipientsRefused({msg["To"]: (550, b"no such user")})


def test_recipient_refused_marks_error(db, settings):
    a = db.add_company({"name": "A社", "email": "info@a.co.jp"})
    opts = SendOptions(kind=KIND_NEW, template=TEMPLATE, interval_sec=0)
    report = run_send_job(db, settings, db.new_targets(), opts, threading.Event(), _progress,
                          sender=RefusingSender())
    assert report.failed == 1
    assert db.get_company(a)["status"] == STATUS_ERROR
    assert db.list_send_log()[0]["result"] == RESULT_FAILED


def test_follow_job_threads_reply(db, settings):
    a = db.add_company({"name": "A社", "email": "info@a.co.jp"})
    db.record_send(a, "info@a.co.jp", KIND_NEW, "ご案内", "本文", RESULT_SENT, message_id="<first@mycorp.co.jp>")
    sender = DryRunSender()
    opts = SendOptions(kind=KIND_FOLLOW, template=TEMPLATE, thread_reply=True, interval_sec=0, max_follow=2)
    targets = db.follow_targets(min_days=0, max_follow=2)
    report = run_send_job(db, settings, targets, opts, threading.Event(), _progress, sender=sender)
    assert report.sent == 1
    msg = sender.sent[0]
    assert msg["Subject"] == "Re: ご案内"
    assert msg["In-Reply-To"] == "<first@mycorp.co.jp>"
    assert db.get_company(a)["follow_count"] == 1


def test_strip_quoted():
    body = "承知しました。検討します。\n\n2026年11月5日(水) 10:00 山田 <me@x.jp>:\n> 今後不要な場合は「配信停止」とご返信ください。"
    assert "配信停止" not in strip_quoted(body)


def test_classify_reply_optout_and_bounce(db):
    a = db.add_company({"name": "A社", "email": "info@a.co.jp"})
    b = db.add_company({"name": "B社", "email": "info@b.co.jp"})
    c = db.add_company({"name": "C社", "email": "info@c.co.jp"})
    d = db.add_company({"name": "D社", "email": "info@d.co.jp"})
    for cid, email in ((a, "info@a.co.jp"), (b, "info@b.co.jp"), (c, "info@c.co.jp"), (d, "info@d.co.jp")):
        db.record_send(cid, email, KIND_NEW, "ご案内", "本文", RESULT_SENT, message_id=f"<{cid}@mycorp.co.jp>")
    mails = [
        # 担当者の個人アドレスから返信（同じ会社ドメイン）。引用部分の「配信停止」は無視する
        InboxMail("tanaka@a.co.jp", "Re: ご案内", body="ぜひ話を聞きたいです。\n> 「配信停止」とご返信ください"),
        InboxMail("info@b.co.jp", "Re: ご案内", body="配信停止をお願いします"),
        InboxMail("MAILER-DAEMON@mx.example.net", "Undelivered", body="Delivery to info@c.co.jp failed"),
        InboxMail("someone@gmail.com", "Re: ご案内", in_reply_to=f"<{d}@mycorp.co.jp>", body="詳細ください"),
    ]
    result = classify(mails, db)
    assert db.get_company(a)["status"] == STATUS_REPLIED
    assert db.get_company(b)["status"] == STATUS_OPTED_OUT
    assert db.get_company(c)["status"] == STATUS_ERROR
    assert db.get_company(d)["status"] == STATUS_REPLIED
    assert result.replied == ["A社", "D社"] and result.opted_out == ["B社"] and result.bounced == ["C社"]
    # 返信あり・配信停止・エラーはフォロー対象外
    assert db.follow_targets(min_days=0, max_follow=2) == []
