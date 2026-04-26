"""
Hermes JP オンライン在庫監視 -> マルチ通知 (Google Chat / LINE)
監視対象: ケリー / バーキン / ピコタン / コンスタンス / エヴリン / アッカド

環境変数 (任意 / どれか1つは必須):
  GOOGLE_CHAT_WEBHOOK   Google Chat Incoming Webhook URL
  LINE_CHANNEL_TOKEN    LINE Messaging API のチャネルアクセストークン
  LINE_TO               LINE 宛先 (userId / groupId / roomId)
  HERMES_INTERVAL       秒数 (デフォルト 1)
  HERMES_LOCALE         例: jp/ja, fr/fr, us/en
  HERMES_PROXIES        プロキシのカンマ区切り (任意)
  HERMES_JITTER         0.0-1.0 のジッタ率 (デフォルト 0.3)

使い方:
  python3 hermes_monitor.py
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import sys
import time
from typing import Iterable

from http_client import AntiBotClient
from notifiers import (
    GoogleChatNotifier,
    LineNotifier,
    MultiNotifier,
    Notifier,
    Product,
)

# ---- 監視対象 (日本語名 -> 検索キーワード) -------------------------
TARGETS: dict[str, str] = {
    "ケリー": "kelly",
    "バーキン": "birkin",
    "ピコタン": "picotin",
    "コンスタンス": "constance",
    "エヴリン": "evelyne",
    "アッカド": "akkad",
}

DEFAULT_LOCALE = "jp/ja"
SEARCH_API_TMPL = "https://www.hermes.com/api/{locale}/products/search"
PRODUCT_URL_TMPL = "https://www.hermes.com{url}"

logging.basicConfig(
    level=os.getenv("HERMES_LOGLEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("hermes")


class HermesClient:
    def __init__(self, locale: str, http: AntiBotClient):
        self.locale = locale
        self.http = http
        self.search_url = SEARCH_API_TMPL.format(locale=locale)
        self.base_url = f"https://www.hermes.com/{locale}/"
        self.http.warmup(self.base_url)

    def search(self, keyword: str) -> list[Product]:
        params = {"locale": self.locale.replace("/", "_"), "q": keyword}
        try:
            r = self.http.get(self.search_url, params=params, referer=self.base_url)
        except Exception as e:  # noqa: BLE001
            log.warning("検索通信エラー [%s]: %s", keyword, e)
            return []

        if r.status_code == 429:
            log.warning("レート制限 (429) — 間隔を広げてください")
            return []
        if r.status_code in (403, 401):
            log.debug("ブロック疑い status=%s — HTML フォールバック", r.status_code)
            return self._search_fallback(keyword)
        if r.status_code != 200:
            log.debug("非200応答 [%s] status=%s", keyword, r.status_code)
            return self._search_fallback(keyword)

        try:
            data = r.json() if callable(getattr(r, "json", None)) else json.loads(r.text)
        except (ValueError, TypeError):
            return self._search_fallback(keyword)

        return self._extract_products(data, keyword)

    def _search_fallback(self, keyword: str) -> list[Product]:
        url = f"https://www.hermes.com/{self.locale}/search/"
        try:
            r = self.http.get(url, params={"s": keyword}, referer=self.base_url)
        except Exception:  # noqa: BLE001
            return []
        if r.status_code != 200:
            return []
        return self._extract_from_html(r.text, keyword)

    @staticmethod
    def _extract_products(payload: dict, keyword_jp_key: str) -> list[Product]:
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
        notifier: Notifier,
        targets: dict[str, str],
        interval: float,
        http: AntiBotClient,
    ):
        self.client = client
        self.notifier = notifier
        self.targets = targets
        self.interval = interval
        self.http = http
        self._seen: dict[str, float] = {}
        self._cooldown_sec = 60 * 60
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
                title_lc = p.title.lower()
                if kw not in title_lc and jp not in p.title:
                    continue
                if self._should_notify(p.sku, now):
                    log.info("入荷検知: [%s] %s -> %s", jp, p.title, p.url)
                    self.notifier.notify(p)

    def run(self) -> None:
        log.info(
            "監視開始 interval=%.2fs jitter=%.2f targets=%s",
            self.interval,
            self.http.jitter,
            list(self.targets.keys()),
        )
        if self.interval < 5:
            log.warning(
                "⚠ interval=%.2fs は短すぎます。Hermes 側のブロックを招きます。"
                " 推奨は 30〜60 秒です。",
                self.interval,
            )
        while not self._stop:
            start = time.monotonic()
            try:
                self._tick()
            except Exception as e:  # noqa: BLE001
                log.exception("巡回中エラー: %s", e)
            elapsed = time.monotonic() - start
            sleep = max(0.0, self.interval - elapsed)
            if sleep:
                end = time.monotonic() + sleep
                while not self._stop and time.monotonic() < end:
                    # ジッタ込みの細切れスリープでシグナル応答性も確保
                    time.sleep(min(0.2, end - time.monotonic()))


def build_notifier(http: AntiBotClient, args) -> Notifier | None:
    sinks: list[Notifier] = []
    if args.webhook:
        sinks.append(GoogleChatNotifier(args.webhook, http))
        log.info("通知先: Google Chat")
    if args.line_token and args.line_to:
        sinks.append(LineNotifier(args.line_token, args.line_to, http))
        log.info("通知先: LINE -> %s", args.line_to)
    if not sinks:
        return None
    return MultiNotifier(sinks)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Hermes 在庫監視 -> Google Chat / LINE 通知")
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
        help="Google Chat Webhook URL (env GOOGLE_CHAT_WEBHOOK)",
    )
    p.add_argument(
        "--line-token",
        default=os.getenv("LINE_CHANNEL_TOKEN"),
        help="LINE Messaging API channel token (env LINE_CHANNEL_TOKEN)",
    )
    p.add_argument(
        "--line-to",
        default=os.getenv("LINE_TO"),
        help="LINE 宛先 userId/groupId (env LINE_TO)",
    )
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    http = AntiBotClient()
    notifier = build_notifier(http, args)
    if notifier is None:
        print(
            "ERROR: 通知先が1つも指定されていません。\n"
            "  GOOGLE_CHAT_WEBHOOK もしくは LINE_CHANNEL_TOKEN + LINE_TO を設定してください。",
            file=sys.stderr,
        )
        return 2

    client = HermesClient(locale=args.locale, http=http)
    monitor = StockMonitor(
        client=client,
        notifier=notifier,
        targets=TARGETS,
        interval=args.interval,
        http=http,
    )
    monitor.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
