import pytest

from sales_mailer.csv_io import read_companies_csv, write_companies_csv


def test_read_shift_jis_with_japanese_headers(tmp_path):
    path = tmp_path / "list.csv"
    path.write_bytes("会社名,メールアドレス,ホームページ,所在地,ステータス\n"
                     "株式会社A,info@a.co.jp,https://a.co.jp,東京都港区1-1,契約済み\n".encode("cp932"))
    rows, recognized = read_companies_csv(path)
    assert recognized == ["会社名", "メールアドレス", "ホームページ", "所在地", "ステータス"]
    assert rows == [{"name": "株式会社A", "email": "info@a.co.jp", "website": "https://a.co.jp",
                     "address": "東京都港区1-1", "status": "契約済み"}]


def test_missing_name_column(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("email\nx@y.jp\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_companies_csv(path)


def test_roundtrip(tmp_path, db):
    db.add_company({"name": "B社", "email": "b@b.jp", "address": "大阪府大阪市北区1-1"})
    path = tmp_path / "out.csv"
    write_companies_csv(path, db.list_companies())
    rows, _ = read_companies_csv(path)
    assert rows[0]["name"] == "B社" and rows[0]["status"] == "未送付" and rows[0]["prefecture"] == "大阪府"
