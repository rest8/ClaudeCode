"""テスト環境（--demo）のテスト."""

import threading

import pytest

from sales_mailer import config, demo
from sales_mailer.campaign import SendOptions, run_send_job, send_test_mail
from sales_mailer.db import (
    KIND_NEW, RESULT_DRY_RUN, STATUS_CONTRACTED, STATUS_NEW, STATUS_OPTED_OUT, STATUS_REPLIED, STATUS_SENT, Database,
)
from sales_mailer.services import run_research, stats_text


@pytest.fixture
def demo_db(tmp_path, monkeypatch):
    monkeypatch.setenv("SALES_MAILER_HOME", str(tmp_path))
    monkeypatch.setenv(config.DEMO_ENV, "1")
    db = Database(config.data_dir() / "sales_mailer.db")
    assert demo.ensure_seeded(db)
    return db


def test_demo_uses_separate_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SALES_MAILER_HOME", str(tmp_path))
    monkeypatch.delenv(config.DEMO_ENV, raising=False)
    real = config.data_dir()
    monkeypatch.setenv(config.DEMO_ENV, "1")
    assert config.data_dir() == real / "test-env"  # 本番のデータと混ざらない


def test_seed_covers_every_status(demo_db):
    stats = demo_db.stats()
    assert stats[STATUS_NEW] == 8 and stats[STATUS_SENT] == 4
    assert stats[STATUS_REPLIED] == stats[STATUS_CONTRACTED] == stats[STATUS_OPTED_OUT] == 1
    assert not demo.ensure_seeded(demo_db)  # 2回目は入れ直さない
    assert all(c["email"].endswith(".example.com") for c in demo_db.list_companies(status_filter="all"))


def test_seed_supports_new_and_follow_flows(demo_db):
    assert len(demo_db.new_targets()) == 8
    follow = {c["name"] for c in demo_db.follow_targets(min_days=7, max_follow=2)}
    assert follow == {"株式会社とうほく機械", "多摩精密工業株式会社", "株式会社しずおか茶園"}  # 3日前の1社は対象外


class ExplodingSender:
    def connect(self):
        raise AssertionError("テスト環境で SMTP に接続してはいけない")

    def send(self, msg):
        raise AssertionError("テスト環境で送信してはいけない")

    def close(self):
        pass


def test_demo_never_sends_even_if_dry_run_is_off(demo_db, settings):
    targets = demo_db.new_targets()[:2]
    opts = SendOptions(kind=KIND_NEW, template={"subject": "件名", "body": "本文"}, dry_run=False, interval_sec=0)
    report = run_send_job(demo_db, settings, targets, opts, threading.Event(), lambda *a: None,
                          sender=ExplodingSender())
    assert report.sent == 2
    assert {r["result"] for r in demo_db.list_send_log()[:2]} == {RESULT_DRY_RUN}
    assert demo_db.get_company(targets[0]["id"])["status"] == STATUS_NEW


def test_demo_blocks_test_mail(demo_db, settings):
    with pytest.raises(ValueError, match="テスト環境"):
        send_test_mail(settings, {"subject": "s", "body": "b"}, {"name": "A社"})


def test_demo_research_uses_samples_and_marks_existing(demo_db, settings):
    messages = []
    prospects = run_research(demo_db, settings, "google", ["製造業"], ["宮城県"], [], 6, True, True,
                             messages.append, threading.Event())
    assert any("費用はかかりません" in m for m in messages)
    assert sum(1 for p in prospects if p.existing_status) == 1  # 登録済みの企業は対象外になる例
    new = [p for p in prospects if not p.existing_status]
    assert len(new) == 6 and all(p.prefecture == "宮城県" for p in new)
    assert any(not p.email for p in new)  # メール未取得の例も含む


def test_simulate_inbox_and_reset(demo_db):
    result = demo.simulate_inbox(demo_db)
    assert len(result.replied) == 1
    assert demo_db.stats()[STATUS_REPLIED] == 2
    demo.reset(demo_db)
    assert demo_db.stats()[STATUS_REPLIED] == 1 and len(demo_db.list_send_log()) == 9  # 初回7通＋フォロー2通


def test_stats_banner(demo_db, settings):
    assert stats_text(demo_db, settings).startswith("【テスト環境")
