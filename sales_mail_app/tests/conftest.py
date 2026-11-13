import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sales_mailer.config import Settings  # noqa: E402
from sales_mailer.db import Database  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("SALES_MAILER_HOME", str(tmp_path))
    return Database(tmp_path / "test.db")


@pytest.fixture
def settings():
    return Settings(
        smtp_user="me@mycorp.co.jp",
        from_name="山田太郎",
        sender_company="株式会社マイコープ",
        sender_address="東京都千代田区1-1-1",
        sender_phone="03-0000-0000",
        send_interval_sec=0,
    )
