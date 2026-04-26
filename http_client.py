"""
アンチBot対策強化された HTTP クライアント

優先度:
  1. curl_cffi (Chrome の TLS/JA3 フィンガープリント完全模倣) — Akamai/Cloudflare に最も有効
  2. cloudscraper (Cloudflare のみ)
  3. requests (素のリクエスト)

加えて:
  - User-Agent ローテーション
  - 人間らしい Accept-Language / sec-ch-ua ヘッダ
  - Cookie 永続化 (セッション内)
  - プロキシローテーション (HERMES_PROXIES=ip:port,ip:port,...)
  - リクエスト間ジッタ (HERMES_JITTER=0.4 で ±40%)
"""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any

log = logging.getLogger("hermes.http")


# Chrome / Safari / Firefox の最新版を模した UA
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

CHROME_SEC_HEADERS = {
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "upgrade-insecure-requests": "1",
}


def _build_session() -> tuple[Any, str]:
    """利用可能な最も強力なクライアントを返す"""
    try:
        from curl_cffi import requests as cffi_requests  # type: ignore

        impersonate = os.getenv("HERMES_IMPERSONATE", "chrome124")
        session = cffi_requests.Session(impersonate=impersonate)
        return session, f"curl_cffi:{impersonate}"
    except ImportError:
        pass

    try:
        import cloudscraper  # type: ignore

        session = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "darwin", "mobile": False}
        )
        return session, "cloudscraper"
    except ImportError:
        pass

    import requests

    return requests.Session(), "requests"


class AntiBotClient:
    """Hermes/Akamai 対策込みの HTTP クライアント"""

    def __init__(self, jitter: float | None = None, proxies: list[str] | None = None):
        self.session, self.backend = _build_session()
        log.info("HTTP backend: %s", self.backend)
        self.jitter = (
            jitter if jitter is not None else float(os.getenv("HERMES_JITTER", "0.3"))
        )
        env_proxies = os.getenv("HERMES_PROXIES", "").strip()
        self.proxies = proxies or (
            [p.strip() for p in env_proxies.split(",") if p.strip()]
            if env_proxies
            else []
        )
        self._proxy_idx = 0
        # 一度ホームページを叩いてセッション Cookie / Akamai の bm_sz を取得
        self._warmed = False

    def _next_proxy(self) -> dict | None:
        if not self.proxies:
            return None
        p = self.proxies[self._proxy_idx % len(self.proxies)]
        self._proxy_idx += 1
        url = p if "://" in p else f"http://{p}"
        return {"http": url, "https": url}

    def _headers(self, referer: str | None = None) -> dict:
        h = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "DNT": "1",
            **CHROME_SEC_HEADERS,
        }
        if referer:
            h["Referer"] = referer
        return h

    def warmup(self, base_url: str) -> None:
        """セッション Cookie を温める (Akamai bm_sz 取得)"""
        if self._warmed:
            return
        try:
            self.session.get(
                base_url,
                headers=self._headers(),
                timeout=15,
                proxies=self._next_proxy(),
            )
            self._warmed = True
            log.info("セッション warmup 完了: %s", base_url)
        except Exception as e:  # noqa: BLE001
            log.debug("warmup 失敗 (続行): %s", e)

    def get(self, url: str, *, params: dict | None = None, referer: str | None = None,
            timeout: float = 15.0):
        return self.session.get(
            url,
            params=params,
            headers=self._headers(referer=referer),
            timeout=timeout,
            proxies=self._next_proxy(),
        )

    def post(self, url: str, *, json: Any = None, headers: dict | None = None,
             timeout: float = 10.0):
        h = {
            "User-Agent": random.choice(USER_AGENTS),
            "Content-Type": "application/json",
        }
        if headers:
            h.update(headers)
        return self.session.post(
            url,
            json=json,
            headers=h,
            timeout=timeout,
        )

    def jitter_sleep(self, base_seconds: float) -> None:
        """次回リクエストまでのスリープ。ジッタを加えて等間隔を回避"""
        if self.jitter <= 0:
            time.sleep(max(0.0, base_seconds))
            return
        spread = base_seconds * self.jitter
        delay = max(0.0, base_seconds + random.uniform(-spread, spread))
        time.sleep(delay)
