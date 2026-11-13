"""CSV の取り込み・書き出し（Excel で開ける UTF-8 BOM 付き / Shift_JIS 読み込み対応）."""

from __future__ import annotations

import csv
import io
import unicodedata
from pathlib import Path

from .db import STATUS_LABELS

COLUMN_ALIASES: dict[str, list[str]] = {
    "name": ["会社名", "企業名", "社名", "法人名", "name", "company", "company_name", "会社"],
    "email": ["メールアドレス", "メール", "email", "e-mail", "mail", "メアド", "mailaddress"],
    "website": ["webサイト", "ウェブサイト", "url", "website", "ホームページ", "hp", "サイト", "homepage"],
    "phone": ["電話番号", "電話", "tel", "phone"],
    "address": ["住所", "所在地", "address"],
    "prefecture": ["都道府県", "prefecture", "県"],
    "city": ["市区町村", "city", "市町村"],
    "industry": ["業種", "industry", "業界"],
    "contact_name": ["担当者名", "担当者", "contact", "contact_name"],
    "status": ["ステータス", "状態", "status"],
    "notes": ["備考", "メモ", "notes", "note"],
    "last_sent_at": ["最終送信日", "送付日", "送信日", "last_sent_at"],
    "description": ["事業内容", "説明", "description", "概要"],
}

EXPORT_COLUMNS = [
    ("id", "ID"), ("name", "会社名"), ("status", "ステータス"), ("email", "メールアドレス"),
    ("website", "Webサイト"), ("phone", "電話番号"), ("address", "住所"), ("prefecture", "都道府県"),
    ("city", "市区町村"), ("industry", "業種"), ("contact_name", "担当者名"), ("first_sent_at", "初回送信日"),
    ("last_sent_at", "最終送信日"), ("follow_count", "フォロー回数"), ("contracted_at", "契約日"),
    ("description", "事業内容"), ("notes", "備考"), ("source", "取得元"),
]


def _norm(header: str) -> str:
    return unicodedata.normalize("NFKC", header or "").strip().lower().replace(" ", "").replace("_", "")


def _map_headers(headers: list[str]) -> dict[int, str]:
    lookup = {}
    for key, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            lookup.setdefault(_norm(alias), key)
    mapping: dict[int, str] = {}
    used: set[str] = set()
    for i, header in enumerate(headers):
        key = lookup.get(_norm(header))
        if key and key not in used:
            mapping[i] = key
            used.add(key)
    return mapping


def read_text(path: str | Path) -> str:
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp932", "euc-jp"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def read_companies_csv(path: str | Path) -> tuple[list[dict], list[str]]:
    """CSV を読み込み、(行データ, 認識できた列名) を返す."""
    text = read_text(path)
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return [], []
    mapping = _map_headers(rows[0])
    if "name" not in mapping.values():
        raise ValueError("「会社名」列が見つかりません。1行目に列名（会社名, メールアドレス など）を入れてください。")
    result = []
    for row in rows[1:]:
        item = {key: row[i].strip() for i, key in mapping.items() if i < len(row)}
        result.append(item)
    recognized = [rows[0][i] for i in sorted(mapping)]
    return result, recognized


def write_companies_csv(path: str | Path, companies: list[dict]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([label for _, label in EXPORT_COLUMNS])
        for c in companies:
            values = []
            for key, _ in EXPORT_COLUMNS:
                value = c.get(key, "")
                if key == "status":
                    value = STATUS_LABELS.get(value, value)
                values.append("" if value is None else value)
            writer.writerow(values)


def write_rows_csv(path: str | Path, headers: list[str], rows: list[list]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
