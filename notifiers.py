"""
通知バックエンド

サポート:
  - Google Chat (Incoming Webhook)
  - LINE Messaging API (公式 Bot, /v2/bot/message/push)

LINE Notify は 2025年4月で終了したため未対応。
LINE 通知には LINE Developers で「Messaging API channel」を作成し、
チャネルアクセストークンと宛先 (ユーザーID/グループID) を取得してください。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger("hermes.notify")


@dataclass(frozen=True)
class Product:
    sku: str
    title: str
    url: str
    price: str
    keyword_jp: str

    def short_text(self) -> str:
        lines = [f"🛍️ Hermes 入荷: {self.keyword_jp}", self.title]
        if self.price:
            lines.append(self.price)
        lines.append(self.url)
        return "\n".join(lines)


class Notifier(Protocol):
    name: str

    def notify(self, product: Product) -> bool:  # pragma: no cover - protocol
        ...


class GoogleChatNotifier:
    name = "google_chat"

    def __init__(self, webhook_url: str, http):
        self.webhook_url = webhook_url
        self.http = http

    def _card(self, p: Product) -> dict:
        return {
            "cards": [
                {
                    "header": {
                        "title": f"🛍️ Hermes 入荷: {p.keyword_jp}",
                        "subtitle": p.title,
                    },
                    "sections": [
                        {
                            "widgets": [
                                {"keyValue": {"topLabel": "価格", "content": p.price or "-"}},
                                {"keyValue": {"topLabel": "SKU", "content": p.sku}},
                                {
                                    "buttons": [
                                        {
                                            "textButton": {
                                                "text": "商品ページを開く",
                                                "onClick": {"openLink": {"url": p.url}},
                                            }
                                        }
                                    ]
                                },
                            ]
                        }
                    ],
                }
            ],
            "text": p.short_text(),
        }

    def notify(self, product: Product) -> bool:
        try:
            r = self.http.post(self.webhook_url, json=self._card(product), timeout=10)
            if r.status_code >= 300:
                log.warning("Google Chat 失敗 status=%s body=%s", r.status_code, r.text[:200])
                return False
            log.info("[google_chat] 送信: %s", product.keyword_jp)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("Google Chat 通信エラー: %s", e)
            return False


class LineNotifier:
    """LINE Messaging API でプッシュメッセージを送信"""

    name = "line"
    PUSH_URL = "https://api.line.me/v2/bot/message/push"

    def __init__(self, access_token: str, to: str, http):
        self.access_token = access_token
        self.to = to  # userId / groupId / roomId
        self.http = http

    def _payload(self, p: Product) -> dict:
        # Flex Message にすると見栄えが良い。ここではテキスト + ボタンのテンプレート
        return {
            "to": self.to,
            "messages": [
                {
                    "type": "text",
                    "text": p.short_text(),
                },
                {
                    "type": "template",
                    "altText": f"Hermes {p.keyword_jp} 入荷",
                    "template": {
                        "type": "buttons",
                        "title": f"🛍️ {p.keyword_jp}"[:40],
                        "text": (p.title + (f"\n{p.price}" if p.price else ""))[:60],
                        "actions": [
                            {"type": "uri", "label": "商品ページを開く", "uri": p.url}
                        ],
                    },
                },
            ],
        }

    def notify(self, product: Product) -> bool:
        try:
            r = self.http.post(
                self.PUSH_URL,
                json=self._payload(product),
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
            if r.status_code >= 300:
                log.warning("LINE 失敗 status=%s body=%s", r.status_code, r.text[:200])
                return False
            log.info("[line] 送信: %s", product.keyword_jp)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("LINE 通信エラー: %s", e)
            return False


class MultiNotifier:
    """複数の通知先に並列送信し、いずれか成功すれば True"""

    name = "multi"

    def __init__(self, notifiers: list[Notifier]):
        self.notifiers = notifiers

    def notify(self, product: Product) -> bool:
        results = [n.notify(product) for n in self.notifiers]
        return any(results) if results else False
