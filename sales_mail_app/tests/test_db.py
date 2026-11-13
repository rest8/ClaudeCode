from datetime import datetime, timedelta

from sales_mailer.db import (
    KIND_FOLLOW, KIND_NEW, RESULT_DRY_RUN, RESULT_SENT, STATUS_CONTRACTED, STATUS_NEW, STATUS_OPTED_OUT,
    STATUS_REPLIED, STATUS_SENT, company_domain, normalize_company_name,
)


def add(db, name, email, **kw):
    return db.add_company({"name": name, "email": email, **kw})


def test_default_templates_seeded(db):
    kinds = {t["kind"] for t in db.list_templates()}
    assert kinds == {KIND_NEW, KIND_FOLLOW}


def test_address_fills_prefecture_and_city(db):
    cid = add(db, "株式会社テスト", "info@test.co.jp", address="〒150-0002 東京都渋谷区渋谷2-1-1")
    c = db.get_company(cid)
    assert c["prefecture"] == "東京都"
    assert c["city"] == "渋谷区"
    assert c["domain"] == "test.co.jp"


def test_company_domain_ignores_free_mail():
    assert company_domain("abc@gmail.com", "") == ""
    assert company_domain("abc@gmail.com", "https://www.foo.co.jp/") == "foo.co.jp"
    assert company_domain("info@bar.jp", "") == "bar.jp"


def test_normalize_company_name():
    assert normalize_company_name("株式会社 ＡＢＣ") == normalize_company_name("ABC(株)")


def test_new_targets_exclude_sent_contracted_and_optout(db):
    a = add(db, "A社", "info@a.co.jp", prefecture="東京都")
    b = add(db, "B社", "info@b.co.jp", prefecture="東京都")
    c = add(db, "C社", "info@c.co.jp", prefecture="東京都")
    d = add(db, "D社", "info@d.co.jp", prefecture="大阪府")
    add(db, "メール無し社", "", prefecture="東京都")
    db.record_send(a, "info@a.co.jp", KIND_NEW, "件名", "本文", RESULT_SENT)
    db.set_status([b], STATUS_CONTRACTED)
    db.set_status([c], STATUS_OPTED_OUT)

    assert db.get_company(a)["status"] == STATUS_SENT
    assert [t["id"] for t in db.new_targets()] == [d]
    assert db.new_targets(prefectures=["東京都"]) == []


def test_new_targets_exclude_same_domain_already_sent(db):
    a = add(db, "A社", "info@a.co.jp")
    add(db, "A社 営業部", "sales@a.co.jp")
    db.record_send(a, "info@a.co.jp", KIND_NEW, "件名", "本文", RESULT_SENT)
    assert db.new_targets() == []


def test_new_targets_exclude_domain_of_contracted_company(db):
    a = add(db, "A社", "info@a.co.jp", website="https://a.co.jp")
    db.set_status([a], STATUS_CONTRACTED)
    # 別名・別アドレスで再登録されても、契約済み企業と同じドメインなら対象外
    db.add_company({"name": "エー株式会社", "email": "contact@a.co.jp"})
    assert db.new_targets() == []


def test_new_targets_dedupes_same_domain_within_batch(db):
    add(db, "X社", "info@x.co.jp")
    db.add_company({"name": "X社 東京支店", "email": "tokyo@x.co.jp"})
    assert len(db.new_targets()) == 1


def test_new_targets_keyword_filter(db):
    add(db, "鈴木建設", "info@suzuki.co.jp", industry="建設業")
    add(db, "佐藤商店", "info@sato.co.jp", industry="小売")
    names = [t["name"] for t in db.new_targets(keywords=["建設"])]
    assert names == ["鈴木建設"]


def test_dry_run_does_not_mark_sent(db):
    a = add(db, "A社", "info@a.co.jp")
    db.record_send(a, "info@a.co.jp", KIND_NEW, "件名", "本文", RESULT_DRY_RUN)
    assert db.get_company(a)["status"] == STATUS_NEW
    assert len(db.new_targets()) == 1


