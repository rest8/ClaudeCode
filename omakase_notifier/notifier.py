"""特定の配信先（メール/LINE/Webhook）へ通知を送信する。"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Iterable

import requests

from .config import NotificationCredentials
from .scraper import AvailabilitySlot
from .subscribers import Subscriber

LOGGER = logging.getLogger(__name__)


def format_message(
    subscriber_label: str,
    restaurant_name: str,
    restaurant_url: str,
    slots: Iterable[AvailabilitySlot],
) -> tuple[str, str]:
    lines = [
        f"【Omakase 空席通知】{restaurant_name}",
        "",
        f"宛先: {subscriber_label}",
        "",
        "新たに空席が出ました:",
    ]
    for s in sorted(slots, key=lambda x: x.key()):
        lines.append(f"  ・{s.describe()}")
    lines.append("")
    lines.append(f"予約ページ: {restaurant_url}")
    body = "\n".join(lines)
    subject = f"[Omakase] {restaurant_name} に空席が出ました"
    return subject, body


class Notifier:
    def __init__(self, credentials: NotificationCredentials) -> None:
        self._creds = credentials

    def notify(
        self,
        subscriber: Subscriber,
        restaurant_name: str,
        restaurant_url: str,
        slots: list[AvailabilitySlot],
    ) -> bool:
        if not slots:
            return False
        subject, body = format_message(
            subscriber.label or subscriber.id, restaurant_name, restaurant_url, slots
        )
        LOGGER.info(
            "通知送信: %s (%s) -> %s (%d件)",
            subscriber.id,
            subscriber.channel,
            restaurant_name,
            len(slots),
        )
        try:
            if subscriber.channel == "email":
                self._send_email(subscriber.destination, subject, body)
            elif subscriber.channel == "line":
                self._send_line(subscriber.destination, body)
            elif subscriber.channel == "webhook":
                self._send_webhook(subscriber.destination, subject, body)
            else:
                LOGGER.warning("未対応チャネル: %s", subscriber.channel)
                return False
            return True
        except Exception as e:  # noqa: BLE001 - 通知失敗で本体を落とさない
            LOGGER.error("通知失敗: %s (%s) - %s", subscriber.id, subscriber.channel, e)
            return False

    def _send_email(self, to_addr: str, subject: str, body: str) -> None:
        cfg = self._creds.email
        if not cfg.smtp_host:
            raise RuntimeError("SMTP設定が未構成です (config.yaml notifications.email)")
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = cfg.from_addr or cfg.username
        msg["To"] = to_addr
        msg.set_content(body)

        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=20) as smtp:
            smtp.ehlo()
            if cfg.use_tls:
                smtp.starttls()
                smtp.ehlo()
            if cfg.username:
                smtp.login(cfg.username, cfg.password)
            smtp.send_message(msg)

    def _send_line(self, to_id: str, body: str) -> None:
        token = self._creds.line.channel_access_token
        if not token:
            raise RuntimeError("LINE設定が未構成です (config.yaml notifications.line)")
        resp = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "to": to_id,
                "messages": [{"type": "text", "text": body[:4900]}],
            },
            timeout=15,
        )
        resp.raise_for_status()

    @staticmethod
    def _send_webhook(url: str, subject: str, body: str) -> None:
        if not url:
            raise RuntimeError("webhook URL が空です")
        resp = requests.post(url, json={"subject": subject, "text": body}, timeout=15)
        resp.raise_for_status()
