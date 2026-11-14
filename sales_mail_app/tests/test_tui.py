"""ターミナル版（Textual）の操作テスト。画面は表示せずヘッドレスで動かす."""

from datetime import datetime, timedelta

import pytest

pytest.importorskip("textual")

from textual.widgets import Button, Checkbox, Input, TabbedContent, TextArea  # noqa: E402

from sales_mailer.config import Settings, load_settings, save_settings  # noqa: E402
from sales_mailer.db import (  # noqa: E402
    KIND_NEW, RESULT_DRY_RUN, RESULT_SENT, STATUS_CONTRACTED, STATUS_NEW, STATUS_REPLIED, Database,
)
from sales_mailer.research import Prospect  # noqa: E402
from sales_mailer.tui.app import SalesMailerTUI  # noqa: E402
from sales_mailer.tui.dialogs import ConfirmDialog, MessageDialog  # noqa: E402

SIZE = (120, 30)  # Windows の標準的なターミナルの大きさ


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("SALES_MAILER_HOME", str(tmp_path))
    save_settings(Settings(smtp_user="me@mycorp.co.jp", from_name="山田", sender_company="マイコープ",
                           send_interval_sec=0, shortcut_prompted=True))
    db = Database(tmp_path / "sales_mailer.db")
    ids = {}
    for name, email in [("A社", "info@a.co.jp"), ("B社", "info@b.co.jp"), ("C社", "info@c.co.jp"),
                        ("D社", "info@d.co.jp"), ("E社", "info@e.co.jp")]:
        ids[name] = db.add_company({"name": name, "email": email, "prefecture": "東京都"})
    old = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    for name in ("A社", "B社", "C社"):
        db.record_send(ids[name], f"info@{name[0].lower()}.co.jp", KIND_NEW, "ご案内", "本文", RESULT_SENT)
        db.update_company(ids[name], {"last_sent_at": old})
    db.set_status([ids["B社"]], STATUS_REPLIED)
    db.set_status([ids["C社"]], STATUS_CONTRACTED)
    return db, ids, tmp_path / "sales_mailer.db"


def make_app(db_path, tab=None):
    return SalesMailerTUI(db_path, first_run_prompts=False, initial_tab=tab)


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def test_contracted_company_disappears_from_list(seeded):
    db, ids, path = seeded
    app = make_app(path)
    async with app.run_test(size=SIZE) as pilot:
        pane = app.query_one("#pane-companies")
        names = [r["name"] for r in pane.table.data.values()]
        assert "C社" not in names and "A社" in names  # 契約済みは既定の表示に出ない
        pane.table.focus()
        key = str(ids["D社"])
        pane.table.move_cursor(row=pane.table.get_row_index(key))
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)
        await pilot.press("enter")
        await settle(app, pilot)
        assert db.get_company(ids["D社"])["status"] == STATUS_CONTRACTED
        assert key not in pane.table.data


async def test_research_adds_only_new_companies(seeded):
    db, _ids, path = seeded
    app = make_app(path, "research")
    async with app.run_test(size=SIZE) as pilot:
        pane = app.query_one("#pane-research")
        pane.prospects = [
            Prospect(name="A社", email="info@a.co.jp", prefecture="東京都"),         # 送付済み → 対象外
            Prospect(name="新規社", email="info@shinki.co.jp", prefecture="東京都"),
            Prospect(name="メールなし社", prefecture="東京都"),
        ]
        from sales_mailer.services import mark_existing

        for p in pane.prospects:
            mark_existing(db, p)
        pane.render_results()
        await pilot.click(pane.query_one("#mark-new"))
        assert pane.table.marked == {"1"}
        await pilot.click(pane.query_one("#add"))
        await pilot.pause()
        assert db.find_duplicate("新規社", "info@shinki.co.jp")["status"] == STATUS_NEW
        assert db.find_duplicate("メールなし社") is None


async def test_new_mail_dry_run_excludes_sent_and_contracted(seeded):
    db, ids, path = seeded
    app = make_app(path, "newmail")
    async with app.run_test(size=SIZE) as pilot:
        pane = app.query_one("#pane-newmail")
        await pilot.click(pane.query_one("#extract"))
        names = sorted(r["name"] for r in pane.table.data.values())
        assert names == ["D社", "E社"]
        assert "件名:" in pane.query_one("#preview", TextArea).text
        pane.query_one("#dry", Checkbox).value = True
        await pilot.click(pane.query_one("#send"))
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, MessageDialog)
        log = db.list_send_log()
        assert [r["result"] for r in log[:2]] == [RESULT_DRY_RUN, RESULT_DRY_RUN]
        assert db.get_company(ids["D社"])["status"] == STATUS_NEW  # テストモードではステータスを変えない


