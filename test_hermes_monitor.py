"""hermes_monitor の単体テスト (ネットワーク不要)"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from hermes_monitor import (
    GoogleChatNotifier,
    HermesClient,
    Product,
    StockMonitor,
    TARGETS,
)


def test_targets_cover_six_models():
    expected = {"ケリー", "バーキン", "ピコタン", "コンスタンス", "エヴリン", "アッカド"}
    assert expected == set(TARGETS.keys())


def test_extract_products_filters_unavailable():
    payload = {
        "items": [
            {
                "sku": "H001",
                "title": "Kelly 25",
                "url": "/jp/ja/product/kelly-25/",
                "price": {"formatted": "¥1,500,000"},
                "available": True,
            },
            {
                "sku": "H002",
                "title": "Kelly 28",
                "url": "/jp/ja/product/kelly-28/",
                "price": {"formatted": "¥1,800,000"},
                "available": False,
            },
        ]
    }
    products = HermesClient._extract_products(payload, "ケリー")
    assert len(products) == 1
    assert products[0].sku == "H001"
    assert products[0].url.startswith("https://www.hermes.com")
    assert products[0].price == "¥1,500,000"


def test_product_chat_card_has_link_and_text():
    p = Product(
        sku="H001",
        title="Kelly 25",
        url="https://www.hermes.com/jp/ja/product/kelly-25/",
        price="¥1,500,000",
        keyword_jp="ケリー",
    )
    card = p.chat_card()
    assert "ケリー" in card["text"]
    assert p.url in card["text"]
    btn = card["cards"][0]["sections"][0]["widgets"][-1]["buttons"][0]
    assert btn["textButton"]["onClick"]["openLink"]["url"] == p.url


def test_should_notify_cooldown():
    monitor = StockMonitor(
        client=MagicMock(),
        notifier=MagicMock(),
        targets={},
        interval=1,
    )
    now = time.time()
    assert monitor._should_notify("SKU1", now) is True
    assert monitor._should_notify("SKU1", now + 10) is False
    assert monitor._should_notify("SKU1", now + monitor._cooldown_sec + 1) is True


def test_notifier_sends_card():
    session = MagicMock()
    session.post.return_value = MagicMock(status_code=200, text="OK")
    notifier = GoogleChatNotifier("https://example.invalid/webhook", session)
    p = Product(
        sku="H001",
        title="Birkin 30",
        url="https://www.hermes.com/jp/ja/product/birkin-30/",
        price="¥2,500,000",
        keyword_jp="バーキン",
    )
    notifier.notify(p)
    session.post.assert_called_once()
    args, kwargs = session.post.call_args
    assert args[0] == "https://example.invalid/webhook"
    assert "バーキン" in kwargs["json"]["text"]


def test_search_returns_empty_on_429():
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=429, text="Too Many Requests")
    client = HermesClient(locale="jp/ja", session=session)
    assert client.search("kelly") == []


def test_tick_skips_noise_and_notifies_match():
    session = MagicMock()
    session.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "items": [
                # マッチする
                {
                    "sku": "H100",
                    "title": "Kelly 25",
                    "url": "/jp/ja/product/kelly-25/",
                    "available": True,
                },
                # ノイズ (kelly を含まない)
                {
                    "sku": "H101",
                    "title": "Wallet",
                    "url": "/jp/ja/product/wallet/",
                    "available": True,
                },
            ]
        },
    )
    client = HermesClient(locale="jp/ja", session=session)
    notifier = MagicMock()
    monitor = StockMonitor(
        client=client,
        notifier=notifier,
        targets={"ケリー": "kelly"},
        interval=1,
    )
    monitor._tick()
    assert notifier.notify.call_count == 1
    notified = notifier.notify.call_args[0][0]
    assert notified.sku == "H100"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
