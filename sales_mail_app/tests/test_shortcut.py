import sys
from pathlib import Path

import pytest

from sales_mailer import shortcut


def test_launch_command_from_source():
    target, args, workdir = shortcut.launch_command()
    assert Path(target).name.startswith("python")
    assert args == [str(workdir / "run_app.py")]
    assert (workdir / "run_app.py").exists()


def test_launch_command_frozen(monkeypatch, tmp_path):
    exe = tmp_path / "SalesMailer.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert shortcut.launch_command() == (str(exe), [], tmp_path)


def test_icon_assets_exist():
    assert (shortcut.assets_dir() / "icon.png").exists()
    assert (shortcut.assets_dir() / "icon.ico").exists()


def test_windows_script_quotes_values():
    script = shortcut.windows_script(r"C:\Users\O'Brien\SalesMailer.exe", [], Path(r"C:\Users\O'Brien"),
                                     r"C:\Users\O'Brien\SalesMailer.exe", 0)
    assert "$target = 'C:\\Users\\O''Brien\\SalesMailer.exe'" in script
    assert "営業メール自動化.lnk" in script
    assert "GetFolderPath('Desktop')" in script  # OneDrive に移動したデスクトップにも対応
    # 日本語のファイル名を扱えるショートカット API（IShellLinkW）を使い、失敗時は予備の方法に切り替える
    assert "IShellLinkW" in script and "WScript.Shell" in script
    # here-string の開始・終了は行頭に置く必要がある
    lines = script.splitlines()
    assert lines.count("'@") == 1 and any(line.endswith("@'") for line in lines)


def test_powershell_error_is_reported(monkeypatch):
    class Result:
        returncode = 1
        stdout = "ERROR: Unable to save shortcut\r\n".encode()
        stderr = b"#< CLIXML noise"

    monkeypatch.setattr(shortcut.subprocess, "run", lambda *a, **k: Result())
    with pytest.raises(OSError, match="Unable to save shortcut"):
        shortcut._powershell("x")


def test_mac_command_file():
    text = shortcut.mac_command_file("/Applications/Sales Mailer/SalesMailer", [], Path("/Applications/Sales Mailer"))
    assert text.startswith("#!/bin/bash")
    assert "exec '/Applications/Sales Mailer/SalesMailer'" in text


def test_linux_desktop_entry_opens_terminal():
    entry = shortcut.linux_desktop_entry("/usr/bin/python3", ["/opt/my app/run_app.py"], Path("/opt/my app"),
                                         Path("/home/u/icon.png"))
    assert "Terminal=true" in entry
    assert 'Exec=/usr/bin/python3 "/opt/my app/run_app.py"' in entry
    assert "Icon=/home/u/icon.png" in entry


@pytest.mark.skipif(sys.platform == "win32", reason="Windows は PowerShell でショートカットを作る")
def test_create_desktop_shortcut_on_posix(monkeypatch, tmp_path):
    desktop = tmp_path / "Desktop"
    monkeypatch.setattr(shortcut, "desktop_dir", lambda: desktop)
    monkeypatch.setattr(shortcut.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(shortcut.shutil, "which", lambda name: None)
    monkeypatch.setattr(shortcut.subprocess, "run", lambda *a, **k: None)
    path = shortcut.create_desktop_shortcut()
    assert path.exists() and path.parent == desktop
    assert path.stat().st_mode & 0o111  # 実行可能（ダブルクリックで起動できる）
    assert shortcut.shortcut_exists()


def test_demo_shortcut_name_and_path(monkeypatch, tmp_path):
    monkeypatch.setattr(shortcut, "desktop_dir", lambda: tmp_path)
    assert shortcut.shortcut_name(demo=True) == "営業メール自動化（テスト環境）"
    script = shortcut.windows_script("C:\\a\\SalesMailer.exe", ["--demo"], Path("C:\\a"), "C:\\a\\SalesMailer.exe", 0,
                                     name=shortcut.shortcut_name(True))
    assert "営業メール自動化（テスト環境）.lnk" in script and "$arguments = '\"--demo\"'" in script


@pytest.mark.skipif(sys.platform == "win32", reason="Windows は PowerShell でショートカットを作る")
def test_create_demo_shortcut_on_posix(monkeypatch, tmp_path):
    desktop = tmp_path / "Desktop"
    monkeypatch.setattr(shortcut, "desktop_dir", lambda: desktop)
    monkeypatch.setattr(shortcut.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(shortcut.shutil, "which", lambda name: None)
    path = shortcut.create_desktop_shortcut(demo=True)
    text = path.read_text(encoding="utf-8")
    assert "--demo" in text and "（テスト環境）" in text
