"""毎日の自動送信を OS の機能に登録する（Windows: タスク スケジューラ）.

アプリが常駐する必要はなく、指定した時刻に「SalesMailer.exe --auto-send」が起動して送信し、終わると閉じる。
費用はかからない（パソコンの電源が入っていて、ログインしている必要がある）。
"""

from __future__ import annotations

import re
import subprocess
import sys

from .shortcut import launch_command

TASK_NAME = "SalesMailer AutoSend"
WEEKDAYS = "MON,TUE,WED,THU,FRI"


class SchedulerError(Exception):
    pass


def validate_time(value: str) -> str:
    m = re.fullmatch(r"\s*(\d{1,2})[:：](\d{2})\s*", value or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise SchedulerError("時刻は「9:30」や「17:00」のように入力してください")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def task_command() -> str:
    """タスクが実行するコマンド（実行ファイルのパスに空白があっても動くよう引用符で囲む）."""
    target, args, _workdir = launch_command()
    return " ".join(f'"{part}"' for part in [target, *args]) + " --auto-send"


def create_command(time_str: str, weekdays_only: bool) -> list[str]:
    command = ["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/TR", task_command(), "/ST", validate_time(time_str)]
    command += ["/SC", "WEEKLY", "/D", WEEKDAYS] if weekdays_only else ["/SC", "DAILY"]
    return command


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, timeout=60,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError as e:
        raise SchedulerError("タスク スケジューラ（schtasks）が見つかりません") from e
    encoding = "oem" if sys.platform == "win32" else "utf-8"
    out = (result.stdout + result.stderr).decode(encoding, "replace").strip()
    if result.returncode != 0:
        raise SchedulerError(out or f"タスク スケジューラの操作に失敗しました（終了コード {result.returncode}）")
    return out


def register(time_str: str, weekdays_only: bool = True) -> str:
    if sys.platform != "win32":
        raise SchedulerError(
            "毎日の自動送信の登録は Windows 版のみ対応しています。macOS / Linux では cron などに次のコマンドを登録してください:\n"
            + task_command())
    _run(create_command(time_str, weekdays_only))
    when = "平日" if weekdays_only else "毎日"
    return f"{when} {validate_time(time_str)} に自動送信するよう、タスク スケジューラに登録しました。"


def unregister() -> str:
    if sys.platform != "win32":
        raise SchedulerError("Windows 版のみ対応しています")
    _run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME])
    return "毎日の自動送信の登録を解除しました。"


def is_registered() -> bool:
    if sys.platform != "win32":
        return False
    try:
        _run(["schtasks", "/Query", "/TN", TASK_NAME])
        return True
    except SchedulerError:
        return False
