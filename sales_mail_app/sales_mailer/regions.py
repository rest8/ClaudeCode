"""日本の地方・都道府県データと、住所から都道府県/市区町村を取り出す処理."""

from __future__ import annotations

import re
import unicodedata

REGIONS: dict[str, list[str]] = {
    "北海道": ["北海道"],
    "東北": ["青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県"],
    "関東": ["茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県"],
    "中部": ["新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県", "愛知県"],
    "近畿": ["三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県"],
    "中国": ["鳥取県", "島根県", "岡山県", "広島県", "山口県"],
    "四国": ["徳島県", "香川県", "愛媛県", "高知県"],
    "九州・沖縄": ["福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"],
}

PREFECTURES: list[str] = [p for prefs in REGIONS.values() for p in prefs]

# 市区町村名の途中に「市・区・町・村・郡」を含むため、単純な区切りでは誤判定する名称
_CITY_EXCEPTIONS = sorted(
    [
        "四日市市", "廿日市市", "野々市市", "市川市", "市原市", "市貝町", "市川三郷町",
        "上市町", "下市町", "町田市", "大町市", "十日町市", "村上市", "村山市", "東村山市",
        "武蔵村山市", "羽村市", "田村市", "大村市", "郡山市", "大和郡山市", "郡上市",
        "中村市", "北村山郡", "西村山郡", "東村山郡", "玉村町", "大和村", "宇治田原町",
    ],
    key=len,
    reverse=True,
)

_DESIGNATED_CITIES = {
    "札幌市": "北海道", "仙台市": "宮城県", "さいたま市": "埼玉県", "千葉市": "千葉県", "横浜市": "神奈川県",
    "川崎市": "神奈川県", "相模原市": "神奈川県", "新潟市": "新潟県", "静岡市": "静岡県", "浜松市": "静岡県",
    "名古屋市": "愛知県", "京都市": "京都府", "大阪市": "大阪府", "堺市": "大阪府", "神戸市": "兵庫県",
    "岡山市": "岡山県", "広島市": "広島県", "北九州市": "福岡県", "福岡市": "福岡県", "熊本市": "熊本県",
}

_ADDRESS_PREFIX = re.compile(r"^(日本[、,]?\s*)?(〒?\s*\d{3}-?\d{4}\s*)?")


def normalize_text(value: str | None) -> str:
    """全角英数字などを半角に揃え、前後の空白を除く."""
    if not value:
        return ""
    return unicodedata.normalize("NFKC", value).strip()


def extract_prefecture(address: str | None) -> str:
    """住所文字列から都道府県名を返す。見つからなければ空文字."""
    text = normalize_text(address)
    if not text:
        return ""
    best_pos, best = len(text) + 1, ""
    for pref in PREFECTURES:
        pos = text.find(pref)
        if pos != -1 and pos < best_pos:
            best_pos, best = pos, pref
    if best:
        return best
    # 都道府県が省略されている住所（「大阪市北区…」「横浜市中区…」など）
    for city, pref in _DESIGNATED_CITIES.items():
        if text.startswith(city):
            return pref
    for pref in PREFECTURES:
        short = pref if pref == "北海道" else pref[:-1]
        if text.startswith(short + "市"):  # 県庁所在地と同名の市（福島市、山口市など）
            return pref
    return ""


def extract_city(address: str | None, prefecture: str | None = None) -> str:
    """住所文字列から市区町村名（郡を含む）を返す。判定できなければ空文字."""
    text = normalize_text(address)
    if not text:
        return ""
    text = _ADDRESS_PREFIX.sub("", text)
    pref = prefecture or extract_prefecture(text)
    rest = text[text.find(pref) + len(pref):] if pref and pref in text else text
    rest = rest.lstrip(" 　")
    if not rest:
        return ""

    for name in _CITY_EXCEPTIONS:
        if rest.startswith(name):
            if name.endswith("郡"):
                m = re.match(re.escape(name) + r"(.{1,6}?[町村])", rest)
                return name + m.group(1) if m else name
            return name

    # 先頭から最初に現れる区切り文字（2文字目以降）で判定する
    for i, ch in enumerate(rest[:10]):
        if i == 0:
            continue
        if ch == "郡":
            m = re.match(r"(.{1,6}?[町村])", rest[i + 1:])
            return rest[: i + 1] + (m.group(1) if m else "")
        if ch in "市区町村":
            return rest[: i + 1]
    return ""


def prefecture_region(prefecture: str) -> str:
    """都道府県が属する地方名を返す."""
    for region, prefs in REGIONS.items():
        if prefecture in prefs:
            return region
    return ""
