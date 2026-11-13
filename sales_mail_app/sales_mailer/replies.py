"""受信トレイ（IMAP）を確認し、返信・配信停止依頼・不達を自動判定する."""

from __future__ import annotations

import email
import imaplib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.utils import getaddresses

from .config import Settings
from .db import (
    FREE_MAIL_DOMAINS, STATUS_ERROR, STATUS_NEW, STATUS_OPTED_OUT, STATUS_REPLIED, STATUS_SENT, Database,
    email_domain, normalize_email,
)

OPTOUT_WORDS = ("配信停止", "配信不要", "送信停止", "配信を停止", "unsubscribe", "今後のご連絡は不要", "営業メールお断り")
BOUNCE_SENDERS = ("mailer-daemon", "postmaster")


@dataclass
class InboxMail:
    from_addr: str
    subject: str
    in_reply_to: str = ""
    references: str = ""
    body: str = ""


@dataclass
class ReplyCheckResult:
    replied: list[str] = field(default_factory=list)
    opted_out: list[str] = field(default_factory=list)
    bounced: list[str] = field(default_factory=list)
    scanned: int = 0


_QUOTE_MARKERS = re.compile(
    r"^(>|＞|-{2,}\s*Original Message|-{2,}\s*元のメッセージ|From:\s|差出人:|送信者:|On .+wrote:|.+wrote:$|"
    r".+(?:のメッセージ|に書きました|さんは書きました)[:：]?$|\d{4}年\d{1,2}月\d{1,2}日.+[:：]$)"
)


def strip_quoted(body: str) -> str:
    """返信メールから引用部分（こちらが送った本文）を取り除く."""
    kept = []
    for line in (body or "").splitlines():
        stripped = line.strip()
        if kept and _QUOTE_MARKERS.match(stripped):
            break
        if stripped.startswith((">", "＞")):
            continue
        if "配信停止" in stripped and "ご返信" in stripped:  # こちらの署名の案内文
            continue
        kept.append(line)
    return "\n".join(kept)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def classify(mails: list[InboxMail], db: Database) -> ReplyCheckResult:
    """受信メールを送信済み企業と突き合わせ、ステータスを更新する."""
    result = ReplyCheckResult(scanned=len(mails))
    companies = db.list_companies(status_filter="all")
    by_email = {c["email"]: c for c in companies if c["email"]}
    by_domain: dict[str, dict] = {}
    for c in companies:
        if c["domain"] and c["status"] != STATUS_NEW:
            by_domain.setdefault(c["domain"], c)
    by_msgid = db.sent_message_ids()
    contacted = (STATUS_SENT, STATUS_REPLIED, STATUS_ERROR)

    for mail in mails:
        sender = normalize_email(mail.from_addr)
        local = sender.split("@", 1)[0] if sender else ""
        if local in BOUNCE_SENDERS or "mailer-daemon" in mail.from_addr.lower():
            for addr in re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", mail.body):
                company = by_email.get(normalize_email(addr))
                if company and company["status"] in (STATUS_SENT, STATUS_NEW):
                    db.set_status([company["id"]], STATUS_ERROR)
                    company["status"] = STATUS_ERROR
                    result.bounced.append(company["name"])
            continue

        company = None
        for ref in re.findall(r"<[^>]+>", f"{mail.in_reply_to} {mail.references}"):
            if ref in by_msgid:
                company = db.get_company(by_msgid[ref])
                break
        if company is None and sender:
            company = by_email.get(sender)
            if company is None:
                domain = email_domain(sender)
                if domain and domain not in FREE_MAIL_DOMAINS:
                    company = by_domain.get(domain)
        if company is None or company["status"] not in contacted + (STATUS_OPTED_OUT,):
            continue

        text = f"{mail.subject}\n{strip_quoted(mail.body)[:3000]}"
        if any(w in text.lower() for w in OPTOUT_WORDS):
            if company["status"] != STATUS_OPTED_OUT:
                db.set_status([company["id"]], STATUS_OPTED_OUT)
                company["status"] = STATUS_OPTED_OUT
                result.opted_out.append(company["name"])
        elif company["status"] in (STATUS_SENT, STATUS_ERROR):
            db.set_status([company["id"]], STATUS_REPLIED)
            company["status"] = STATUS_REPLIED
            result.replied.append(company["name"])
    return result


def _body_text(msg: email.message.Message) -> str:
    parts = msg.walk() if msg.is_multipart() else [msg]
    texts = []
    for part in parts:
        if part.get_content_type() not in ("text/plain", "message/delivery-status", "text/rfc822-headers"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            payload_obj = part.get_payload()
            if isinstance(payload_obj, list):
                texts.extend(str(p) for p in payload_obj)
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            texts.append(payload.decode(charset, "replace"))
        except LookupError:
            texts.append(payload.decode("utf-8", "replace"))
    return "\n".join(texts)


def fetch_inbox(settings: Settings, since_days: int = 30, max_messages: int = 500) -> list[InboxMail]:
    user = settings.effective_imap_user
    if not user:
        raise ValueError("IMAP のユーザー名（またはSMTPユーザー名）が設定されていません")
    since = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
    mails: list[InboxMail] = []
    imap = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
    try:
        imap.login(user, settings.effective_imap_password)
        imap.select("INBOX", readonly=True)
        status, data = imap.search(None, "SINCE", since)
        if status != "OK":
            return mails
        ids = data[0].split()[-max_messages:]
        for msg_id in ids:
            status, parts = imap.fetch(msg_id, "(BODY.PEEK[])")
            if status != "OK" or not parts or not isinstance(parts[0], tuple):
                continue
            msg = email.message_from_bytes(parts[0][1])
            addrs = getaddresses([msg.get("From", "")])
            mails.append(InboxMail(
                from_addr=addrs[0][1] if addrs else "",
                subject=_decode(msg.get("Subject")),
                in_reply_to=msg.get("In-Reply-To", "") or "",
                references=msg.get("References", "") or "",
                body=_body_text(msg)[:20000],
            ))
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return mails


def check_replies(settings: Settings, db: Database, since_days: int = 30) -> ReplyCheckResult:
    return classify(fetch_inbox(settings, since_days), db)


def check_imap_connection(settings: Settings) -> str:
    imap = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
    try:
        imap.login(settings.effective_imap_user, settings.effective_imap_password)
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return f"{settings.imap_host}:{settings.imap_port} に接続・ログインできました。"
