"""アプリ設定の保存・読み込み."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import APP_NAME

DEFAULT_OPTOUT_TEXT = (
    "※本メールは、貴社ウェブサイト等で公開されているメールアドレス宛にお送りしております。\n"
    "今後このようなご案内が不要な場合は、お手数ですが本メールに「配信停止」とご返信ください。"
)


DEMO_ENV = "SALES_MAILER_DEMO"


def is_demo() -> bool:
    """テスト環境（サンプルデータ・実際には送信しない）で動いているか."""
    return os.environ.get(DEMO_ENV) == "1"


def data_dir() -> Path:
    """設定・データベースを保存するフォルダ（OSごとのユーザーデータ領域）.

    テスト環境では本番のデータと混ざらないよう、その中の test-env フォルダを使う。
    """
    path = base_data_dir() / "test-env" if is_demo() else base_data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def base_data_dir() -> Path:
    override = os.environ.get("SALES_MAILER_HOME")
    if override:
        path = Path(override)
    elif sys.platform == "win32":
        path = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        path = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Settings:
    # --- SMTP（送信） ---
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_security: str = "starttls"  # starttls / ssl / none
    smtp_user: str = ""
    smtp_password: str = ""

    # --- 送信者情報（署名・特定電子メール法の表示） ---
    from_name: str = ""
    from_email: str = ""
    reply_to: str = ""
    sender_company: str = ""
    sender_address: str = ""
    sender_phone: str = ""
    sender_url: str = ""
    optout_text: str = DEFAULT_OPTOUT_TEXT

    # --- IMAP（返信チェック） ---
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""

    # --- 送信ルール ---
    send_interval_sec: int = 30
    daily_limit: int = 100
    follow_after_days: int = 7
    max_follow_count: int = 2

    # --- 調査・AI ---
    google_api_key: str = ""
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"
    crawl_max_pages: int = 5
    crawl_timeout_sec: int = 10

    # --- 自動送信 ---
    auto_new_template_id: int = 0      # 0 なら最初の新規メールテンプレート
    auto_follow: bool = True           # フォローメールも送る
    auto_check_inbox: bool = True      # 送信前に受信トレイを確認（返信・配信停止を除外）
    auto_time: str = "09:30"           # 毎日の自動送信の時刻
    auto_weekdays_only: bool = True    # 平日のみ
    auto_scheduled: bool = False       # タスク スケジューラに登録済みか

    # --- その他 ---
    shortcut_prompted: bool = False  # 初回起動時に「デスクトップにアイコンを作成」を確認済みか

    @property
    def effective_from_email(self) -> str:
        return self.from_email or self.smtp_user

    @property
    def effective_imap_user(self) -> str:
        return self.imap_user or self.smtp_user

    @property
    def effective_imap_password(self) -> str:
        return self.imap_password or self.smtp_password


def settings_path() -> Path:
    return data_dir() / "settings.json"


def load_settings(path: Path | None = None) -> Settings:
    path = path or settings_path()
    if not path.exists():
        return Settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Settings()
    known = {f.name: f for f in fields(Settings)}
    values = {}
    for key, value in raw.items():
        if key not in known:
            continue
        default = getattr(Settings, key, None)
        if isinstance(default, int) and not isinstance(default, bool):
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
        values[key] = value
    return Settings(**values)


def save_settings(settings: Settings, path: Path | None = None) -> None:
    path = path or settings_path()
    path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
    if os.name == "posix":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
