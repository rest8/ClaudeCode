"""自動送信とタスク スケジューラ登録のテスト."""

import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sales_mailer import scheduler
from sales_mailer.autosend import make_plan, run_auto_send
from sales_mailer.db import KIND_FOLLOW, KIND_NEW, RESULT_SENT, STATUS_CONTRACTED, STATUS_REPLIED, STATUS_SENT
from sales_mailer.mailer import DryRunSender

ROOT = Path(__file__).resolve().parents[1]


def seed(db):
    old = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    ids = {}
    for name in ("新規A", "新規B", "新規C", "送付済みD", "送付済みE", "返信F", "契約G"):
        ids[name] = db.add_company({"name": name, "email": f"info@{len(ids)}x.co.jp"})
    for name in ("送付済みD", "送付済みE", "返信F", "契約G"):
        c = db.get_company(ids[name])
        db.record_send(ids[name], c["email"], KIND_NEW, "ご案内", "本文", RESULT_SENT, message_id=f"<{name}@x>")
        db.update_company(ids[name], {"last_sent_at": old})
    db.record_send(ids["送付済みE"], "info@4x.co.jp", KIND_FOLLOW, "Re: ご案内", "本文", RESULT_SENT, step=1)
    db.update_company(ids["送付済みE"], {"last_sent_at": old})
    db.set_status([ids["返信F"]], STATUS_REPLIED)
    db.set_status([ids["契約G"]], STATUS_CONTRACTED)
    return ids


def test_plan_groups_follow_by_step_and_excludes_replied(db, settings):
    seed(db)
    plan = make_plan(db, settings)
    assert [c["name"] for c in plan.new_targets] == ["新規A", "新規B", "新規C"]
    steps = [(t["name"], [c["name"] for c in cs]) for t, cs in plan.follow_groups]
    assert steps == [("フォロー1回目", ["送付済みD"]), ("フォロー2回目（最終）", ["送付済みE"])]
    assert "フォロー 2 社・新規 3 社" in plan.summary()


def test_run_sends_follow_first_within_daily_limit(db, settings):
    ids = seed(db)
    settings.daily_limit = 5 + 3  # 準備で今日5通送った扱いなので残り3通
    settings.auto_check_inbox = False
    sent = []

    class Recorder(DryRunSender):
        def send(self, msg):
            sent.append((msg["To"], msg["Subject"]))

    result = run_auto_send(db, settings, lambda m: None, threading.Event(), sender_factory=Recorder)
    assert (result.sent_follow, result.sent_new) == (2, 1)
    assert sent[0][1].startswith("Re: ")  # フォローは前回メールへの返信として送る
    assert db.get_company(ids["送付済みD"])["follow_count"] == 1
    assert db.get_company(ids["新規A"])["status"] == STATUS_SENT
    assert db.get_company(ids["新規B"])["status"] != STATUS_SENT  # 上限で止まる
    again = run_auto_send(db, settings, lambda m: None, threading.Event(), sender_factory=Recorder)
    assert "上限" in again.aborted_reason


def test_dry_run_does_not_change_status(db, settings):
    ids = seed(db)
    settings.auto_check_inbox = False
    result = run_auto_send(db, settings, lambda m: None, dry_run=True)
    assert result.dry_run and result.sent_new == 3
    assert db.get_company(ids["新規A"])["status"] != STATUS_SENT


def test_follow_can_be_turned_off(db, settings):
    seed(db)
    settings.auto_follow = False
    assert make_plan(db, settings).follow_groups == []


def test_scheduler_command(monkeypatch, tmp_path):
    exe = tmp_path / "Program Files" / "SalesMailer.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    cmd = scheduler.create_command("9:05", True)
    assert cmd[:5] == ["schtasks", "/Create", "/F", "/TN", scheduler.TASK_NAME]
    assert cmd[cmd.index("/TR") + 1] == f'"{exe}" --auto-send'
    assert cmd[cmd.index("/ST") + 1] == "09:05"
    assert cmd[-4:] == ["/SC", "WEEKLY", "/D", "MON,TUE,WED,THU,FRI"]
    assert scheduler.create_command("17:00", False)[-2:] == ["/SC", "DAILY"]
    for bad in ("25:00", "9時", ""):
        with pytest.raises(scheduler.SchedulerError):
            scheduler.validate_time(bad)


def test_register_reports_schtasks_error(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    class Result:
        returncode = 1
        stdout = b""
        stderr = b"ERROR: Access is denied."

    monkeypatch.setattr(scheduler.subprocess, "run", lambda *a, **k: Result())
    monkeypatch.setattr(scheduler, "_run", lambda cmd: (_ for _ in ()).throw(scheduler.SchedulerError("Access is denied.")))
    with pytest.raises(scheduler.SchedulerError, match="denied"):
        scheduler.register("09:30")


def test_cli_auto_send_in_test_environment(tmp_path):
    """テスト環境で --auto-send を実行すると、送信せずに記録してログを残す."""
    env = {"SALES_MAILER_HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run([sys.executable, str(ROOT / "run_app.py"), "--demo", "--auto-send"], env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "自動送信が終わりました" in proc.stdout and "テスト記録" in proc.stdout
    log = (tmp_path / "test-env" / "auto-send.log").read_text(encoding="utf-8")
    assert "送信予定" in log


def test_cli_auto_send_requires_smtp(tmp_path):
    env = {"SALES_MAILER_HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run([sys.executable, str(ROOT / "run_app.py"), "--auto-send"], env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 1 and "SMTP" in proc.stdout
