"""設定ファイルのロードと検証。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class EmailConfig:
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    use_tls: bool = True
    username: str = ""
    password: str = ""
    from_addr: str = ""
    to_addrs: list[str] = field(default_factory=list)


@dataclass
class LineConfig:
    enabled: bool = False
    channel_access_token: str = ""
    to: str = ""


@dataclass
class WebhookConfig:
    enabled: bool = False
    url: str = ""


@dataclass
class NotificationConfig:
    email: EmailConfig = field(default_factory=EmailConfig)
    line: LineConfig = field(default_factory=LineConfig)
    webhook: WebhookConfig = field(default_factory=WebhookConfig)


@dataclass
class TargetConfig:
    name: str
    url: str
    dates: list[str] = field(default_factory=list)
    times: list[str] = field(default_factory=list)
    party_size: int | None = None


@dataclass
class AppConfig:
    targets: list[TargetConfig]
    poll_interval_seconds: int = 90
    cookies: dict[str, str] = field(default_factory=dict)
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    state_file: str = "state.json"
    log_file: str = "omakase_notifier.log"
    log_level: str = "INFO"
    tray_enabled: bool = True


def _build_target(raw: dict[str, Any]) -> TargetConfig:
    if "name" not in raw or "url" not in raw:
        raise ValueError("target には name と url が必須です")
    return TargetConfig(
        name=raw["name"],
        url=raw["url"],
        dates=list(raw.get("dates") or []),
        times=list(raw.get("times") or []),
        party_size=raw.get("party_size"),
    )


def _build_notifications(raw: dict[str, Any]) -> NotificationConfig:
    raw = raw or {}
    email_raw = raw.get("email") or {}
    line_raw = raw.get("line") or {}
    webhook_raw = raw.get("webhook") or {}
    return NotificationConfig(
        email=EmailConfig(**{k: v for k, v in email_raw.items() if k in EmailConfig.__dataclass_fields__}),
        line=LineConfig(**{k: v for k, v in line_raw.items() if k in LineConfig.__dataclass_fields__}),
        webhook=WebhookConfig(
            **{k: v for k, v in webhook_raw.items() if k in WebhookConfig.__dataclass_fields__}
        ),
    )


def load_config(path: str | Path) -> AppConfig:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    targets_raw = raw.get("targets") or []
    if not targets_raw:
        raise ValueError("targets が空です。少なくとも1件の監視対象を設定してください")

    return AppConfig(
        targets=[_build_target(t) for t in targets_raw],
        poll_interval_seconds=int(raw.get("poll_interval_seconds", 90)),
        cookies=dict(raw.get("cookies") or {}),
        user_agent=raw.get("user_agent") or AppConfig.__dataclass_fields__["user_agent"].default,
        notifications=_build_notifications(raw.get("notifications") or {}),
        state_file=raw.get("state_file", "state.json"),
        log_file=raw.get("log_file", "omakase_notifier.log"),
        log_level=raw.get("log_level", "INFO"),
        tray_enabled=bool(raw.get("tray_enabled", True)),
    )
