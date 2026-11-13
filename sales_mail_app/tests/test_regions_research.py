import pytest

from sales_mailer.ai import parse_prospects_json
from sales_mailer.regions import PREFECTURES, extract_city, extract_prefecture
from sales_mailer.research import (
    GooglePlacesSearcher, _LinkParser, build_queries, deobfuscate, extract_emails, rank_emails,
)


def test_47_prefectures():
    assert len(PREFECTURES) == 47


@pytest.mark.parametrize("address, pref, city", [
    ("日本、〒150-0002 東京都渋谷区渋谷２丁目", "東京都", "渋谷区"),
    ("東京都新宿区市谷本村町5-1", "東京都", "新宿区"),
    ("神奈川県横浜市中区本町6-50", "神奈川県", "横浜市"),
    ("三重県四日市市諏訪町1-5", "三重県", "四日市市"),
    ("東京都町田市森野2-2-22", "東京都", "町田市"),
    ("東京都西多摩郡瑞穂町箱根ケ崎2335", "東京都", "西多摩郡瑞穂町"),
    ("奈良県大和郡山市北郡山町248-4", "奈良県", "大和郡山市"),
    ("福島県郡山市朝日1-23-7", "福島県", "郡山市"),
    ("北海道札幌市中央区北1条西2丁目", "北海道", "札幌市"),
    ("大阪市北区梅田1-1", "大阪府", "大阪市"),
    ("福島区海老江1-1", "", ""),
])
def test_extract_prefecture_and_city(address, pref, city):
    assert extract_prefecture(address) == pref
    if pref:
        assert extract_city(address) == city


def test_build_queries():
    q = build_queries(["製造業", "建設"], ["愛知県"], [])
    assert q == [("製造業 愛知県", "愛知県"), ("建設 愛知県", "愛知県")]
    q = build_queries(["IT"], ["東京都", "広島県"], ["府中市"])
    assert q == [("IT 東京都府中市", "東京都"), ("IT 広島県府中市", "広島県")]
    # 政令指定都市は都道府県が自動で決まる
    assert build_queries(["IT"], ["東京都"], ["横浜市"]) == [("IT 横浜市", "神奈川県")]
    q = build_queries(["IT"], [], ["大阪府大阪市"])
    assert q == [("IT 大阪府大阪市", "大阪府")]


def test_deobfuscate_and_extract():
    assert deobfuscate("info[at]foo.co.jp") == "info@foo.co.jp"
    assert deobfuscate("info（アット）foo.co.jp") == "info@foo.co.jp"
    text = "お問い合わせ: ｉｎｆｏ＠ｆｏｏ．ｃｏ．ｊｐ / logo@2x.png / user@example.com / noreply@foo.co.jp"
    assert extract_emails(text) == ["info@foo.co.jp"]


def test_rank_prefers_same_domain_and_contact():
    ranked = rank_emails(["recruit@foo.co.jp", "someone@gmail.com", "info@foo.co.jp", "x@other.jp"],
                         "https://www.foo.co.jp/")
    assert ranked[0] == "info@foo.co.jp"
    assert ranked[1] == "recruit@foo.co.jp"


def test_link_parser_collects_mailto_and_contact_links():
    p = _LinkParser()
    p.feed('<a href="/contact/">お問い合わせ</a><a href="mailto:sales@foo.co.jp?subject=x">mail</a>'
           '<script>var a="hidden@foo.co.jp"</script><p>TEL 03</p>')
    assert ("/contact/", "お問い合わせ") in p.links
    assert p.mailtos == ["sales@foo.co.jp"]
    assert "hidden@foo.co.jp" not in p.text


def test_places_to_prospect():
    place = {
        "id": "abc",
        "displayName": {"text": "株式会社サンプル"},
        "formattedAddress": "日本、〒460-0008 愛知県名古屋市中区栄1-1-1",
        "addressComponents": [
            {"longText": "愛知県", "types": ["administrative_area_level_1", "political"]},
            {"longText": "名古屋市", "types": ["locality", "political"]},
        ],
        "websiteUri": "https://sample.co.jp/",
        "nationalPhoneNumber": "052-000-0000",
        "primaryTypeDisplayName": {"text": "建設会社"},
    }
    p = GooglePlacesSearcher._to_prospect(place)
    assert (p.name, p.prefecture, p.city, p.industry, p.place_id) == (
        "株式会社サンプル", "愛知県", "名古屋市", "建設会社", "abc")
    assert p.address.startswith("〒460")


def test_parse_prospects_json():
    text = 'ok\n```json\n[{"name": "A社", "email": ""}, "bad"]\n```'
    assert parse_prospects_json(text) == [{"name": "A社", "email": ""}]
    assert parse_prospects_json("no json") == []
