"""デスクトップにアイコン（クリックでターミナルが開きアプリが起動する）を作る.

- Windows: デスクトップに「営業メール自動化.lnk」（コンソールアプリなのでターミナルが開く）
- macOS  : デスクトップに「営業メール自動化.command」（ダブルクリックでターミナル.app が開く）
- Linux  : デスクトップとアプリ一覧に .desktop（Terminal=true）
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import APP_TITLE
from .config import data_dir

SHORTCUT_NAME = APP_TITLE


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """ソースから実行しているときの sales_mail_app フォルダ."""
    return Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", project_root()))
    return base / "assets"


def launch_command() -> tuple[str, list[str], Path]:
    """(実行ファイル, 引数, 作業フォルダ)."""
    if is_frozen():
        exe = Path(sys.executable)
        return str(exe), [], exe.parent
    python = Path(sys.executable)
    if os.name == "nt" and python.name.lower() == "pythonw.exe":  # コンソールが開く python.exe を使う
        python = python.with_name("python.exe")
    root = project_root()
    return str(python), [str(root / "run_app.py")], root


def desktop_dir() -> Path:
    home = Path.home()
    if sys.platform == "win32":
        try:
            out = _powershell("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                              "Write-Output ([Environment]::GetFolderPath('Desktop'))")
            if out:
                return Path(out)
        except (OSError, subprocess.SubprocessError):
            pass
        return home / "Desktop"
    if sys.platform.startswith("linux") and shutil.which("xdg-user-dir"):
        try:
            out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5).stdout.strip()
            if out and Path(out).is_dir():
                return Path(out)
        except (OSError, subprocess.SubprocessError):
            pass
    for name in ("Desktop", "デスクトップ"):
        if (home / name).is_dir():
            return home / name
    return home / "Desktop"


def _powershell(script: str) -> str:
    """PowerShell を実行して標準出力を返す。スクリプトが「ERROR: …」を出して終了したら OSError."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        capture_output=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    out = result.stdout.decode("utf-8", "replace").strip()
    if result.returncode != 0:
        errors = [line[6:].strip() for line in out.splitlines() if line.startswith("ERROR:")]
        raise OSError("\n".join(errors) or f"PowerShell の実行に失敗しました（終了コード {result.returncode}）")
    return out.splitlines()[-1].strip() if out else ""


# Windows のショートカット API（IShellLinkW）を直接使う C# コード。
# WScript.Shell は ANSI 経由で保存するため、英語版 Windows などでは日本語のファイル名が「????」になり保存に失敗する。
_SHELL_LINK_CS = r"""
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;

namespace SalesMailerShortcut {
    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellLinkW {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszFile, int cch, IntPtr pfd, uint fFlags);
        void GetIDList(out IntPtr ppidl);
        void SetIDList(IntPtr pidl);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszName, int cch);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string pszName);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszDir, int cch);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string pszDir);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszArgs, int cch);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string pszArgs);
        void GetHotkey(out short pwHotkey);
        void SetHotkey(short wHotkey);
        void GetShowCmd(out int piShowCmd);
        void SetShowCmd(int iShowCmd);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszIconPath, int cch, out int piIcon);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string pszIconPath, int iIcon);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string pszPathRel, uint dwReserved);
        void Resolve(IntPtr hwnd, uint fFlags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string pszFile);
    }

    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    class ShellLink {
    }

    public static class Creator {
        public static void Create(string path, string target, string arguments, string workdir,
                                  string iconPath, int iconIndex, string description) {
            IShellLinkW link = (IShellLinkW)new ShellLink();
            link.SetPath(target);
            link.SetArguments(arguments);
            link.SetWorkingDirectory(workdir);
            link.SetIconLocation(iconPath, iconIndex);
            link.SetDescription(description);
            ((IPersistFile)link).Save(path, false);
        }
    }
}
"""


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def windows_script(target: str, args: list[str], workdir: Path, icon_path: str, icon_index: int = 0) -> str:
    arguments = " ".join(f'"{a}"' for a in args)
    description = APP_TITLE + "（ターミナル版）"
    values = [_ps_quote(v) for v in (target, arguments, str(workdir), icon_path)]
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "$ProgressPreference = 'SilentlyContinue'",
        "try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}",
        "try {",
        "  $desktop = [Environment]::GetFolderPath('Desktop')",
        "  if (-not $desktop) { $desktop = Join-Path $env:USERPROFILE 'Desktop' }",
        "  if (-not (Test-Path -LiteralPath $desktop)) { New-Item -ItemType Directory -Path $desktop | Out-Null }",
        f"  $path = Join-Path $desktop {_ps_quote(SHORTCUT_NAME + '.lnk')}",
        f"  $target = {values[0]}; $arguments = {values[1]}; $workdir = {values[2]}; $icon = {values[3]}",
        "  try {",
        "    Add-Type -TypeDefinition @'",
        _SHELL_LINK_CS.strip("\n"),
        "'@",
        f"    [SalesMailerShortcut.Creator]::Create($path, $target, $arguments, $workdir, $icon, {int(icon_index)},"
        f" {_ps_quote(description)})",
        "  } catch {",
        "    # 予備: WScript.Shell で英数字の名前で保存してから日本語の名前に変更する",
        "    $tmp = Join-Path $desktop 'SalesMailer-shortcut.lnk'",
        "    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($tmp)",
        "    $s.TargetPath = $target; $s.Arguments = $arguments; $s.WorkingDirectory = $workdir",
        f"    $s.IconLocation = \"$icon,{int(icon_index)}\"; $s.Save()",
        "    Move-Item -LiteralPath $tmp -Destination $path -Force",
        "  }",
        "  if (-not (Test-Path -LiteralPath $path)) { throw \"shortcut was not saved: $path\" }",
        "  Write-Output $path",
        "} catch {",
        "  Write-Output ('ERROR: ' + $_.Exception.Message)",
        "  exit 1",
        "}",
    ])


