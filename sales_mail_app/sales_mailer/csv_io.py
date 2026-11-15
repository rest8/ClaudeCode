"""Excel（.xlsx）・CSV の取り込みと書き出し.

- 取り込み: .xlsx / .xlsm（1枚目のシート）と CSV（UTF-8 / Shift_JIS）。先頭の10行から列名の行を探すので、
  GPT などで作った表の上にタイトル行があっても読み込める。
- 書き出し: 拡張子が .xlsx なら Excel、.csv なら Excel で開ける UTF-8（BOM 付き）の CSV。
"""

from __future__ import annotations

import csv
import io
import unicodedata
from datetime import date, datetime
from pathlib import Path

from .db import STATUS_LABELS

COLUMN_ALIASES: dict[str, list[str]] = {
    "name": ["会社名", "企業名", "社名", "法人名", "会社名称", "企業名称", "name", "company", "company_name", "会社"],
    "email": ["メールアドレス", "メール", "eメール", "email", "e-mail", "mail", "メアド", "mailaddress",
              "問い合わせメール", "連絡先メール"],
    "website": ["webサイト", "ウェブサイト", "url", "website", "ホームページ", "hp", "サイト", "homepage",
                "公式サイト", "企業サイト", "サイトurl"],
    "phone": ["電話番号", "電話", "tel", "phone", "代表電話", "連絡先電話"],
    "address": ["住所", "所在地", "address", "本社所在地"],
    "prefecture": ["都道府県", "prefecture", "県"],
    "city": ["市区町村", "city", "市町村"],
    "industry": ["業種", "industry", "業界"],
    "contact_name": ["担当者名", "担当者", "contact", "contact_name", "代表者名", "代表者"],
    "status": ["ステータス", "状態", "status"],
    "notes": ["備考", "メモ", "notes", "note"],
    "last_sent_at": ["最終送信日", "送付日", "送信日", "last_sent_at"],
    "description": ["事業内容", "説明", "description", "概要", "特徴"],
}

EXPORT_COLUMNS = [
    ("id", "ID"), ("name", "会社名"), ("status", "ステータス"), ("email", "メールアドレス"),
    ("website", "Webサイト"), ("phone", "電話番号"), ("address", "住所"), ("prefecture", "都道府県"),
    ("city", "市区町村"), ("industry", "業種"), ("contact_name", "担当者名"), ("first_sent_at", "初回送信日"),
    ("last_sent_at", "最終送信日"), ("follow_count", "フォロー回数"), ("contracted_at", "契約日"),
    ("description", "事業内容"), ("notes", "備考"), ("source", "取得元"),
]

# 取り込み用ひな形の列（GPT にこの列名で表を作ってもらう）
TEMPLATE_COLUMNS = ["会社名", "メールアドレス", "担当者名", "業種", "住所", "電話番号", "Webサイト", "備考"]
TEMPLATE_EXAMPLES = [
    ["株式会社サンプル製作所", "info@sample-seisakusho.example.com", "", "製造業", "宮城県仙台市青葉区1-1-1",
     "022-000-0000", "https://www.sample-seisakusho.example.com", "（この行は例です。削除してください）"],
]
GPT_PROMPT_EXAMPLE = (
    "宮城県仙台市にある製造業の企業を30社、表にしてください。"
    "列は「会社名・メールアドレス・担当者名・業種・住所・電話番号・Webサイト」にしてください。"
    "メールアドレスは各社の公式サイトに掲載されている問い合わせ用のものだけを書き、"
    "見つからない場合や不確かな場合は空欄にしてください。最後に Excel（.xlsx）ファイルでダウンロードできるようにしてください。"
)


def _norm(header: str) -> str:
    return unicodedata.normalize("NFKC", str(header or "")).strip().lower().replace(" ", "").replace("_", "")


def _map_headers(headers: list[str]) -> dict[int, str]:
    lookup: dict[str, str] = {}
    for key, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            lookup.setdefault(_norm(alias), key)
    mapping: dict[int, str] = {}
    used: set[str] = set()
    for i, header in enumerate(headers):  # 1. 列名が完全に一致するもの
        key = lookup.get(_norm(header))
        if key and key not in used:
            mapping[i] = key
            used.add(key)
    by_length = sorted(lookup.items(), key=lambda kv: len(kv[0]), reverse=True)
    for i, header in enumerate(headers):  # 2. 「会社名（正式名称）」のように列名を含むもの
        if i in mapping or not _norm(header):
            continue
        for alias, key in by_length:
            if len(alias) >= 2 and alias in _norm(header) and key not in used:
                mapping[i] = key
                used.add(key)
                break
    return mapping


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S") if (value.hour or value.minute) else value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value).replace("\u3000", " ").strip()


