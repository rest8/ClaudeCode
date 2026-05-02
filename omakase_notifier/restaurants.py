"""Omakase 掲載店舗の一覧取得とキャッシュ。

Omakase の HTML 構造は公開仕様がないため、店舗一覧ページから
`/ja/r/<id>` への内部リンクを横断的に拾い、店舗 ID と名称を抽出する。
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)

DEFAULT_INDEX_URL = "https://omakase.in/ja/restaurants"
RESTAURANT_HREF_RE = re.compile(r"^/ja/r/([A-Za-z0-9_-]+)/?$")


@dataclass
class Restaurant:
    id: str
    name: str
    url: str
    area: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Restaurant":
        return cls(
            id=d["id"],
            name=d.get("name", ""),
            url=d.get("url", ""),
            area=d.get("area", ""),
        )


class RestaurantDirectory:
    """店舗一覧のキャッシュ管理 (`restaurants.json`)。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._fetched_at: float = 0.0
        self._restaurants: dict[str, Restaurant] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            LOGGER.warning("店舗キャッシュの読み込み失敗: %s", e)
            return
        self._fetched_at = float(data.get("fetched_at") or 0.0)
        for r in data.get("restaurants", []):
            try:
                self._restaurants[r["id"]] = Restaurant.from_dict(r)
            except KeyError:
                continue

    def save(self) -> None:
        payload = {
            "fetched_at": self._fetched_at,
            "restaurants": [r.to_dict() for r in self._all_sorted()],
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get(self, restaurant_id: str) -> Restaurant | None:
        return self._restaurants.get(restaurant_id)

    def all(self) -> list[Restaurant]:
        return self._all_sorted()

    def search(self, keyword: str) -> list[Restaurant]:
        kw = keyword.strip().lower()
        if not kw:
            return self.all()
        return [
            r for r in self._all_sorted()
            if kw in r.name.lower() or kw in r.area.lower() or kw in r.id.lower()
        ]

    def upsert_many(self, items: Iterable[Restaurant]) -> int:
        added = 0
        for r in items:
            if r.id not in self._restaurants:
                added += 1
            self._restaurants[r.id] = r
        return added

    def is_empty(self) -> bool:
        return not self._restaurants

    def fetched_at(self) -> float:
        return self._fetched_at

    def _all_sorted(self) -> list[Restaurant]:
        return sorted(self._restaurants.values(), key=lambda r: (r.area, r.name, r.id))

    def discover(
        self,
        index_urls: list[str],
        cookies: dict[str, str] | None = None,
        user_agent: str = "",
        timeout: int = 20,
    ) -> int:
        """インデックスページを巡回して店舗を抽出。新規追加件数を返す。"""
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": user_agent or "Mozilla/5.0",
                "Accept-Language": "ja,en-US;q=0.8,en;q=0.5",
            }
        )
        for k, v in (cookies or {}).items():
            session.cookies.set(k, v)

        found: dict[str, Restaurant] = {}
        for url in index_urls:
            page_url: str | None = url
            visited: set[str] = set()
            while page_url and page_url not in visited:
                visited.add(page_url)
                LOGGER.info("インデックス取得: %s", page_url)
                try:
                    resp = session.get(page_url, timeout=timeout)
                    resp.raise_for_status()
                except requests.RequestException as e:
                    LOGGER.warning("インデックス取得失敗: %s (%s)", page_url, e)
                    break

                page_restaurants = self._extract_from_html(resp.text, page_url)
                for r in page_restaurants:
                    found.setdefault(r.id, r)

                page_url = self._next_page_url(resp.text, page_url)

        added = self.upsert_many(found.values())
        self._fetched_at = time.time()
        self.save()
        LOGGER.info("店舗抽出: %d件 (新規 %d件)", len(found), added)
        return added

    @staticmethod
    def _extract_from_html(html: str, base_url: str) -> list[Restaurant]:
        soup = BeautifulSoup(html, "html.parser")
        out: dict[str, Restaurant] = {}
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            parsed = urlparse(href)
            path = parsed.path or href
            m = RESTAURANT_HREF_RE.match(path)
            if not m:
                continue
            rid = m.group(1)
            name = a.get_text(" ", strip=True)
            if not name:
                img = a.find("img")
                name = (img.get("alt") if img else "") or rid
            area = ""
            parent = a.find_parent(["article", "li", "div"])
            if parent is not None:
                area_el = parent.find(class_=re.compile(r"area|location|region", re.I))
                if area_el is not None:
                    area = area_el.get_text(" ", strip=True)
            full_url = urljoin(base_url, f"/ja/r/{rid}")
            existing = out.get(rid)
            if existing is None or (not existing.name and name):
                out[rid] = Restaurant(id=rid, name=name, url=full_url, area=area)
        return list(out.values())

    @staticmethod
    def _next_page_url(html: str, current_url: str) -> str | None:
        soup = BeautifulSoup(html, "html.parser")
        # rel="next"
        link = soup.find("a", rel=lambda v: v and "next" in v)
        if link and link.get("href"):
            return urljoin(current_url, link["href"])
        # ?page=N が増える形式
        for a in soup.select("a[href*='page=']"):
            txt = a.get_text(" ", strip=True)
            if txt in ("次へ", "次", "Next", ">", "»"):
                return urljoin(current_url, a["href"])
        return None
