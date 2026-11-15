"""Excel（.xlsx）の取り込み・書き出しと、ドメイン確認のテスト."""

import socket
from datetime import datetime

import pytest

openpyxl = pytest.importorskip("openpyxl")

from sales_mailer.csv_io import read_companies_file, write_companies, write_import_template, write_rows  # noqa: E402
from sales_mailer.db import STATUS_CONTRACTED, STATUS_ERROR, STATUS_NEW  # noqa: E402
from sales_mailer.email_check import DomainChecker  # noqa: E402
from sales_mailer.services import import_companies  # noqa: E402


def make_xlsx(path, rows, title_rows=()):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in title_rows:
        ws.append(r)
    for r in rows:
        ws.append(r)
    wb.save(path)


def test_reads_gpt_style_sheet_with_title_row(tmp_path):
    path = tmp_path / "list.xlsx"
    make_xlsx(path, [
        ["No.", "会社名（正式名称）", "メールアドレス", "電話番号", "公式サイト", "業種"],
        [1, "株式会社テスト", "info@test.co.jp", 223334444, "https://test.co.jp", "製造業"],
        [2, "　空白入り株式会社　", None, None, None, None],
        [None, None, None, None, None, None],
    ], title_rows=[["仙台市の製造業リスト（GPT作成）"]])
    rows, recognized = read_companies_file(path)
    assert recognized == ["会社名（正式名称）", "メールアドレス", "電話番号", "公式サイト", "業種"]
    assert rows[0] == {"name": "株式会社テスト", "email": "info@test.co.jp", "phone": "223334444",
                       "website": "https://test.co.jp", "industry": "製造業"}
    assert rows[1] == {"name": "空白入り株式会社"}
    assert len(rows) == 2


def test_dates_and_old_format(tmp_path):
    path = tmp_path / "d.xlsx"
    make_xlsx(path, [["会社名", "送信日"], ["A社", datetime(2026, 10, 1)]])
    rows, _ = read_companies_file(path)
    assert rows[0]["last_sent_at"] == "2026-10-01"
    with pytest.raises(ValueError, match="xlsx"):
        read_companies_file(tmp_path / "old.xls")


def test_missing_name_column(tmp_path):
    path = tmp_path / "x.xlsx"
    make_xlsx(path, [["メール"], ["a@b.jp"]])
    with pytest.raises(ValueError, match="会社名"):
        read_companies_file(path)


def test_template_roundtrip(tmp_path):
    path = tmp_path / "ひな形.xlsx"
    write_import_template(path)
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["企業リスト", "使い方"]
    rows, recognized = read_companies_file(path)
    assert "会社名" in recognized and "メールアドレス" in recognized
    assert rows[0]["name"] == "株式会社サンプル製作所"


def test_export_xlsx_and_csv(tmp_path, db):
    db.add_company({"name": "B社", "email": "b@b.jp", "address": "大阪府大阪市北区1-1"})
    write_companies(tmp_path / "out.xlsx", db.list_companies())
    write_companies(tmp_path / "out.csv", db.list_companies())
    for name in ("out.xlsx", "out.csv"):
        rows, _ = read_companies_file(tmp_path / name)
        assert rows[0]["name"] == "B社" and rows[0]["status"] == "未送付"
    write_rows(tmp_path / "h.xlsx", ["日時", "会社名"], [["2026-11-01", "A社"]], "送信履歴")
    assert openpyxl.load_workbook(tmp_path / "h.xlsx").sheetnames == ["送信履歴"]


def fake_resolver(existing):
    def resolve(host):
        if host in existing:
            return [("ok",)]
        raise socket.gaierror(socket.EAI_NONAME, "not found")
    return resolve


def test_domain_checker():
    checker = DomainChecker(fake_resolver({"www.google.com", "real.co.jp", "www.mailonly.jp"}))
    result = checker.check_emails(["info@real.co.jp", "a@fake-ai-made.co.jp", "b@mailonly.jp"])
    assert result == {"info@real.co.jp": True, "a@fake-ai-made.co.jp": False, "b@mailonly.jp": True}


def test_domain_checker_offline_is_unknown():
    checker = DomainChecker(fake_resolver(set()))
    assert checker.check_emails(["info@real.co.jp"]) == {"info@real.co.jp": None}
    assert not checker.online()


def test_import_marks_nonexistent_domains(tmp_path, db):
    path = tmp_path / "gpt.xlsx"
    make_xlsx(path, [
        ["会社名", "メールアドレス"],
        ["本物株式会社", "info@real.co.jp"],
        ["架空株式会社", "info@fake-ai-made.co.jp"],
        ["メールなし株式会社", ""],
        ["形式不正株式会社", "info@@bad"],
    ])
    checker = DomainChecker(fake_resolver({"www.google.com", "real.co.jp"}))
    report = import_companies(db, path, checker=checker)
    assert (report.total, report.added, report.no_email) == (4, 4, 2)
    assert report.bad_domain == ["架空株式会社 <info@fake-ai-made.co.jp>"]
    fake = db.find_duplicate("架空株式会社")
    assert fake["status"] == STATUS_ERROR and "ドメインが存在しない" in fake["notes"]
    assert [c["name"] for c in db.new_targets()] == ["本物株式会社"]  # 送信対象は実在ドメインだけ
    assert "存在しないドメイン" in report.text()


def test_import_contracted_skips_domain_check(tmp_path, db):
    path = tmp_path / "customers.xlsx"
    make_xlsx(path, [["会社名", "メールアドレス"], ["既存顧客株式会社", "info@fake-ai-made.co.jp"]])

    class NoCheck:
        def check_emails(self, *a, **k):
            raise AssertionError("契約済みの取り込みでは確認しない")

    report = import_companies(db, path, status=STATUS_CONTRACTED, checker=NoCheck())
    assert report.added == 1
    assert db.find_duplicate("既存顧客株式会社")["status"] == STATUS_CONTRACTED
    assert db.stats()[STATUS_NEW] == 0
