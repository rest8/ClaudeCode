"""アプリ全体の設定ロード（共通設定 + 認証情報のみ）。

配信先と監視店舗は subscribers.yaml で管理し、店舗一覧は
restaurants.json でキャッシュする。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class EmailCredentials:
    smtp_host: str = ""
    smtp_port: int = 587
    use_tls: bool = True
    username: str = ""
    password: str = ""
    from_addr: str = ""


@dataclass
class LineCredentials:
    channel_access_token: str = ""


@dataclass
class NotificationCredentials:
    email: EmailCredentials = field(default_factory=EmailCredentials)
    line: LineCredentials = field(default_factory=LineCredentials)


@dataclass
class AppConfig:
    poll_interval_seconds: int = 90
    cookies: dict[str, str] = field(default_factory=dict)
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    notifications: NotificationCredentials = field(default_factory=NotificationCredentials)

    state_file: str = "state.json"
    restaurants_file: str = "restaurants.json"
    subscribers_file: str = "subscribers.yaml"
    log_file: str = "omakase_notifier.log"
    log_level: str = "INFO"
    tray_enabled: bool = True

    discover_index_urls: list[str] = field(
        default_factory=lambda: ["https://omakase.in/ja/restaurants"]
    )


def _build_credentials(raw: dict[str, Any]) -> NotificationCredentials:
    raw = raw or {}
    email_raw = raw.get("email") or {}
    line_raw = raw.get("line") or {}
    return NotificationCredentials(
        email=EmailCredentials(
            **{k: v for k, v in email_raw.items() if k in EmailCredentials.__dataclass_fields__}
        ),
        line=LineCredentials(
            **{k: v for k, v in line_raw.items() if k in LineCredentials.__dataclass_fields__}
        ),
    )


def load_config(path: str | Path) -> AppConfig:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    return AppConfig(
        poll_interval_seconds=int(raw.get("poll_interval_seconds", 90)),
        cookies=dict(raw.get("cookies") or {}),
        user_agent=raw.get("user_agent") or AppConfig.__dataclass_fields__["user_agent"].default,
        notifications=_build_credentials(raw.get("notifications") or {}),
        state_file=raw.get("state_file", "state.json"),
        restaurants_file=raw.get("restaurants_file", "restaurants.json"),
        subscribers_file=raw.get("subscribers_file", "subscribers.yaml"),
        log_file=raw.get("log_file", "omakase_notifier.log"),
        log_level=raw.get("log_level", "INFO"),
        tray_enabled=bool(raw.get("tray_enabled", True)),
        discover_index_urls=list(
            raw.get("discover_index_urls") or ["https://omakase.in/ja/restaurants"]
        ),
    )