def test_follow_targets(db):
    now = datetime.now()
    old = (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    recent = (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    a = add(db, "A社", "info@a.co.jp")
    b = add(db, "B社", "info@b.co.jp")
    c = add(db, "C社", "info@c.co.jp")
    d = add(db, "D社", "info@d.co.jp")
    e = add(db, "E社", "info@e.co.jp")
    for cid in (a, b, c, d, e):
        db.update_company(cid, {"status": STATUS_SENT, "last_sent_at": old})
    db.update_company(b, {"last_sent_at": recent})          # まだ日数が経っていない
    db.set_status([c], STATUS_REPLIED)                       # 返信あり
    db.set_status([d], STATUS_CONTRACTED)                    # 契約済み
    db.update_company(e, {"follow_count": 2})                # 上限到達

    ids = [t["id"] for t in db.follow_targets(min_days=7, max_follow=2)]
    assert ids == [a]


def test_follow_send_increments_count(db):
    a = add(db, "A社", "info@a.co.jp")
    db.record_send(a, "info@a.co.jp", KIND_NEW, "件名1", "本文", RESULT_SENT, message_id="<m1@x>")
    db.record_send(a, "info@a.co.jp", KIND_FOLLOW, "Re: 件名1", "本文", RESULT_SENT, message_id="<m2@x>", step=1)
    c = db.get_company(a)
    assert c["follow_count"] == 1
    assert c["status"] == STATUS_SENT
    assert c["last_subject"] == "Re: 件名1"
    assert c["last_message_id"] == "<m2@x>"


def test_is_still_eligible(db):
    a = add(db, "A社", "info@a.co.jp")
    assert db.is_still_eligible(a, KIND_NEW)
    db.set_status([a], STATUS_CONTRACTED)
    assert not db.is_still_eligible(a, KIND_NEW)
    assert not db.is_still_eligible(a, KIND_FOLLOW)


def test_import_contracted_marks_existing_and_adds_new(db):
    a = add(db, "株式会社アルファ", "info@alpha.co.jp", prefecture="東京都")
    rows = [
        {"name": "アルファ(株)", "email": "", "website": "https://www.alpha.co.jp/"},  # 既存→契約済みに更新
        {"name": "ベータ株式会社", "email": "info@beta.co.jp"},                          # 新規に契約済みとして登録
        {"name": "", "email": "x@y.jp"},                                                # 会社名なし→スキップ
    ]
    result = db.import_rows(rows, status=STATUS_CONTRACTED)
    assert (result.added, result.updated, result.skipped) == (1, 1, 1)
    assert db.get_company(a)["status"] == STATUS_CONTRACTED
    # 一覧の既定表示（有効な企業）からは契約済みが消える
    assert db.list_companies() == []
    assert len(db.list_companies(status_filter="all")) == 2


def test_import_new_skips_duplicates(db):
    add(db, "A社", "info@a.co.jp")
    result = db.import_rows([{"name": "A社", "email": "INFO@A.CO.JP"}, {"name": "B社", "email": "b@b.jp"}])
    assert (result.added, result.skipped) == (1, 1)


def test_import_status_column_overrides(db):
    result = db.import_rows([{"name": "C社", "email": "c@c.jp", "status": "契約済み"}])
    assert result.added == 1
    assert db.list_companies(status_filter=STATUS_CONTRACTED)[0]["name"] == "C社"


def test_count_sent_today_and_stats(db):
    a = add(db, "A社", "info@a.co.jp")
    db.record_send(a, "info@a.co.jp", KIND_NEW, "s", "b", RESULT_SENT)
    db.record_send(None, "me@x.jp", "test", "s", "b", RESULT_DRY_RUN)
    assert db.count_sent_today() == 1
    stats = db.stats()
    assert stats[STATUS_SENT] == 1 and stats["today"] == 1


def test_import_sent_normalizes_date_for_follow_targets(db):
    existing = add(db, "A社", "info@a.co.jp")
    result = db.import_rows([
        {"name": "A社", "email": "info@a.co.jp", "last_sent_at": "2020/01/15"},
        {"name": "B社", "email": "info@b.co.jp", "last_sent_at": "2020/02/01"},
    ], status=STATUS_SENT)
    assert (result.added, result.updated) == (1, 1)
    assert db.get_company(existing)["last_sent_at"] == "2020-01-15 00:00:00"
    assert {t["name"] for t in db.follow_targets(min_days=7, max_follow=2)} == {"A社", "B社"}
