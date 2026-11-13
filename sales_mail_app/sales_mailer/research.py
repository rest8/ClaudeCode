"""新規開拓のための企業調査.

- Google Places API (New) の Text Search で、選択した地域×業種の企業を探す
- 企業の公式サイトを巡回し、公開されている問い合わせ用メールアドレスを取得する
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse

from .db import FREE_MAIL_DOMAINS, normalize_email, url_domain
from .regions import extract_city, extract_prefecture, normalize_text

USER_AGENT = "Mozilla/5.0 (compatible; SalesMailerResearch/1.0)"

ProgressFn = Callable[[str], None]


class ResearchError(Exception):
    pass


@dataclass
class Prospect:
    name: str
    address: str = ""
    prefecture: str = ""
    city: str = ""
    phone: str = ""
    website: str = ""
    email: str = ""
    emails: list[str] = field(default_factory=list)
    industry: str = ""
    description: str = ""
    place_id: str = ""
    source: str = ""
    existing_status: str = ""  # 既に登録済みならそのステータス
    existing_id: int | None = None

    def to_company(self) -> dict:
        return {
            "name": self.name, "address": self.address, "prefecture": self.prefecture, "city": self.city,
            "phone": self.phone, "website": self.website, "email": self.email, "industry": self.industry,
            "description": self.description, "place_id": self.place_id, "source": self.source,
        }


# ---------------------------------------------------------------- Google Places
class GooglePlacesSearcher:
    ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
    FIELD_MASK = ",".join([
        "places.id", "places.displayName", "places.formattedAddress", "places.addressComponents",
        "places.websiteUri", "places.nationalPhoneNumber", "places.primaryTypeDisplayName",
        "nextPageToken",
    ])

    def __init__(self, api_key: str, timeout: int = 20):
        if not api_key:
            raise ResearchError("Google Places API キーが設定されていません（設定タブ）")
        self.api_key = api_key
        self.timeout = timeout

    def _post(self, body: dict) -> dict:
        req = urllib.request.Request(
            self.ENDPOINT,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": self.FIELD_MASK,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            raise ResearchError(f"Google Places API エラー ({e.code}): {detail}") from e
        except urllib.error.URLError as e:
            raise ResearchError(f"Google Places API に接続できません: {e.reason}") from e

    def search(self, query: str, max_results: int = 60, stop: threading.Event | None = None) -> list[Prospect]:
        results: list[Prospect] = []
        page_token = ""
        while len(results) < max_results:
            if stop and stop.is_set():
                break
            body = {"textQuery": query, "languageCode": "ja", "regionCode": "JP",
                    "pageSize": min(20, max_results - len(results))}
            if page_token:
                body["pageToken"] = page_token
            data = self._post(body)
            for place in data.get("places", []):
                results.append(self._to_prospect(place))
            page_token = data.get("nextPageToken", "")
            if not page_token:
                break
            time.sleep(1.0)  # 次ページトークンが有効になるまで少し待つ
        return results[:max_results]

    @staticmethod
    def _to_prospect(place: dict) -> Prospect:
        address = place.get("formattedAddress", "")
        prefecture = city = ""
        for comp in place.get("addressComponents", []):
            types = comp.get("types", [])
            if "administrative_area_level_1" in types:
                prefecture = comp.get("longText", "")
            elif "locality" in types and not city:
                city = comp.get("longText", "")
        prefecture = extract_prefecture(prefecture) or extract_prefecture(address)
        city = city or extract_city(address, prefecture)
        return Prospect(
            name=(place.get("displayName") or {}).get("text", ""),
            address=re.sub(r"^日本、\s*", "", address),
            prefecture=prefecture,
            city=city,
            phone=place.get("nationalPhoneNumber", ""),
            website=place.get("websiteUri", ""),
            industry=(place.get("primaryTypeDisplayName") or {}).get("text", ""),
            place_id=place.get("id", ""),
            source="google_places",
        )


def build_queries(keywords: Iterable[str], prefectures: Iterable[str], cities: Iterable[str]) -> list[tuple[str, str]]:
    """(検索クエリ, 想定都道府県) の一覧を作る.

    市区町村が指定された場合は、選択した都道府県×市区町村で検索する。
    """
    kws = [normalize_text(k) for k in keywords if normalize_text(k)] or ["企業"]
    prefs = list(prefectures)
    city_list = [normalize_text(c) for c in cities if normalize_text(c)]
    queries: list[tuple[str, str]] = []
    for kw in kws:
        if city_list:
            for city in city_list:
                pref = extract_prefecture(city)
                if pref:
                    queries.append((f"{kw} {city}", pref))
                elif prefs:
                    for p in prefs:
                        queries.append((f"{kw} {p}{city}", p))
                else:
                    queries.append((f"{kw} {city}", ""))
        else:
            for p in prefs:
                queries.append((f"{kw} {p}", p))
    return queries


# ---------------------------------------------------------------- メール取得
_EMAIL_IN_TEXT = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_BAD_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js", ".ico", ".bmp")
_BAD_DOMAINS = {"example.com", "example.co.jp", "example.jp", "sentry.io", "wixpress.com", "domain.com",
                "email.com", "sample.com", "test.com", "xxx.co.jp", "xxx.com", "sentry-next.wixpress.com"}
_GOOD_LOCALPARTS = ("info", "contact", "inquiry", "otoiawase", "toiawase", "sales", "eigyo", "eigyou",
                    "support", "office", "mail", "webmaster", "jimukyoku", "soumu", "honsha")
_BAD_LOCALPARTS = ("noreply", "no-reply", "donotreply", "do-not-reply", "privacy", "abuse", "postmaster")
_CONTACT_HINTS = ("contact", "inquiry", "toiawase", "otoiawase", "お問い合わせ", "お問合せ", "問い合わせ", "問合せ",
                  "company", "about", "profile", "gaiyo", "gaiyou", "corporate", "outline", "会社概要", "会社案内",
                  "企業情報", "会社情報", "access", "アクセス", "事業所", "info")


def deobfuscate(text: str) -> str:
    """「info[at]example.co.jp」「info＠example.co.jp」などを通常表記に戻す."""
    text = normalize_text(text)
    text = re.sub(r"\s*[\[\(（【<]\s*(?:at|アット|あっと)\s*[\]\)）】>]\s*", "@", text, flags=re.I)
    text = re.sub(r"\s*[\[\(（【<]\s*(?:dot|ドット)\s*[\]\)）】>]\s*", ".", text, flags=re.I)
    text = text.replace("★", "@").replace("☆", "@")
    return text


def extract_emails(text: str) -> list[str]:
    found: list[str] = []
    for raw in _EMAIL_IN_TEXT.findall(deobfuscate(html.unescape(text))):
        email = normalize_email(raw.strip(".-"))
        if not email or email.endswith(_BAD_SUFFIXES):
            continue
        local, domain = email.split("@", 1)
        if domain in _BAD_DOMAINS or ".." in email or local.startswith(_BAD_LOCALPARTS):
            continue
        if re.fullmatch(r"[0-9a-f]{16,}", local):  # トラッキング用のハッシュ
            continue
        if email not in found:
            found.append(email)
    return found


def rank_emails(emails: Iterable[str], website: str) -> list[str]:
    """公式サイトと同じドメイン・問い合わせ用らしいアドレスを優先して並べる."""
    site = url_domain(website)

    def score(email: str) -> tuple:
        local, domain = email.split("@", 1)
        same = bool(site) and (domain == site or domain.endswith("." + site) or site.endswith("." + domain))
        good = any(local.startswith(p) for p in _GOOD_LOCALPARTS)
        recruit = any(w in local for w in ("recruit", "saiyo", "saiyou", "jinji", "career"))
        free = domain in FREE_MAIL_DOMAINS
        return (not same, recruit, not good, free, len(email))

    return sorted(dict.fromkeys(emails), key=score)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.mailtos: list[str] = []
        self.text_parts: list[str] = []
        self._href: str | None = None
        self._anchor: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href.lower().startswith("mailto:"):
                self.mailtos.append(href[7:].split("?", 1)[0])
            self._href = href
            self._anchor = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        if tag == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._anchor).strip()))
            self._href = None

    def handle_data(self, data):
        if self._skip:
            return
        self.text_parts.append(data)
        if self._href is not None:
            self._anchor.append(data)

    @property
    def text(self) -> str:
        return " ".join(self.text_parts)


def _decode(body: bytes, content_type: str) -> str:
    charset = ""
    m = re.search(r"charset=([\w\-]+)", content_type or "", re.I)
    if m:
        charset = m.group(1)
    else:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", body[:4096], re.I)
        if m:
            charset = m.group(1).decode("ascii", "ignore")
    candidates = [c for c in (charset, "utf-8", "cp932", "euc-jp") if c]
    for enc in candidates:
        try:
            return body.decode("cp932" if enc.lower() in ("shift_jis", "sjis", "x-sjis") else enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", "replace")


class EmailCrawler:
    """企業サイトのトップページ＋問い合わせ／会社概要ページから公開メールアドレスを集める."""

    def __init__(self, max_pages: int = 5, timeout: int = 10, delay: float = 0.7):
        self.max_pages = max(1, max_pages)
        self.timeout = timeout
        self.delay = delay
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def fetch(self, url: str) -> tuple[str, str] | None:
        """(最終URL, HTML) を返す。HTML 以外・取得失敗は None."""
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ja"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                ctype = resp.headers.get("Content-Type", "")
                if "html" not in ctype and "text" not in ctype:
                    return None
                body = resp.read(2_000_000)
                return resp.geturl(), _decode(body, ctype)
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._robots:
            parser: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
            req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    parser.parse(resp.read(500_000).decode("utf-8", "replace").splitlines())
            except urllib.error.HTTPError as e:
                parser = None if e.code in (401, 403) else _allow_all()
            except (urllib.error.URLError, OSError, ValueError):
                parser = _allow_all()
            self._robots[base] = parser
        rp = self._robots[base]
        return rp is not None and rp.can_fetch(USER_AGENT, url)

    def find_emails(self, website: str, stop: threading.Event | None = None) -> list[str]:
        website = normalize_text(website)
        if not website:
            return []
        if "://" not in website:
            website = "https://" + website
        site_host = url_domain(website)
        queue = [website]
        visited: set[str] = set()
        emails: list[str] = []
        while queue and len(visited) < self.max_pages:
            if stop and stop.is_set():
                break
            url = queue.pop(0)
            if url in visited or not self.allowed(url):
                visited.add(url)
                continue
            visited.add(url)
            fetched = self.fetch(url)
            if fetched is None:
                continue
            final_url, page = fetched
            parser = _LinkParser()
            try:
                parser.feed(page)
            except Exception:
                pass
            for raw in parser.mailtos:
                emails.extend(extract_emails(raw))
            emails.extend(extract_emails(parser.text))
            if len(visited) == 1:
                # トップページから問い合わせ・会社概要らしいページを候補に追加（問い合わせページを優先）
                candidates = []
                for href, anchor in parser.links:
                    target = urljoin(final_url, href).split("#", 1)[0]
                    if not target.startswith("http") or url_domain(target) != site_host:
                        continue
                    hay = (href + " " + anchor).lower()
                    hits = [i for i, h in enumerate(_CONTACT_HINTS) if h in hay]
                    if hits and target not in visited and target not in [c[1] for c in candidates]:
                        candidates.append((min(hits), target))
                queue.extend(t for _, t in sorted(candidates, key=lambda c: c[0]))
            if any(_is_contact_address(e, site_host) for e in emails):
                break  # 公式ドメインの問い合わせ用アドレスが見つかったら終了
            time.sleep(self.delay)
        return rank_emails(dict.fromkeys(emails), website)


def _is_contact_address(email: str, site_host: str) -> bool:
    local, domain = email.split("@", 1)
    same = bool(site_host) and (domain == site_host or domain.endswith("." + site_host))
    return same and local.startswith(_GOOD_LOCALPARTS)


def _allow_all() -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    rp.parse([])
    return rp


# ---------------------------------------------------------------- 調査の実行
def run_places_research(
    api_key: str,
    keywords: Iterable[str],
    prefectures: Iterable[str],
    cities: Iterable[str],
    max_per_query: int,
    restrict_to_region: bool,
    progress: ProgressFn,
    stop: threading.Event,
) -> list[Prospect]:
    searcher = GooglePlacesSearcher(api_key)
    prefs = set(prefectures)
    queries = build_queries(keywords, prefectures, cities)
    if not queries:
        raise ResearchError("調査する地域（都道府県）を1つ以上選択してください")
    found: dict[str, Prospect] = {}
    for i, (query, pref) in enumerate(queries, 1):
        if stop.is_set():
            break
        progress(f"検索中 ({i}/{len(queries)}): {query}")
        for p in searcher.search(query, max_per_query, stop):
            if restrict_to_region and prefs and p.prefecture not in prefs:
                continue
            if not p.industry:
                p.industry = query.split(" ", 1)[0]
            key = p.place_id or f"{p.name}|{p.address}"
            found.setdefault(key, p)
    return list(found.values())


def enrich_emails(
    prospects: list[Prospect],
    crawler: EmailCrawler,
    progress: ProgressFn,
    stop: threading.Event,
    on_found: Callable[[Prospect], None] | None = None,
) -> None:
    targets = [p for p in prospects if p.website and not p.email and not p.existing_status]
    for i, p in enumerate(targets, 1):
        if stop.is_set():
            break
        progress(f"メールアドレス取得中 ({i}/{len(targets)}): {p.name}")
        emails = crawler.find_emails(p.website, stop)
        if emails:
            p.emails = emails
            p.email = emails[0]
            if on_found:
                on_found(p)
