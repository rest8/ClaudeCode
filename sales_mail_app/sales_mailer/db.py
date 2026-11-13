"""SQLite による企業リスト・送信履歴・テンプレートの管理.

ステータスの考え方
------------------
- new        未送付     … 新規メールの送信対象
- sent       送付済み   … 新規メールの対象外。フォローメールの対象
- replied    返信あり   … フォローメールの対象外
- contracted 契約済み   … すべての送信対象・一覧（既定表示）から除外
- opted_out  配信停止   … すべての送信対象・一覧（既定表示）から除外
- error      送信エラー … 宛先不明など。送信対象外
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import urlparse

from .regions import extract_city, extract_prefecture, normalize_text

STATUS_NEW = "new"
STATUS_SENT = "sent"
STATUS_REPLIED = "replied"
STATUS_CONTRACTED = "contracted"
STATUS_OPTED_OUT = "opted_out"
STATUS_ERROR = "error"

STATUS_LABELS: dict[str, str] = {
    STATUS_NEW: "未送付",
    STATUS_SENT: "送付済み",
    STATUS_REPLIED: "返信あり",
    STATUS_CONTRACTED: "契約済み",
    STATUS_OPTED_OUT: "配信停止",
    STATUS_ERROR: "送信エラー",
}
LABEL_TO_STATUS: dict[str, str] = {v: k for k, v in STATUS_LABELS.items()}
LABEL_TO_STATUS.update({k: k for k in STATUS_LABELS})
LABEL_TO_STATUS.update({"送信済み": STATUS_SENT, "送付済": STATUS_SENT, "契約": STATUS_CONTRACTED,
                        "既存顧客": STATUS_CONTRACTED, "顧客": STATUS_CONTRACTED, "返信": STATUS_REPLIED,
                        "停止": STATUS_OPTED_OUT, "エラー": STATUS_ERROR, "": STATUS_NEW})

# 一覧の既定表示・すべての送信対象から外すステータス
EXCLUDED_STATUSES = (STATUS_CONTRACTED, STATUS_OPTED_OUT)

KIND_NEW = "new"
KIND_FOLLOW = "follow"
KIND_TEST = "test"

RESULT_SENT = "sent"
RESULT_FAILED = "failed"
RESULT_DRY_RUN = "dry_run"

# 同じドメイン＝同じ会社とは限らないフリーメール・プロバイダのドメイン
FREE_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.co.jp", "yahoo.com", "ymail.ne.jp", "hotmail.com",
    "hotmail.co.jp", "outlook.com", "outlook.jp", "live.jp", "live.com", "msn.com", "icloud.com",
    "me.com", "mac.com", "docomo.ne.jp", "ezweb.ne.jp", "au.com", "softbank.ne.jp", "i.softbank.jp",
    "nifty.com", "biglobe.ne.jp", "ocn.ne.jp", "so-net.ne.jp", "plala.or.jp", "excite.co.jp",
    "aol.com", "zoho.com", "proton.me", "protonmail.com", "mail.com", "gmx.com",
}

_TIME_FMT = "%Y-%m-%d %H:%M:%S"
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_CORP_WORDS = re.compile(
    r"(株式会社|有限会社|合同会社|合資会社|合名会社|一般社団法人|一般財団法人|公益社団法人|"
    r"公益財団法人|社会福祉法人|医療法人社団|医療法人|特定非営利活動法人|NPO法人|\(株\)|\(有\)|\(合\)|㈱|㈲)"
)

COMPANY_FIELDS = (
    "name", "email", "website", "phone", "address", "prefecture", "city", "industry",
    "contact_name", "description", "status", "notes", "source", "place_id",
    "first_sent_at", "last_sent_at", "follow_count",
)


def now_str() -> str:
    return datetime.now().strftime(_TIME_FMT)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in (_TIME_FMT, "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def normalize_email(email: str | None) -> str:
    value = normalize_text(email).replace("mailto:", "").strip().strip("<>").lower()
    return value if _EMAIL_RE.match(value) else ""


def email_domain(email: str | None) -> str:
    email = normalize_email(email)
    return email.split("@", 1)[1] if email else ""


def url_domain(url: str | None) -> str:
    url = normalize_text(url)
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def company_domain(email: str | None, website: str | None) -> str:
    """会社を識別するドメイン。フリーメールのドメインは使わない."""
    domain = url_domain(website)
    if domain and domain not in FREE_MAIL_DOMAINS:
        return domain
    domain = email_domain(email)
    if domain and domain not in FREE_MAIL_DOMAINS:
        return domain
    return ""


def normalize_company_name(name: str | None) -> str:
    text = unicodedata.normalize("NFKC", name or "")
    text = _CORP_WORDS.sub("", text)
    text = re.sub(r"[\s　・,，.。\-‐ー_]", "", text)
    return text.lower()


@dataclass
class ImportResult:
    added: int = 0
    updated: int = 0
    skipped: int = 0


SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    website TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    prefecture TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    industry TEXT NOT NULL DEFAULT '',
    contact_name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    follow_count INTEGER NOT NULL DEFAULT 0,
    first_sent_at TEXT,
    last_sent_at TEXT,
    last_subject TEXT NOT NULL DEFAULT '',
    last_message_id TEXT NOT NULL DEFAULT '',
    replied_at TEXT,
    contracted_at TEXT,
    notes TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    place_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_companies_email ON companies(email);
CREATE INDEX IF NOT EXISTS idx_companies_domain ON companies(domain);
CREATE INDEX IF NOT EXISTS idx_companies_status ON companies(status);
CREATE INDEX IF NOT EXISTS idx_companies_name_key ON companies(name_key);

CREATE TABLE IF NOT EXISTS send_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    company_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL,
    kind TEXT NOT NULL,
    step INTEGER NOT NULL DEFAULT 0,
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    message_id TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    sent_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_send_log_email ON send_log(email);
CREATE INDEX IF NOT EXISTS idx_send_log_sent_at ON send_log(sent_at);

CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_TEMPLATES = [
    (
        "新規開拓（標準）",
        KIND_NEW,
        "【ご提案】{会社名}様へのご案内（{送信者会社名}）",
        "{会社名}\n{担当者名}様\n\n"
        "突然のご連絡失礼いたします。\n"
        "{送信者会社名}の{送信者名}と申します。\n\n"
        "貴社のウェブサイトを拝見し、お役に立てることがあるのではと考え、ご連絡いたしました。\n\n"
        "弊社では、（ここにサービス・商品の概要を記載してください）をご提供しております。\n\n"
        "・（導入メリット1）\n"
        "・（導入メリット2）\n"
        "・（導入メリット3）\n\n"
        "もしご興味をお持ちいただけましたら、15〜30分ほどオンラインでご説明の機会を\n"
        "いただけますと幸いです。本メールにご返信いただければ、日程を調整いたします。\n\n"
        "何卒よろしくお願い申し上げます。",
    ),
    (
        "フォロー1回目",
        KIND_FOLLOW,
        "先日のご案内について（{送信者会社名}）",
        "{会社名}\n{担当者名}様\n\n"
        "お世話になっております。\n"
        "{送信者会社名}の{送信者名}です。\n\n"
        "{前回送信日}に（サービス名）についてご案内をお送りいたしましたが、\n"
        "ご覧いただけましたでしょうか。\n\n"
        "ご多用のところ恐縮ですが、少しでもご関心がございましたら、\n"
        "資料のお送りやオンラインでのご説明など、ご都合のよい形で対応いたします。\n\n"
        "ご検討のほど、よろしくお願いいたします。",
    ),
    (
        "フォロー2回目（最終）",
        KIND_FOLLOW,
        "最後のご案内（{送信者会社名}）",
        "{会社名}\n{担当者名}様\n\n"
        "お世話になっております。\n"
        "{送信者会社名}の{送信者名}です。\n\n"
        "これまで（サービス名）についてご案内をお送りしてまいりましたが、\n"
        "今回で最後のご連絡とさせていただきます。\n\n"
        "今後、もし同様の課題が出てまいりましたら、お気軽に本メールへご返信ください。\n"
        "お忙しいところ、お読みいただきありがとうございました。",
    ),
]


class Database:
    """接続はメソッド呼び出しごとに開くため、複数スレッドから安全に使える."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            seeded = conn.execute("SELECT value FROM meta WHERE key='templates_seeded'").fetchone()
            if not seeded:
                for name, kind, subject, body in DEFAULT_TEMPLATES:
                    conn.execute(
                        "INSERT INTO templates(name, kind, subject, body, updated_at) VALUES (?,?,?,?,?)",
                        (name, kind, subject, body, now_str()),
                    )
                conn.execute("INSERT INTO meta(key, value) VALUES ('templates_seeded', '1')")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------ 企業
    @staticmethod
    def _prepare(data: dict) -> dict:
        values = {k: data[k] for k in COMPANY_FIELDS if k in data and data[k] is not None}
        for key in ("name", "website", "phone", "address", "prefecture", "city", "industry",
                    "contact_name", "description", "notes", "source", "place_id"):
            if key in values:
                values[key] = normalize_text(str(values[key]))
        if "email" in values:
            values["email"] = normalize_email(values["email"])
        if "status" in values:
            values["status"] = LABEL_TO_STATUS.get(str(values["status"]).strip(), STATUS_NEW)
        if values.get("address") and not values.get("prefecture"):
            values["prefecture"] = extract_prefecture(values["address"])
        if values.get("address") and not values.get("city"):
            values["city"] = extract_city(values["address"], values.get("prefecture"))
        return values

    def add_company(self, data: dict) -> int:
        values = self._prepare(data)
        if not values.get("name"):
            raise ValueError("会社名は必須です")
        values["name_key"] = normalize_company_name(values["name"])
        values["domain"] = company_domain(values.get("email"), values.get("website"))
        values.setdefault("status", STATUS_NEW)
        if values["status"] == STATUS_CONTRACTED:
            values["contracted_at"] = now_str()
        values["created_at"] = values["updated_at"] = now_str()
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        with self._conn() as conn:
            cur = conn.execute(f"INSERT INTO companies({cols}) VALUES ({marks})", tuple(values.values()))
            return int(cur.lastrowid)

    def update_company(self, company_id: int, data: dict) -> None:
        values = self._prepare(data)
        if "name" in values:
            if not values["name"]:
                raise ValueError("会社名は必須です")
            values["name_key"] = normalize_company_name(values["name"])
        current = self.get_company(company_id)
        if current is None:
            raise KeyError(company_id)
        if "email" in values or "website" in values:
            values["domain"] = company_domain(
                values.get("email", current["email"]), values.get("website", current["website"])
            )
        if values.get("status") == STATUS_CONTRACTED and current["status"] != STATUS_CONTRACTED:
            values["contracted_at"] = now_str()
        if values.get("status") == STATUS_REPLIED and current["status"] != STATUS_REPLIED:
            values["replied_at"] = now_str()
        values["updated_at"] = now_str()
        assignments = ", ".join(f"{k} = ?" for k in values)
        with self._conn() as conn:
            conn.execute(f"UPDATE companies SET {assignments} WHERE id = ?", (*values.values(), company_id))

    def delete_companies(self, ids: Iterable[int]) -> None:
        ids = list(ids)
        if not ids:
            return
        with self._conn() as conn:
            conn.executemany("DELETE FROM companies WHERE id = ?", [(i,) for i in ids])

    def get_company(self, company_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
            return dict(row) if row else None

    def set_status(self, ids: Iterable[int], status: str) -> None:
        stamp = now_str()
        extra = ""
        if status == STATUS_CONTRACTED:
            extra = ", contracted_at = COALESCE(contracted_at, :stamp)"
        elif status == STATUS_REPLIED:
            extra = ", replied_at = COALESCE(replied_at, :stamp)"
        with self._conn() as conn:
            conn.executemany(
                f"UPDATE companies SET status = :status, updated_at = :stamp{extra} WHERE id = :id",
                [{"status": status, "stamp": stamp, "id": i} for i in ids],
            )

    def list_companies(
        self,
        status_filter: str = "active",
        prefectures: Iterable[str] | None = None,
        search: str = "",
        limit: int | None = None,
    ) -> list[dict]:
        """status_filter: 'active'（契約済み・配信停止を除く）/ 'all' / 各ステータス値."""
        where, params = [], []
        if status_filter == "active":
            where.append(f"status NOT IN ({','.join('?' * len(EXCLUDED_STATUSES))})")
            params.extend(EXCLUDED_STATUSES)
        elif status_filter != "all":
            where.append("status = ?")
            params.append(status_filter)
        prefs = list(prefectures or [])
        if prefs:
            where.append(f"prefecture IN ({','.join('?' * len(prefs))})")
            params.extend(prefs)
        search = normalize_text(search)
        if search:
            like = f"%{search}%"
            where.append("(name LIKE ? OR email LIKE ? OR industry LIKE ? OR city LIKE ? "
                         "OR address LIKE ? OR notes LIKE ? OR website LIKE ?)")
            params.extend([like] * 7)
        sql = "SELECT * FROM companies"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def find_duplicate(
        self,
        name: str = "",
        email: str = "",
        website: str = "",
        place_id: str = "",
        prefecture: str = "",
    ) -> dict | None:
        """既に登録済みの企業を探す（メール → ドメイン → Google Place ID → 会社名+都道府県 の順）."""
        email = normalize_email(email)
        domain = company_domain(email, website)
        name_key = normalize_company_name(name)
        with self._conn() as conn:
            if email:
                row = conn.execute("SELECT * FROM companies WHERE email = ? LIMIT 1", (email,)).fetchone()
                if row:
                    return dict(row)
            if domain:
                row = conn.execute("SELECT * FROM companies WHERE domain = ? LIMIT 1", (domain,)).fetchone()
                if row:
                    return dict(row)
            if place_id:
                row = conn.execute("SELECT * FROM companies WHERE place_id = ? LIMIT 1", (place_id,)).fetchone()
                if row:
                    return dict(row)
            if name_key:
                if prefecture:
                    row = conn.execute(
                        "SELECT * FROM companies WHERE name_key = ? AND (prefecture = ? OR prefecture = '') LIMIT 1",
                        (name_key, prefecture),
                    ).fetchone()
                else:
                    row = conn.execute("SELECT * FROM companies WHERE name_key = ? LIMIT 1", (name_key,)).fetchone()
                if row:
                    return dict(row)
        return None

    def was_ever_sent(self, email: str, website: str = "") -> bool:
        """このアドレス、または同じ会社ドメインに一度でも実送信したことがあるか."""
        email = normalize_email(email)
        domain = company_domain(email, website)
        with self._conn() as conn:
            params: list = [RESULT_SENT, KIND_NEW, KIND_FOLLOW]
            cond = "lower(email) = ?"
            params.append(email)
            if domain:
                cond += " OR lower(email) LIKE ?"
                params.append(f"%@{domain}")
            row = conn.execute(
                f"SELECT 1 FROM send_log WHERE result = ? AND kind IN (?, ?) AND ({cond}) LIMIT 1", params
            ).fetchone()
            return row is not None

    def import_rows(self, rows: Iterable[dict], status: str = STATUS_NEW) -> ImportResult:
        """CSV などから一括登録する。

        status が「契約済み」「配信停止」「送付済み」の場合、既に登録済みの企業は
        そのステータスに更新する（既存顧客をリストから除外するための取り込み）。
        """
        result = ImportResult()
        for row in rows:
            name = normalize_text(row.get("name"))
            if not name:
                result.skipped += 1
                continue
            row_status = LABEL_TO_STATUS.get(normalize_text(row.get("status")), None) if row.get("status") else None
            target_status = row_status or status
            sent_dt = parse_time(row.get("last_sent_at"))
            sent_at = sent_dt.strftime(_TIME_FMT) if sent_dt else None
            prefecture = normalize_text(row.get("prefecture")) or extract_prefecture(row.get("address"))
            dup = self.find_duplicate(name, row.get("email", ""), row.get("website", ""),
                                      row.get("place_id", ""), prefecture)
            if dup:
                if target_status in (STATUS_CONTRACTED, STATUS_OPTED_OUT, STATUS_REPLIED) and dup["status"] != target_status:
                    self.set_status([dup["id"]], target_status)
                    result.updated += 1
                elif target_status == STATUS_SENT and dup["status"] == STATUS_NEW:
                    self.update_company(dup["id"], {"status": STATUS_SENT, "last_sent_at": sent_at,
                                                    "first_sent_at": sent_at})
                    result.updated += 1
                else:
                    result.skipped += 1
                continue
            data = dict(row)
            data["status"] = target_status
            data.pop("last_sent_at", None)
            if target_status == STATUS_SENT and sent_at:
                data["last_sent_at"] = data["first_sent_at"] = sent_at
            self.add_company(data)
            result.added += 1
        return result

    # ------------------------------------------------------------ 送信対象
    def new_targets(self, prefectures: Iterable[str] | None = None, keywords: Iterable[str] | None = None) -> list[dict]:
        """新規メールの送信対象。

        未送付・メールあり・契約済み/配信停止でない企業のうち、
        同じアドレス／同じ会社ドメインに過去送信していないものだけを返す。
        """
        where = ["status = ?", "email <> ''"]
        params: list = [STATUS_NEW]
        prefs = list(prefectures or [])
        if prefs:
            where.append(f"prefecture IN ({','.join('?' * len(prefs))})")
            params.extend(prefs)
        kws = [normalize_text(k) for k in (keywords or []) if normalize_text(k)]
        if kws:
            where.append("(" + " OR ".join("(industry LIKE ? OR name LIKE ? OR description LIKE ?)" for _ in kws) + ")")
            for k in kws:
                params.extend([f"%{k}%"] * 3)
        sql = f"SELECT * FROM companies WHERE {' AND '.join(where)} ORDER BY id"
        with self._conn() as conn:
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
            excluded_domains = {
                r["domain"] for r in conn.execute(
                    "SELECT DISTINCT domain FROM companies WHERE domain <> '' AND status <> ?", (STATUS_NEW,)
                ).fetchall()
            }
        targets, seen = [], set()
        for row in rows:
            key = row["domain"] or row["email"]
            if key in seen:  # 同じ会社に二重送信しない
                continue
            if row["domain"] and row["domain"] in excluded_domains:
                continue
            if self.was_ever_sent(row["email"], row["website"]):
                continue
            seen.add(key)
            targets.append(row)
        return targets

    def follow_targets(
        self,
        min_days: int,
        max_follow: int,
        prefectures: Iterable[str] | None = None,
        follow_count: int | None = None,
        now: datetime | None = None,
    ) -> list[dict]:
        """フォローメールの送信対象（送付済み・返信なし・規定日数経過・回数上限未満）."""
        cutoff = ((now or datetime.now()) - timedelta(days=min_days)).strftime(_TIME_FMT)
        where = ["status = ?", "email <> ''", "follow_count < ?", "(last_sent_at IS NULL OR last_sent_at <= ?)"]
        params: list = [STATUS_SENT, max_follow, cutoff]
        if follow_count is not None:
            where.append("follow_count = ?")
            params.append(follow_count)
        prefs = list(prefectures or [])
        if prefs:
            where.append(f"prefecture IN ({','.join('?' * len(prefs))})")
            params.extend(prefs)
        sql = f"SELECT * FROM companies WHERE {' AND '.join(where)} ORDER BY last_sent_at, id"
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def is_still_eligible(self, company_id: int, kind: str, max_follow: int | None = None) -> bool:
        """送信直前の再確認（別画面でステータスが変わっていないか）."""
        company = self.get_company(company_id)
        if not company or not company["email"]:
            return False
        if kind == KIND_NEW:
            return company["status"] == STATUS_NEW and not self.was_ever_sent(company["email"], company["website"])
        if kind == KIND_FOLLOW:
            if company["status"] != STATUS_SENT:
                return False
            return max_follow is None or company["follow_count"] < max_follow
        return True

    # ------------------------------------------------------------ 送信履歴
    def record_send(
        self,
        company_id: int | None,
        email: str,
        kind: str,
        subject: str,
        body: str,
        result: str,
        message_id: str = "",
        error: str = "",
        step: int = 0,
        company_name: str = "",
    ) -> None:
        stamp = now_str()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO send_log(company_id, company_name, email, kind, step, subject, body, message_id,"
                " result, error, sent_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (company_id, company_name, email, kind, step, subject, body, message_id, result, error, stamp),
            )
            if result != RESULT_SENT or not company_id:
                return
            if kind == KIND_NEW:
                conn.execute(
                    "UPDATE companies SET status = CASE WHEN status IN (?, ?) THEN ? ELSE status END,"
                    " first_sent_at = COALESCE(first_sent_at, ?), last_sent_at = ?, last_subject = ?,"
                    " last_message_id = ?, updated_at = ? WHERE id = ?",
                    (STATUS_NEW, STATUS_ERROR, STATUS_SENT, stamp, stamp, subject, message_id, stamp, company_id),
                )
            elif kind == KIND_FOLLOW:
                conn.execute(
                    "UPDATE companies SET follow_count = follow_count + 1, last_sent_at = ?, last_subject = ?,"
                    " last_message_id = ?, updated_at = ? WHERE id = ?",
                    (stamp, subject, message_id, stamp, company_id),
                )

    def count_sent_today(self) -> int:
        start = datetime.now().strftime("%Y-%m-%d 00:00:00")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM send_log WHERE result = ? AND sent_at >= ?", (RESULT_SENT, start)
            ).fetchone()
            return int(row[0])

    def list_send_log(self, kind: str | None = None, result: str | None = None, limit: int = 2000) -> list[dict]:
        where, params = [], []
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if result:
            where.append("result = ?")
            params.append(result)
        sql = "SELECT * FROM send_log"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY id DESC LIMIT {int(limit)}"
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def sent_message_ids(self) -> dict[str, int]:
        """送信済みメールの Message-ID → company_id."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT message_id, company_id FROM send_log WHERE result = ? AND message_id <> ''"
                " AND company_id IS NOT NULL",
                (RESULT_SENT,),
            ).fetchall()
            return {r["message_id"]: r["company_id"] for r in rows}

    def stats(self) -> dict[str, int]:
        with self._conn() as conn:
            counts = {s: 0 for s in STATUS_LABELS}
            for row in conn.execute("SELECT status, COUNT(*) AS n FROM companies GROUP BY status"):
                counts[row["status"]] = row["n"]
        counts["today"] = self.count_sent_today()
        return counts

    # ------------------------------------------------------------ テンプレート
    def list_templates(self, kind: str | None = None) -> list[dict]:
        with self._conn() as conn:
            if kind:
                rows = conn.execute("SELECT * FROM templates WHERE kind = ? ORDER BY id", (kind,)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM templates ORDER BY CASE kind WHEN ? THEN 0 ELSE 1 END, id", (KIND_NEW,)
                ).fetchall()
            return [dict(r) for r in rows]

    def get_template(self, template_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
            return dict(row) if row else None

    def save_template(self, template_id: int | None, name: str, kind: str, subject: str, body: str) -> int:
        if not name.strip():
            raise ValueError("テンプレート名は必須です")
        with self._conn() as conn:
            if template_id:
                conn.execute(
                    "UPDATE templates SET name = ?, kind = ?, subject = ?, body = ?, updated_at = ? WHERE id = ?",
                    (name, kind, subject, body, now_str(), template_id),
                )
                return template_id
            cur = conn.execute(
                "INSERT INTO templates(name, kind, subject, body, updated_at) VALUES (?,?,?,?,?)",
                (name, kind, subject, body, now_str()),
            )
            return int(cur.lastrowid)

    def delete_template(self, template_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
