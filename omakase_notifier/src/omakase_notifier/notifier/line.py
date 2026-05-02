from __future__ import annotations

import logging

import requests

from ..config import LineConfig

log = logging.getLogger(__name__)

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


class LineNotifier:
    """Sends a push message via the LINE Messaging API.

    Note: requires the recipient (line_user_id) to have already added the
    bot as a friend in their LINE app. The channel access token is taken
    from config.line.channel_access_token.
    """

    def __init__(self, config: LineConfig):
        self.config = config

    def send(self, to_user_id: str, text: str) -> None:
        if not self.config.configured:
            raise RuntimeError("LINE Messaging API is not configured")
        payload = {
            "to": to_user_id,
            "messages": [{"type": "text", "text": text[:4900]}],
        }
        headers = {
            "Authorization": f"Bearer {self.config.channel_access_token}",
            "Content-Type": "application/json",
        }
        resp = requests.post(LINE_PUSH_URL, headers=headers, json=payload, timeout=15)
        if resp.status_code >= 300:
            raise RuntimeError(
                f"LINE push failed: {resp.status_code} {resp.text}"
            )
        log.info("LINE message sent to %s", to_user_id)