def mac_command_file(target: str, args: list[str], workdir: Path) -> str:
    quoted = " ".join(_sh_quote(a) for a in [target, *args])
    return (f"#!/bin/bash\n# {APP_TITLE}（ダブルクリックでターミナルが開きます）\n"
            f"cd {_sh_quote(str(workdir))}\nexec {quoted}\n")


def linux_desktop_entry(target: str, args: list[str], workdir: Path, icon: Path) -> str:
    exec_line = " ".join(_desktop_quote(a) for a in [target, *args])
    return "\n".join([
        "[Desktop Entry]", "Type=Application", f"Name={APP_TITLE}",
        "Comment=営業メールの企業調査・送信・管理（ターミナル版）", f"Exec={exec_line}", f"Path={workdir}",
        f"Icon={icon}", "Terminal=true", "Categories=Office;", "",
    ])


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _desktop_quote(value: str) -> str:
    if any(c in value for c in ' \t"\'\\$`'):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`") + '"'
    return value


def _copy_icon(name: str) -> Path | None:
    """アイコン画像をデータフォルダにコピーする（1ファイル版の実行ファイルは終了時に一時フォルダが消えるため）."""
    src = assets_dir() / name
    if not src.exists():
        return None
    dst = data_dir() / name
    shutil.copyfile(src, dst)
    return dst


def shortcut_path() -> Path:
    desktop = desktop_dir()
    if sys.platform == "win32":
        return desktop / f"{SHORTCUT_NAME}.lnk"
    if sys.platform == "darwin":
        return desktop / f"{SHORTCUT_NAME}.command"
    return desktop / "sales-mailer.desktop"


def shortcut_exists() -> bool:
    try:
        return shortcut_path().exists()
    except OSError:
        return False


def create_desktop_shortcut() -> Path:
    """デスクトップにアイコンを作り、そのパスを返す."""
    target, args, workdir = launch_command()
    if sys.platform == "win32":
        if is_frozen():
            icon = target  # exe に埋め込んだアイコン
        else:
            copied = _copy_icon("icon.ico")
            icon = str(copied) if copied else target
        return Path(_powershell(windows_script(target, args, workdir, icon, 0)))

    desktop = desktop_dir()
    desktop.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        path = desktop / f"{SHORTCUT_NAME}.command"
        path.write_text(mac_command_file(target, args, workdir), encoding="utf-8")
        path.chmod(0o755)
        icon = _copy_icon("icon.png")
        if icon:  # Finder 上のアイコンを設定（失敗しても動作には影響なし）
            script = (f'use framework "AppKit"\n'
                      f'set img to current application\'s NSImage\'s alloc()\'s initWithContentsOfFile:"{icon}"\n'
                      f'current application\'s NSWorkspace\'s sharedWorkspace()\'s setIcon:img forFile:"{path}" '
                      f'options:0')
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=30)
        return path

    icon = _copy_icon("icon.png") or Path("mail-send")
    entry = linux_desktop_entry(target, args, workdir, icon)
    path = desktop / "sales-mailer.desktop"
    for dest in (path, Path.home() / ".local" / "share" / "applications" / "sales-mailer.desktop"):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(entry, encoding="utf-8")
        dest.chmod(0o755)
    if shutil.which("gio"):  # GNOME で「起動を許可」済みにする
        subprocess.run(["gio", "set", str(path), "metadata::trusted", "true"], capture_output=True, timeout=10)
    return path
