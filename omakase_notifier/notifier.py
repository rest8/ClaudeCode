"""通知チャネル: メール / LINE Messaging API / Webhook。"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Iterable

import requests

from .config import EmailConfig, LineConfig, NotificationConfig, WebhookConfig
from .scraper import AvailabilitySlot

LOGGER = logging.getLogger(__name__)


def _format_message(target_name: str, slots: Iterable[AvailabilitySlot]) -> tuple[str, str]:
    lines = [f"【Omakase 空席通知】{target_name}", "", "新たに空席が出ました:"]
    for s in sorted(slots, key=lambda x: x.key()):
        lines.append(f"  ・{s.describe()}")
    body = "\n".join(lines)
    subject = f"[Omakase] {target_name} に空席が出ました"
    return subject, body


class Notifier:
    def __init__(self, config: NotificationConfig) -> None:
        self._config = config

    def notify(self, target_name: str, slots: Iterable[AvailabilitySlot]) -> None:
        slots = list(slots)
        if not slots:
            return
        subject, body = _format_message(target_name, slots)
        LOGGER.info("通知送信: %s (%d件)", target_name, len(slots))

        if self._config.email.enabled:
            try:
                self._send_email(self._config.email, subject, body)
            except Exception as e:  # noqa: BLE001 - 通知失敗で本体を落とさない
                LOGGER.error("メール通知に失敗: %s", e)

        if self._config.line.enabled:
            try:
                self._send_line(self._config.line, body)
            except Exception as e:
                LOGGER.error("LINE通知に失敗: %s", e)

        if self._config.webhook.enabled:
            try:
                self._send_webhook(self._config.webhook, subject, body)
            except Exception as e:
                LOGGER.error("Webhook通知に失敗: %s", e)

    @staticmethod
    def _send_email(cfg: EmailConfig, subject: str, body: str) -> None:
        if not cfg.to_addrs:
            LOGGER.warning("メール宛先が未設定のためスキップ")
            return
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = cfg.from_addr or cfg.username
        msg["To"] = ", ".join(cfg.to_addrs)
        msg.set_content(body)

        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=20) as smtp:
            smtp.ehlo()
            if cfg.use_tls:
                smtp.starttls()
                smtp.ehlo()
            if cfg.username:
                smtp.login(cfg.username, cfg.password)
            smtp.send_message(msg)

    @staticmethod
    def _send_line(cfg: LineConfig, body: str) -> None:
        if not cfg.channel_access_token or not cfg.to:
            LOGGER.warning("LINE設定が不完全のためスキップ")
            return
        resp = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Authorization": f"Bearer {cfg.channel_access_token}",
                "Content-Type": "application/json",
            },
            json={
                "to": cfg.to,
                "messages": [{"type": "text", "text": body[:4900]}],
            },
            timeout=15,
        )
        resp.raise_for_status()

    @staticmethod
    def _send_webhook(cfg: WebhookConfig, subject: str, body: str) -> None:
        if not cfg.url:
            return
        resp = requests.post(
            cfg.url,
            json={"subject": subject, "text": body},
            timeout=15,
        )
        resp.raise_for_status()
