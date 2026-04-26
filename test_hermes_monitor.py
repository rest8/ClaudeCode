"""hermes_monitor / notifiers / http_client の単体テスト (ネットワーク不要)"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from hermes_monitor import HermesClient, StockMonitor, TARGETS, build_notifier, parse_args
from notifiers import (
    GoogleChatNotifier,
    LineNotifier,
    MultiNotifier,
    Product,
)


# ---- ターゲット ----------------------------------------------------------
def test_targets_cover_six_models():
    expected = {"ケリー", "バーキン", "ピコタン", "コンスタンス", "エヴリン", "アッカド"}
    assert expected == set(TARGETS.keys())


# ---- 抽出 ----------------------------------------------------------------
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


def test_extract_from_html_next_data():
    html = """
    <html><body>
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"items":[
      {"sku":"H999","title":"Birkin 30","url":"/jp/ja/product/birkin-30/","available":true,"price":{"formatted":"¥3,000,000"}}
    ]}}}
    </script>
    </body></html>
    """
    products = HermesClient._extract_from_html(html, "バーキン")
    assert len(products) == 1
    assert products[0].sku == "H999"


# ---- Product / 通知 -----------------------------------------------------
def test_product_short_text_includes_link():
    p = Product(
        sku="H001",
        title="Kelly 25",
        url="https://www.hermes.com/jp/ja/product/kelly-25/",
        price="¥1,500,000",
        keyword_jp="ケリー",
    )
    txt = p.short_text()
    assert "ケリー" in txt
    assert p.url in txt
    assert p.price in txt


def test_google_chat_notifier_sends_card():
    http = MagicMock()
    http.post.return_value = MagicMock(status_code=200, text="OK")
    n = GoogleChatNotifier("https://chat.example/webhook", http)
    p = Product("H001", "Birkin 30", "https://www.hermes.com/p/birkin", "¥2,500,000", "バーキン")
    assert n.notify(p) is True
    args, kwargs = http.post.call_args
    assert args[0] == "https://chat.example/webhook"
    assert "バーキン" in kwargs["json"]["text"]
    btn = kwargs["json"]["cards"][0]["sections"][0]["widgets"][-1]["buttons"][0]
    assert btn["textButton"]["onClick"]["openLink"]["url"] == p.url


def test_line_notifier_sends_push():
    http = MagicMock()
    http.post.return_value = MagicMock(status_code=200, text="OK")
    n = LineNotifier("TOKEN_XYZ", "U1234", http)
    p = Product("H001", "Picotin Lock 18", "https://www.hermes.com/p/picotin", "¥600,000", "ピコタン")
    assert n.notify(p) is True
    args, kwargs = http.post.call_args
    assert args[0] == "https://api.line.me/v2/bot/message/push"
    assert kwargs["headers"]["Authorization"] == "Bearer TOKEN_XYZ"
    body = kwargs["json"]
    assert body["to"] == "U1234"
    assert body["messages"][0]["type"] == "text"
    assert "ピコタン" in body["messages"][0]["text"]
    # ボタンテンプレートに商品 URL が入る
    tpl = body["messages"][1]["template"]
    assert tpl["actions"][0]["uri"] == p.url


def test_line_notifier_failure_returns_false():
    http = MagicMock()
    http.post.return_value = MagicMock(status_code=401, text="invalid token")
    n = LineNotifier("BAD", "U1", http)
    p = Product("H1", "T", "https://x", "", "ケリー")
    assert n.notify(p) is False


def test_multi_notifier_succeeds_if_any_succeeds():
    a = MagicMock(); a.notify.return_value = False
    b = MagicMock(); b.notify.return_value = True
    multi = MultiNotifier([a, b])
    p = Product("H1", "T", "https://x", "", "ケリー")
    assert multi.notify(p) is True
    a.notify.assert_called_once()
    b.notify.assert_called_once()


def test_multi_notifier_all_fail_returns_false():
    a = MagicMock(); a.notify.return_value = False
    b = MagicMock(); b.notify.return_value = False
    assert MultiNotifier([a, b]).notify(
        Product("H1", "T", "https://x", "", "ケリー")
    ) is False


# ---- StockMonitor -------------------------------------------------------
def _make_monitor(targets=None, search_result=None) -> tuple[StockMonitor, MagicMock]:
    http = MagicMock()
    http.jitter = 0.0
    client = MagicMock()
    if search_result is not None:
        client.search.return_value = search_result
    notifier = MagicMock()
    notifier.notify.return_value = True
    monitor = StockMonitor(
        client=client,
        notifier=notifier,
        targets=targets or {"ケリー": "kelly"},
        interval=1,
        http=http,
    )
    return monitor, notifier


def test_should_notify_cooldown():
    monitor, _ = _make_monitor()
    now = time.time()
    assert monitor._should_notify("SKU1", now) is True
    assert monitor._should_notify("SKU1", now + 10) is False
    assert monitor._should_notify("SKU1", now + monitor._cooldown_sec + 1) is True


def test_tick_skips_noise_and_notifies_match():
    products = [
        Product("H100", "Kelly 25", "https://www.hermes.com/p/kelly-25", "¥1.5M", "ケリー"),
        Product("H101", "Wallet", "https://www.hermes.com/p/wallet", "¥0", "ケリー"),
    ]
    monitor, notifier = _make_monitor(search_result=products)
    monitor._tick()
    assert notifier.notify.call_count == 1
    notified = notifier.notify.call_args[0][0]
    assert notified.sku == "H100"


def test_tick_dedupes_within_cooldown():
    products = [Product("H100", "Kelly 25", "https://x", "", "ケリー")]
    monitor, notifier = _make_monitor(search_result=products)
    monitor._tick()
    monitor._tick()
    assert notifier.notify.call_count == 1


# ---- build_notifier ----------------------------------------------------
def test_build_notifier_supports_both_sinks():
    http = MagicMock()
    args = parse_args([
        "--webhook", "https://chat.example/webhook",
        "--line-token", "T", "--line-to", "U1",
    ])
    n = build_notifier(http, args)
    assert isinstance(n, MultiNotifier)
    assert len(n.notifiers) == 2
    names = {x.name for x in n.notifiers}
    assert names == {"google_chat", "line"}


def test_build_notifier_returns_none_without_config(monkeypatch):
    monkeypatch.delenv("GOOGLE_CHAT_WEBHOOK", raising=False)
    monkeypatch.delenv("LINE_CHANNEL_TOKEN", raising=False)
    monkeypatch.delenv("LINE_TO", raising=False)
    args = parse_args([])
    assert build_notifier(MagicMock(), args) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
