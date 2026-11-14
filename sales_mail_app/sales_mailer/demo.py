"""テスト環境（サンプルデータ）.

本番のデータとは別のフォルダに、架空の企業と送信履歴を用意する。
テスト環境ではメールを実際には送信せず、企業調査も API を使わずにサンプル結果を返すため、費用はかからない。
メールアドレスはすべて example.com（例示用に予約され、実在しないドメイン）を使う。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .config import Settings
from .db import (
    KIND_FOLLOW, KIND_NEW, RESULT_SENT, STATUS_CONTRACTED, STATUS_NEW, STATUS_OPTED_OUT, STATUS_REPLIED,
    STATUS_SENT, Database,
)

__all__ = ["DEMO_BANNER", "ensure_seeded", "reset", "sample_prospects", "simulate_inbox", "demo_settings"]
from .regions import PREFECTURES
from .research import Prospect

DEMO_BANNER = "【テスト環境】サンプルデータ・メールは実際には送信されません"

# (会社名, メールのドメイン名, 住所, 業種, 状態, 何日前に初回送信したか, フォロー回数)
DEMO_COMPANIES = [
    ("株式会社あおば精工", "aoba-seiko", "宮城県仙台市青葉区一番町1-1-1", "製造業", STATUS_NEW, None, 0),
    ("杜の都建設株式会社", "morinomiyako", "宮城県仙台市宮城野区榴岡2-2-2", "建設業", STATUS_NEW, None, 0),
    ("株式会社さくらシステム", "sakura-system", "東京都千代田区丸の内3-3-3", "IT・ソフトウェア", STATUS_NEW, None, 0),
    ("みなと物流株式会社", "minato-butsuryu", "神奈川県横浜市中区本町4-4-4", "物流", STATUS_NEW, None, 0),
    ("有限会社ひかり印刷", "hikari-insatsu", "大阪府大阪市北区梅田5-5-5", "印刷業", STATUS_NEW, None, 0),
    ("株式会社なごやテック", "nagoya-tech", "愛知県名古屋市中区栄6-6-6", "製造業", STATUS_NEW, None, 0),
    ("ふくおか食品株式会社", "fukuoka-shokuhin", "福岡県福岡市博多区博多駅前7-7-7", "食品製造", STATUS_NEW, None, 0),
    ("株式会社ほっかい不動産", "hokkai-fudosan", "北海道札幌市中央区北1条西8-8", "不動産", STATUS_NEW, None, 0),
    ("株式会社とうほく機械", "tohoku-kikai", "宮城県名取市増田9-9-9", "製造業", STATUS_SENT, 10, 0),
    ("多摩精密工業株式会社", "tama-seimitsu", "東京都八王子市明神町1-2-3", "製造業", STATUS_SENT, 12, 1),
    ("株式会社しずおか茶園", "shizuoka-chaen", "静岡県静岡市葵区追手町2-3-4", "小売", STATUS_SENT, 9, 0),
    ("株式会社きょうと工芸", "kyoto-kogei", "京都府京都市中京区烏丸通3-4-5", "製造業", STATUS_SENT, 3, 0),
    ("北斗電機株式会社", "hokuto-denki", "北海道札幌市北区北7条西4-5-6", "製造業", STATUS_REPLIED, 15, 0),
    ("株式会社ひろしま商事", "hiroshima-shoji", "広島県広島市中区紙屋町5-6-7", "卸売", STATUS_CONTRACTED, 30, 1),
    ("有限会社くまもと運送", "kumamoto-unso", "熊本県熊本市中央区手取本町6-7-8", "物流", STATUS_OPTED_OUT, 20, 0),
]

_NAME_PARTS = [("さくら", "sakura"), ("あおい", "aoi"), ("ひかり", "hikari"), ("みどり", "midori"),
               ("やまと", "yamato"), ("ふじ", "fuji"), ("あさひ", "asahi"), ("つばさ", "tsubasa"),
               ("なごみ", "nagomi"), ("ことぶき", "kotobuki"), ("いずみ", "izumi"), ("はるか", "haruka")]
_FORMS = ["株式会社{p}{kw}", "{p}{kw}株式会社", "有限会社{p}{kw}"]


def demo_email(slug: str) -> str:
    return f"info@{slug}.example.com"


def demo_settings() -> Settings:
    """テスト環境の初期設定（送信者情報は架空。SMTP は未設定のまま）."""
    return Settings(
        from_name="山田 太郎（テスト）", from_email="sales@example.com", sender_company="株式会社サンプル営業",
        sender_address="東京都千代田区丸の内1-1-1",
        sender_phone="03-0000-0000", sender_url="https://www.example.com", send_interval_sec=1,
        shortcut_prompted=True,
    )


def clear(db: Database) -> None:
    for company in db.list_companies(status_filter="all"):
        db.delete_companies([company["id"]])
    with db._conn() as conn:  # noqa: SLF001 - テスト環境の履歴だけを消す
        conn.execute("DELETE FROM send_log")


def seed(db: Database, now: datetime | None = None) -> None:
    """サンプルの企業と送信履歴を入れる."""
    now = now or datetime.now()
    for name, slug, address, industry, status, days_ago, follow in DEMO_COMPANIES:
        cid = db.add_company({"name": name, "email": demo_email(slug), "address": address, "industry": industry,
                              "website": f"https://www.{slug}.example.com", "source": "demo",
                              "notes": "テスト環境のサンプル（架空の企業）"})
        if days_ago is None:
            continue
        email = demo_email(slug)
        db.record_send(cid, email, KIND_NEW, "【ご提案】業務効率化のご案内（株式会社サンプル営業）", "（サンプル本文）",
                       RESULT_SENT, message_id=f"<demo-{cid}@example.com>", company_name=name)
        for step in range(1, follow + 1):
            db.record_send(cid, email, KIND_FOLLOW, "Re: 【ご提案】業務効率化のご案内（株式会社サンプル営業）",
                           "（サンプル本文）", RESULT_SENT, message_id=f"<demo-{cid}-{step}@example.com>",
                           step=step, company_name=name)
        sent_at = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
        with db._conn() as conn:  # noqa: SLF001 - 送信日を過去の日付にする
            conn.execute("UPDATE send_log SET sent_at = ? WHERE company_id = ?", (sent_at, cid))
            conn.execute("UPDATE companies SET first_sent_at = ?, last_sent_at = ? WHERE id = ?",
                         (sent_at, sent_at, cid))
        if status != STATUS_SENT:
            db.set_status([cid], status)


def ensure_seeded(db: Database) -> bool:
    """初めてテスト環境を開いたときだけサンプルを入れる。入れたら True."""
    with db._conn() as conn:  # noqa: SLF001
        done = conn.execute("SELECT value FROM meta WHERE key = 'demo_seeded'").fetchone()
        if done:
            return False
        conn.execute("INSERT INTO meta(key, value) VALUES ('demo_seeded', '1')")
    seed(db)
    return True


def reset(db: Database) -> None:
    clear(db)
    seed(db)


def sample_prospects(db: Database, keywords: list[str], prefectures: list[str], cities: list[str],
                     count: int = 6) -> list[Prospect]:
    """企業調査のサンプル結果（API を使わない）。登録済みの企業も1社まぜて、対象外になる様子を確認できるようにする."""
    areas = [(c, c) for c in cities] or [(p, p) for p in prefectures] or [("東京都", "東京都")]
    results: list[Prospect] = []
    n = 0
    for keyword in keywords or ["企業"]:
        kw = keyword.replace("会社", "").replace("業", "") or keyword
        for label, pref in areas:
            for i in range(max(1, min(count, 12))):
                part, slug = _NAME_PARTS[(n + i) % len(_NAME_PARTS)]
                name = _FORMS[(n + i) % len(_FORMS)].format(p=part, kw=kw)
                has_mail = (n + i) % 5 != 4  # 5社に1社はメール未取得の例
                results.append(Prospect(
                    name=f"{name}（サンプル）", prefecture=pref if pref in PREFECTURES else "",
                    city=label if label != pref else "", industry=keyword,
                    email=demo_email(f"{slug}-{n + i}") if has_mail else "",
                    website=f"https://www.{slug}-{n + i}.example.com", phone=f"000-0000-{n + i:04d}",
                    description="テスト環境のサンプル結果（架空の企業）", source="demo",
                ))
            n += count
    existing = db.list_companies(status_filter="all", prefectures=prefectures or None, limit=1) or \
        db.list_companies(status_filter="all", limit=1)
    if existing:
        c = existing[0]
        results.insert(1, Prospect(name=c["name"], email=c["email"], website=c["website"], prefecture=c["prefecture"],
                                   city=c["city"], industry=c["industry"], source="demo"))
    return results


def simulate_inbox(db: Database):
    """受信トレイ確認の代わりに、送付済みの企業を1社「返信あり」にする."""
    from .replies import ReplyCheckResult

    result = ReplyCheckResult(scanned=0)
    targets = db.list_companies(status_filter=STATUS_SENT)
    if targets:
        company = sorted(targets, key=lambda c: c["last_sent_at"] or "")[0]
        db.set_status([company["id"]], STATUS_REPLIED)
        result.replied.append(company["name"])
        result.scanned = 1
    return result
