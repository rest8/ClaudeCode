"""テンプレートの差し込み、メール組み立て、SMTP 送信."""

from __future__ import annotations

import re
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from .config import Settings
from .db import parse_time

PLACEHOLDERS = {
    "会社名": "宛先の会社名",
    "担当者名": "担当者名（未登録なら「ご担当者」）",
    "業種": "業種",
    "都道府県": "都道府県",
    "市区町村": "市区町村",
    "地域": "都道府県＋市区町村",
    "送信者名": "設定の送信者名",
    "送信者会社名": "設定の会社名",
    "前回件名": "前回送ったメールの件名",
    "前回送信日": "前回送信日（例: 11月5日）",
    "フォロー回数": "今回が何回目のフォローか",
}

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def build_context(company: dict, settings: Settings) -> dict[str, str]:
    last_sent = parse_time(company.get("last_sent_at"))
    return {
        "会社名": company.get("name", ""),
        "担当者名": company.get("contact_name") or "ご担当者",
        "業種": company.get("industry", ""),
        "都道府県": company.get("prefecture", ""),
        "市区町村": company.get("city", ""),
        "地域": f"{company.get('prefecture', '')}{company.get('city', '')}",
        "送信者名": settings.from_name,
        "送信者会社名": settings.sender_company,
        "前回件名": company.get("last_subject", ""),
        "前回送信日": f"{last_sent.month}月{last_sent.day}日" if last_sent else "先日",
        "フォロー回数": str(int(company.get("follow_count") or 0) + 1),
    }


def render(text: str, context: dict[str, str]) -> str:
    """{会社名} のような差し込み項目を置換する。未知の項目はそのまま残す."""
    return _PLACEHOLDER_RE.sub(lambda m: str(context.get(m.group(1), m.group(0))), text or "")


def signature(settings: Settings) -> str:
    """署名と配信停止の案内（特定電子メール法の表示事項）."""
    lines = ["", "--"]
    for value in (settings.sender_company, settings.from_name, settings.sender_address):
        if value:
            lines.append(value)
    if settings.sender_phone:
        lines.append(f"TEL: {settings.sender_phone}")
    if settings.effective_from_email:
        lines.append(f"Mail: {settings.effective_from_email}")
    if settings.sender_url:
        lines.append(settings.sender_url)
    if settings.optout_text:
        lines.extend(["", settings.optout_text])
    return "\n".join(lines)


def compose(template: dict, company: dict, settings: Settings, thread_reply: bool = False) -> tuple[str, str]:
    """テンプレートから件名・本文（署名付き）を作る."""
    context = build_context(company, settings)
    subject = render(template.get("subject", ""), context)
    if thread_reply and company.get("last_subject"):
        last = company["last_subject"]
        subject = last if last.lower().startswith("re:") else f"Re: {last}"
    body = render(template.get("body", ""), context).rstrip() + "\n" + signature(settings)
    return subject, body


def build_message(
    settings: Settings,
    to_email: str,
    subject: str,
    body: str,
    in_reply_to: str = "",
) -> EmailMessage:
    from_email = settings.effective_from_email
    if not from_email:
        raise ValueError("送信元メールアドレスが設定されていません（設定タブ）")
    msg = EmailMessage()
    msg["From"] = formataddr((settings.from_name, from_email)) if settings.from_name else from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    domain = from_email.split("@", 1)[1] if "@" in from_email else None
    msg["Message-ID"] = make_msgid(domain=domain)
    if settings.reply_to:
        msg["Reply-To"] = settings.reply_to
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg["List-Unsubscribe"] = f"<mailto:{settings.reply_to or from_email}?subject=%E9%85%8D%E4%BF%A1%E5%81%9C%E6%AD%A2>"
    msg.set_content(body, charset="utf-8")
    return msg


class SmtpSender:
    """SMTP 接続を保持して連続送信する。切断されたら1回だけ再接続する."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._smtp: smtplib.SMTP | None = None

    def connect(self) -> None:
        s = self.settings
        timeout = 30
        if s.smtp_security == "ssl":
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=timeout,
                                                  context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=timeout)
            smtp.ehlo()
            if s.smtp_security == "starttls":
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        self._smtp = smtp

    def send(self, msg: EmailMessage) -> None:
        if self._smtp is None:
            self.connect()
        try:
            self._smtp.send_message(msg)  # type: ignore[union-attr]
        except smtplib.SMTPServerDisconnected:
            self.connect()
            self._smtp.send_message(msg)  # type: ignore[union-attr]

    def close(self) -> None:
        if self._smtp is not None:
            try:
                self._smtp.quit()
            except Exception:
                pass
            self._smtp = None

    def __enter__(self) -> "SmtpSender":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class DryRunSender:
    """テストモード用。実際には送信せず、送ったものを記録するだけ."""

    def __init__(self, settings: Settings | None = None):
        self.sent: list[EmailMessage] = []

    def connect(self) -> None:
        pass

    def send(self, msg: EmailMessage) -> None:
        self.sent.append(msg)

    def close(self) -> None:
        pass

    def __enter__(self) -> "DryRunSender":
        return self

    def __exit__(self, *exc) -> None:
        pass


def check_smtp_connection(settings: Settings) -> str:
    sender = SmtpSender(settings)
    sender.connect()
    sender.close()
    return f"{settings.smtp_host}:{settings.smtp_port} に接続・ログインできました。"


def format_date_jp(value: str | None) -> str:
    dt = parse_time(value)
    return dt.strftime("%Y/%m/%d") if dt else ""


def days_since(value: str | None, now: datetime | None = None) -> int | None:
    dt = parse_time(value)
    if not dt:
        return None
    return ((now or datetime.now()) - dt).days