def read_text(path: str | Path) -> str:
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp932", "euc-jp"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _read_xlsx_rows(path: Path) -> list[list[str]]:
    try:
        from openpyxl import load_workbook
    except ImportError as e:  # pragma: no cover - requirements.txt で導入
        raise ValueError("Excel を読み込むには openpyxl が必要です（pip install openpyxl）") from e
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 - 壊れたファイル・パスワード付きなど
        raise ValueError(f"Excel ファイルを開けませんでした（{e}）。Excel で開いて保存し直してからお試しください。") from e
    try:
        best: list[list[str]] = []
        for sheet in workbook.worksheets:  # 「会社名」列があるシートを使う（無ければ1枚目）
            rows = [[_cell_text(v) for v in row] for row in sheet.iter_rows(values_only=True)]
            rows = [r for r in rows if any(r)]
            if _find_header(rows) is not None:
                return rows
            if not best:
                best = rows
        return best
    finally:
        workbook.close()


def _find_header(rows: list[list[str]]) -> int | None:
    for index, row in enumerate(rows[:10]):
        if "name" in _map_headers(row).values():
            return index
    return None


def read_companies_file(path: str | Path) -> tuple[list[dict], list[str]]:
    """Excel / CSV を読み込み、(行データ, 認識できた列名) を返す."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".xls":
        raise ValueError("古い Excel 形式（.xls）は読み込めません。Excel で「名前を付けて保存」→"
                         "「Excel ブック (*.xlsx)」で保存し直してから取り込んでください。")
    if suffix in (".xlsx", ".xlsm"):
        rows = _read_xlsx_rows(path)
    else:
        reader = csv.reader(io.StringIO(read_text(path)))
        rows = [[c.strip() for c in r] for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return [], []
    header_index = _find_header(rows)
    if header_index is None:
        raise ValueError("「会社名」の列が見つかりません。1行目に列名（会社名, メールアドレス など）を入れてください。")
    header = rows[header_index]
    mapping = _map_headers(header)
    result = []
    for row in rows[header_index + 1:]:
        item = {key: row[i].strip() for i, key in mapping.items() if i < len(row) and row[i]}
        if item:
            result.append(item)
    recognized = [header[i] for i in sorted(mapping)]
    return result, recognized


# 以前の名前（CSV 専用だったとき）でも呼べるようにしておく
read_companies_csv = read_companies_file


def _company_row(c: dict) -> list:
    values = []
    for key, _ in EXPORT_COLUMNS:
        value = c.get(key, "")
        if key == "status":
            value = STATUS_LABELS.get(value, value)
        values.append("" if value is None else value)
    return values


def write_rows(path: str | Path, headers: list[str], rows: list[list], sheet_title: str = "データ") -> None:
    """拡張子に合わせて Excel（.xlsx）または CSV で書き出す."""
    path = Path(path)
    if path.suffix.lower() == ".xlsx":
        _write_xlsx(path, [(sheet_title, headers, rows)])
        return
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def write_companies(path: str | Path, companies: list[dict]) -> None:
    write_rows(path, [label for _, label in EXPORT_COLUMNS], [_company_row(c) for c in companies], "企業リスト")


# 以前の名前でも呼べるようにしておく
write_companies_csv = write_companies
write_rows_csv = write_rows


def write_import_template(path: str | Path) -> None:
    """取り込み用のひな形（列名と例の行、使い方のシート）を書き出す."""
    howto = [
        ["このファイルの使い方"],
        ["1. 「企業リスト」シートの2行目（例の行）を消して、3行目以降に企業を入力します。"],
        ["2. 列名（1行目）はそのままにしてください。使わない列は空欄で構いません（会社名とメールアドレスは必須）。"],
        ["3. 保存したら、アプリの「自動送信」タブの「Excelを取り込む」から読み込みます。"],
        [""],
        ["GPT などの AI にリストを作ってもらうときの頼み方（例）"],
        [GPT_PROMPT_EXAMPLE],
        [""],
        ["注意: AI はメールアドレスを推測で作ることがあります。取り込み時に存在しないドメインは自動で送信対象外にしますが、"
         "各社の公式サイトに掲載されているアドレスか確認してから送ってください。"],
    ]
    _write_xlsx(Path(path), [("企業リスト", TEMPLATE_COLUMNS, TEMPLATE_EXAMPLES), ("使い方", [], howto)])


def _write_xlsx(path: Path, sheets: list[tuple[str, list[str], list[list]]]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, headers, rows in sheets:
        sheet = workbook.create_sheet(title)
        if headers:
            sheet.append(headers)
            for cell in sheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="1C5CC4")
            sheet.freeze_panes = "A2"
        for row in rows:
            sheet.append(["" if v is None else v for v in row])
        widths: dict[int, int] = {}
        for row in ([headers] if headers else []) + rows:
            for i, value in enumerate(row, 1):
                text = str(value or "")
                width = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
                widths[i] = min(max(widths.get(i, 8), width + 2), 60 if headers else 120)
        for i, width in widths.items():
            sheet.column_dimensions[get_column_letter(i)].width = width
    workbook.save(path)
