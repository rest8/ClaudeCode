from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    poll_interval_seconds: float = 300.0
    list_refresh_time: str = "04:00"
    database_url: str = "sqlite:///./data/omakase.db"
    # Run Chromium with a visible window. omakase.in performs deep
    # bot fingerprinting (TLS / Canvas / WebGL subtleties) and serves a
    # degraded view to headless browsers — paginated URLs all return
    # page 1's 32 cards. Real-window mode is the only reliable option.
    # If you need headless on a server with no display, use a virtual
    # framebuffer (Xvfb) and accept that some pages may be missed.
    headless: bool = False
    # Default to a realistic Chrome UA. omakase.in serves a stripped-down
    # view (no pagination, no sitemap) to obvious bot User-Agents.
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
    web_host: str = "127.0.0.1"
    web_port: int = 8765


class EmailConfig(BaseModel):
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_address: str = ""
    use_starttls: bool = True

    @property
    def configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.from_address)


class LineConfig(BaseModel):
    channel_access_token: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.channel_access_token)


class Config(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    line: LineConfig = Field(default_factory=LineConfig)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        path = path or default_config_path()
        if not path.exists():
            return cls()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)

    def save(self, path: Optional[Path] = None) -> None:
        path = path or default_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                self.model_dump(),
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_config_path() -> Path:
    return project_root() / "config.yaml"
