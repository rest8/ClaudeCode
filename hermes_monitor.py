"""
Hermes JP オンライン在庫監視 -> Google Chat 通知
監視対象: ケリー / バーキン / ピコタン / コンスタンス / エヴリン / アッカド

使い方:
  export GOOGLE_CHAT_WEBHOOK="https://chat.googleapis.com/v1/spaces/.../messages?key=...&token=..."
  python3 hermes_monitor.py [--interval 1] [--locale jp/ja]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import signal
import sys
import time
from dataclasses import dataclass
from typing import Iterable

import requests

# ---- 監視対象 (日本語名 -> Hermes 検索キーワード) -------------------------
TARGETS: dict[str, str] = {
    "ケリー": "kelly",
    "バーキン": "birkin",
    "ピコタン": "picotin",
    "コンスタンス": "constance",
    "エヴリン": "evelyne",
    "アッカド": "akkad",
}

# Hermes はロケールごとに URL が分かれる。デフォルトは日本 (jp/ja)
DEFAULT_LOCALE = "jp/ja"
SEARCH_API_TMPL = "https://www.hermes.com/api/{locale}/products/search"
PRODUCT_URL_TMPL = "https://www.hermes.com{url}"

# 一般的なブラウザに偽装 (Hermes は UA で簡易フィルタリングする)
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("hermes")


@dataclass(frozen=True)
class Product:
    sku: str
    title: str
    url: str
    price: str
    keyword_jp: str

    def chat_card(self) -> dict:
        """Google Chat のカード形式メッセージ"""
        return {
            "cards": [
                {
                    "header": {
                        "title": f"🛍️ Hermes 入荷: {self.keyword_jp}",
                        "subtitle": self.title,
                    },
                    "sections": [
                        {
                            "widgets": [
                                {
                                    "keyValue": {
                                        "topLabel": "価格",
                                        "content": self.price or "-",
                                    }
                                },
                                {
                                    "keyValue": {
                                        "topLabel": "SKU",
                                        "content": self.sku,
                                    }
                                },
                                {
                                    "buttons": [
                                        {
                                            "textButton": {
                                                "text": "商品ページを開く",
                                                "onClick": {
                                                    "openLink": {"url": self.url}
                                                },
                                            }
                                        }
                                    ]
                                },
                            ]
                        }
                    ],
                }
            ],
            "text": f"🛍️ {self.keyword_jp} 入荷: {self.title} {self.url}",
        }


class GoogleChatNotifier:
    def __init__(self, webhook_url: str, session: requests.Session):
        self.webhook_url = webhook_url
        self.session = session

    def notify(self, product: Product) -> None:
        try:
            r = self.session.post(
                self.webhook_url,
                json=product.chat_card(),
                timeout=10,
            )
            if r.status_code >= 300:
                log.warning("Google Chat 通知失敗 status=%s body=%s", r.status_code, r.text[:200])
            else:
                log.info("通知送信: %s (%s)", product.keyword_jp, product.title)
        except requests.RequestException as e:
            log.warning("Google Chat 通信エラー: %s", e)


class HermesClient:
    def __init__(self, locale: str, session: requests.Session):
        self.locale = locale
        self.session = session
        self.search_url = SEARCH_API_TMPL.format(locale=locale)

    def _headers(self) -> dict:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Referer": f"https://www.hermes.com/{self.locale}/",
        }

    def search(self, keyword: str) -> list[Product]:
        """検索 API を叩いて在庫ありの商品だけ返す"""
        params = {
            "locale": self.locale.replace("/", "_"),
            "q": keyword,
        }
        try:
            r = self.session.get(
                self.search_url,
                params=params,
                headers=self._headers(),
                timeout=15,
            )
        except requests.RequestException as e:
            log.warning("検索エラー [%s]: %s", keyword, e)
            return []

        if r.status_code == 429:
            log.warning("レート制限 (429) - 間隔を広げてください")
            return []
        if r.status_code != 200:
            log.debug("非200応答 [%s] status=%s", keyword, r.status_code)
            return self._search_fallback(keyword)

        try:
            data = r.json()
        except ValueError:
            return self._search_fallback(keyword)

        return self._extract_products(data, keyword)

    def _search_fallback(self, keyword: str) -> list[Product]:
        """JSON API が使えない場合は HTML 検索ページをパース"""
        url = f"https://www.hermes.com/{self.locale}/search/"
        try:
            r = self.session.get(
                url,
                params={"s": keyword},
                headers=self._headers(),
                timeout=15,
            )
        except requests.RequestException:
            return []
        if r.status_code != 200:
            return []
        return self._extract_from_html(r.text, keyword)

    @staticmethod
    def _extract_products(payload: dict, keyword_jp_key: str) -> list[Product]:
        """Hermes 検索 API の JSON から在庫ありの商品を抽出"""
        items = (
            payload.get("products", {}).get("items")
            or payload.get("items")
            or []
        )
        out: list[Product] = []
        for it in items:
            available = (
                it.get("available")
                if "available" in it
                else it.get("inStock", True)
            )
            if not available:
                continue
            sku = str(it.get("sku") or it.get("id") or it.get("productId") or "")
            title = str(it.get("title") or it.get("name") or "").strip()
            url_path = it.get("url") or it.get("link") or ""
            price = ""
            price_obj = it.get("price") or {}
            if isinstance(price_obj, dict):
                price = str(price_obj.get("formatted") or price_obj.get("value") or "")
            elif isinstance(price_obj, (int, float, str)):
                price = str(price_obj)
            if not (sku and url_path):
                continue
            full_url = (
                url_path if url_path.startswith("http")
                else PRODUCT_URL_TMPL.format(url=url_path)
            )
            out.append(
                Product(
                    sku=sku,
                    title=title or keyword_jp_key,
                    url=full_url,
                    price=price,
                    keyword_jp=keyword_jp_key,
                )
            )
        return out

    @staticmethod
    def _extract_from_html(html: str, keyword_jp_key: str) -> list[Product]:
        """HTML 内に埋め込まれた __NEXT_DATA__ などから商品情報を抽出"""
        m = re.search(
            r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.+?)</script>',
            html,
            re.DOTALL,
        )
        if not m:
            return []
        try:
            data = json.loads(m.group(1))
        except ValueError:
            return []
        # 構造は変動するため再帰的に "items" を探す
        items: list[dict] = []

        def walk(node):
            if isinstance(node, dict):
                if "items" in node and isinstance(node["items"], list):
                    items.extend(
                        x for x in node["items"]
                        if isinstance(x, dict) and (x.get("sku") or x.get("id"))
                    )
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(data)
        return HermesClient._extract_products({"items": items}, keyword_jp_key)


class StockMonitor:
    def __init__(
        self,
        client: HermesClient,
        notifier: GoogleChatNotifier,
        targets: dict[str, str],
        interval: float,
    ):
        self.client = client
        self.notifier = notifier
        self.targets = targets
        self.interval = interval
        # SKU 単位で通知済みを記録 (再入荷検知のため一定時間で揮発させる)
        self._seen: dict[str, float] = {}
        self._cooldown_sec = 60 * 60  # 1時間以内の再通知は抑止
        self._stop = False
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, *_):
        log.info("停止シグナル受信。終了します。")
        self._stop = True

    def _should_notify(self, sku: str, now: float) -> bool:
        last = self._seen.get(sku)
        if last is None or (now - last) > self._cooldown_sec:
            self._seen[sku] = now
            return True
        return False

    def _tick(self) -> None:
        for jp, kw in self.targets.items():
            if self._stop:
                return
            products = self.client.search(kw)
            now = time.time()
            for p in products:
                # キーワードが含まれない検索ノイズを除外
                title_lc = p.title.lower()
                if kw not in title_lc and jp not in p.title:
                    continue
                if self._should_notify(p.sku, now):
                    log.info("入荷検知: [%s] %s -> %s", jp, p.title, p.url)
                    self.notifier.notify(p)

    def run(self) -> None:
        log.info(
            "監視開始 interval=%.2fs targets=%s",
            self.interval,
            list(self.targets.keys()),
        )
        if self.interval < 5:
            log.warning(
                "⚠ interval=%.2fs は非常に短く、Hermes 側のレート制限/IPブロックの"
                "リスクが高いです。30〜60s を推奨します。",
                self.interval,
            )
        while not self._stop:
            start = time.monotonic()
            try:
                self._tick()
            except Exception as e:  # ループ全体は止めない
                log.exception("巡回中エラー: %s", e)
            elapsed = time.monotonic() - start
            sleep = max(0.0, self.interval - elapsed)
            # 1秒未満も切り捨てず正確にスリープ
            if sleep:
                # 短時間 sleep でもシグナルに応答できるよう分割
                end = time.monotonic() + sleep
                while not self._stop and time.monotonic() < end:
                    time.sleep(min(0.2, end - time.monotonic()))


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Hermes 在庫監視 -> Google Chat 通知")
    p.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv("HERMES_INTERVAL", "1")),
        help="ポーリング間隔(秒) デフォルト=1 (推奨: 30-60)",
    )
    p.add_argument(
        "--locale",
        default=os.getenv("HERMES_LOCALE", DEFAULT_LOCALE),
        help="Hermes ロケール (例: jp/ja, fr/fr, us/en)",
    )
    p.add_argument(
        "--webhook",
        default=os.getenv("GOOGLE_CHAT_WEBHOOK"),
        help="Google Chat Webhook URL (env GOOGLE_CHAT_WEBHOOK でも可)",
    )
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.webhook:
        print(
            "ERROR: Google Chat Webhook URL が指定されていません。\n"
            "環境変数 GOOGLE_CHAT_WEBHOOK か --webhook で指定してください。",
            file=sys.stderr,
        )
        return 2

    session = requests.Session()
    client = HermesClient(locale=args.locale, session=session)
    notifier = GoogleChatNotifier(webhook_url=args.webhook, session=session)
    monitor = StockMonitor(
        client=client,
        notifier=notifier,
        targets=TARGETS,
        interval=args.interval,
    )
    monitor.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