async def test_follow_targets_skip_replied_and_contracted(seeded):
    _db, _ids, path = seeded
    app = make_app(path, "follow")
    async with app.run_test(size=SIZE) as pilot:
        pane = app.query_one("#pane-follow")
        await pilot.click(pane.query_one("#extract"))
        assert [r["name"] for r in pane.table.data.values()] == ["A社"]
        assert "Re: ご案内" in pane.query_one("#preview", TextArea).text


async def test_function_keys_switch_tabs_from_any_widget(seeded):
    _db, _ids, path = seeded
    app = make_app(path, "follow")
    async with app.run_test(size=SIZE) as pilot:
        app.query_one("#pane-follow").query_one("#preview", TextArea).focus()
        await pilot.pause()
        for key, tab in [("f1", "companies"), ("f2", "research"), ("f5", "templates"), ("f7", "settings"),
                         ("f3", "newmail")]:
            await pilot.press(key)
            await pilot.pause()
            assert app.query_one(TabbedContent).active == tab


async def test_settings_are_saved(seeded):
    _db, _ids, path = seeded
    app = make_app(path, "settings")
    async with app.run_test(size=SIZE) as pilot:
        pane = app.query_one("#pane-settings")
        pane.query_one("#s-daily_limit", Input).value = "55"
        pane.query_one("#s-sender_phone", Input).value = "03-9999-0000"
        await pilot.click(pane.query_one("#save"))  # 保存ボタンは画面上部に常に表示
        await pilot.pause()
    saved = load_settings()
    assert saved.daily_limit == 55 and saved.sender_phone == "03-9999-0000"
    assert saved.smtp_user == "me@mycorp.co.jp"  # 画面に無い値もそのまま残る


async def test_template_edit_and_save(seeded):
    db, _ids, path = seeded
    app = make_app(path, "templates")
    async with app.run_test(size=SIZE) as pilot:
        pane = app.query_one("#pane-templates")
        await pilot.click(pane.query_one("#new"))
        pane.query_one("#name", Input).value = "展示会フォロー"
        pane.query_one("#subject", Input).value = "先日はありがとうございました"
        await pilot.click(pane.query_one("#save"))
        await pilot.pause()
    assert any(t["name"] == "展示会フォロー" for t in db.list_templates())


async def test_send_button_disabled_state_restored_after_dry_run(seeded):
    _db, _ids, path = seeded
    app = make_app(path, "newmail")
    async with app.run_test(size=SIZE) as pilot:
        pane = app.query_one("#pane-newmail")
        await pilot.click(pane.query_one("#extract"))
        pane.query_one("#dry", Checkbox).value = True
        await pilot.click(pane.query_one("#send"))
        await pilot.pause()
        await pilot.press("enter")
        await settle(app, pilot)
        assert not pane.query_one("#send", Button).disabled
        assert pane.query_one("#stop", Button).disabled
        assert not pane.busy


async def test_demo_mode_end_to_end(tmp_path, monkeypatch):
    """テスト環境: サンプルデータ入り・常にテストモード・調査はサンプル結果・費用なし."""
    from sales_mailer import config

    monkeypatch.setenv("SALES_MAILER_HOME", str(tmp_path))
    monkeypatch.setenv(config.DEMO_ENV, "1")
    app = SalesMailerTUI(first_run_prompts=False, initial_tab="newmail")
    async with app.run_test(size=SIZE) as pilot:
        assert "テスト環境" in str(app.query_one("#stats").render())
        pane = app.query_one("#pane-newmail")
        dry = pane.query_one("#dry", Checkbox)
        assert dry.value and dry.disabled  # 送信しない設定を外せない
        await pilot.click(pane.query_one("#extract"))
        assert len(pane.table.data) == 8
        await pilot.click(pane.query_one("#send"))
        await pilot.pause()
        await pilot.press("enter")
        await settle(app, pilot)
        assert {r["result"] for r in app.db.list_send_log()[:8]} == {RESULT_DRY_RUN}
        assert isinstance(app.screen, MessageDialog)  # 送信結果
        await pilot.press("enter")

        await pilot.press("f2")
        await pilot.pause()
        research = app.query_one("#pane-research")
        research.query_one("#keywords", Input).value = "製造業"
        research.query_one("#prefs").set_prefectures(["宮城県"])
        await pilot.click(research.query_one("#start"))
        await settle(app, pilot)
        assert research.prospects and any(p.existing_status for p in research.prospects)

        await pilot.press("f4")
        await pilot.pause()
        follow = app.query_one("#pane-follow")
        await pilot.click(follow.query_one("#extract"))
        before = len(follow.table.data)
        await pilot.click(follow.query_one("#inbox"))
        await pilot.pause()
        assert isinstance(app.screen, MessageDialog)
        await pilot.press("enter")
        await pilot.pause()
        assert len(follow.table.data) == before - 1  # 返信ありになった企業はフォロー対象から外れる
    # 本番のデータフォルダには何も作られていない
    assert not (tmp_path / "sales_mailer.db").exists()
    assert (tmp_path / "test-env" / "sales_mailer.db").exists()
