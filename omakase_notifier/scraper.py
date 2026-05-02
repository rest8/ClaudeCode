"""店舗ページから空席情報を抽出する。

Omakase の HTML 構造は公開仕様がないため、本実装では
JSON-LD / data-* 属性 / カレンダーセル等を横断的に解析する
ヒューリスティックなアプローチを取る。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Iterable

import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)

AVAILABILITY_KEYWORDS = (
    "available",
    "空席",
    "予約可能",
    "OK",
    "○",
    "◯",
)

DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")


@dataclass(frozen=True)
class AvailabilitySlot:
    """空席1件を表す。"""

    date: str
    time: str | None = None
    party_size: int | None = None
    raw: str = ""

    def key(self) -> str:
        return f"{self.date}|{self.time or '*'}|{self.party_size or '*'}"

    def describe(self) -> str:
        parts = [self.date]
        if self.time:
            parts.append(self.time)
        if self.party_size:
            parts.append(f"{self.party_size}名")
        return " ".join(parts)


class OmakaseScraper:
    def __init__(self, user_agent: str, cookies: dict[str, str] | None = None) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "ja,en-US;q=0.8,en;q=0.5",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        for k, v in (cookies or {}).items():
            self._session.cookies.set(k, v)

    def fetch_url(self, url: str) -> set[AvailabilitySlot]:
        LOGGER.debug("fetch_url: %s", url)
        try:
            resp = self._session.get(url, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as e:
            LOGGER.warning("HTTP取得に失敗: %s (%s)", url, e)
            return set()
        return self._parse(resp.text)

    def _parse(self, html: str) -> set[AvailabilitySlot]:
        soup = BeautifulSoup(html, "html.parser")
        slots: set[AvailabilitySlot] = set()
        slots |= self._parse_jsonld(soup)
        slots |= self._parse_inline_json(soup)
        slots |= self._parse_data_attributes(soup)
        slots |= self._parse_calendar_cells(soup)
        return slots

    def _parse_jsonld(self, soup: BeautifulSoup) -> set[AvailabilitySlot]:
        out: set[AvailabilitySlot] = set()
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            out |= self._extract_from_obj(data)
        return out

    def _parse_inline_json(self, soup: BeautifulSoup) -> set[AvailabilitySlot]:
        out: set[AvailabilitySlot] = set()
        for tag in soup.find_all("script"):
            text = tag.string
            if not text:
                continue
            for match in re.finditer(r"=\s*(\{.*?\})\s*[;<]", text, flags=re.DOTALL):
                try:
                    data = json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
                out |= self._extract_from_obj(data)
        return out

    def _parse_data_attributes(self, soup: BeautifulSoup) -> set[AvailabilitySlot]:
        out: set[AvailabilitySlot] = set()
        for el in soup.select("[data-available], [data-availability], [data-status]"):
            status = (
                el.get("data-available")
                or el.get("data-availability")
                or el.get("data-status")
                or ""
            )
            if not self._is_available(status):
                continue
            date = el.get("data-date") or self._first_date(el.get_text(" ", strip=True))
            if not date:
                continue
            time = el.get("data-time") or self._first_time(el.get_text(" ", strip=True))
            out.add(AvailabilitySlot(date=date, time=time, raw=str(el)[:200]))
        return out

    def _parse_calendar_cells(self, soup: BeautifulSoup) -> set[AvailabilitySlot]:
        out: set[AvailabilitySlot] = set()
        selectors = [
            ".available",
            ".is-available",
            ".calendar-day.available",
            "td.available",
            "li.available",
        ]
        for sel in selectors:
            for el in soup.select(sel):
                text = el.get_text(" ", strip=True)
                date = el.get("data-date") or self._first_date(text)
                if not date:
                    continue
                time = el.get("data-time") or self._first_time(text)
                out.add(AvailabilitySlot(date=date, time=time, raw=text[:200]))
        return out

    def _extract_from_obj(self, obj: object) -> set[AvailabilitySlot]:
        out: set[AvailabilitySlot] = set()
        stack: list[object] = [obj]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                if self._looks_like_slot(cur):
                    slot = self._slot_from_dict(cur)
                    if slot:
                        out.add(slot)
                stack.extend(cur.values())
            elif isinstance(cur, list):
                stack.extend(cur)
        return out

    @staticmethod
    def _looks_like_slot(d: dict) -> bool:
        keys = {k.lower() for k in d.keys()}
        has_date = bool(keys & {"date", "day", "available_date", "reservation_date"})
        has_avail = bool(
            keys & {"available", "availability", "status", "is_available", "vacant"}
        )
        return has_date and has_avail

    def _slot_from_dict(self, d: dict) -> AvailabilitySlot | None:
        date = (
            d.get("date") or d.get("day") or d.get("available_date") or d.get("reservation_date")
        )
        if not date:
            return None
        if isinstance(date, str):
            m = DATE_RE.search(date)
            if not m:
                return None
            date = m.group(1)
        else:
            return None

        status = (
            d.get("available")
            or d.get("availability")
            or d.get("status")
            or d.get("is_available")
            or d.get("vacant")
        )
        if not self._is_available(status):
            return None

        time = d.get("time") or d.get("start_time") or d.get("hour")
        if isinstance(time, str):
            m = TIME_RE.search(time)
            time = f"{int(m.group(1)):02d}:{m.group(2)}" if m else None
        else:
            time = None

        party = d.get("party_size") or d.get("seats") or d.get("people")
        if isinstance(party, str) and party.isdigit():
            party = int(party)
        if not isinstance(party, int):
            party = None

        return AvailabilitySlot(date=date, time=time, party_size=party)

    @staticmethod
    def _is_available(value: object) -> bool:
        if value is True:
            return True
        if value is False or value is None:
            return False
        s = str(value).strip().lower()
        if s in ("true", "1", "yes", "y"):
            return True
        return any(kw.lower() in s for kw in AVAILABILITY_KEYWORDS)

    @staticmethod
    def _first_date(text: str) -> str | None:
        m = DATE_RE.search(text or "")
        return m.group(1) if m else None

    @staticmethod
    def _first_time(text: str) -> str | None:
        m = TIME_RE.search(text or "")
        return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def filter_slots(
    slots: Iterable[AvailabilitySlot],
    dates: list[str],
    times: list[str],
    party_size: int | None,
) -> list[AvailabilitySlot]:
    """購読者の条件で空席をフィルタ。"""
    wanted_dates = set(dates)
    wanted_times = set(times)
    out: list[AvailabilitySlot] = []
    for s in slots:
        if wanted_dates and s.date not in wanted_dates:
            continue
        if wanted_times and (s.time is None or s.time not in wanted_times):
            continue
        if party_size is not None and s.party_size is not None and s.party_size < party_size:
            continue
        out.append(s)
    return out
