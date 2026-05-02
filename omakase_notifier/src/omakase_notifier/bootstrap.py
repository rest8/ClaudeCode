"""Self-bootstrapping helpers.

On the very first run, create a desktop shortcut so subsequent launches
can be done by double-clicking an icon. No-op on non-Windows or when
the shortcut already exists.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

SHORTCUT_NAME = "Omakase Notifier.lnk"


def project_root() -> Path:
    # this file is at src/omakase_notifier/bootstrap.py
    return Path(__file__).resolve().parents[2]


def desktop_dir() -> Optional[Path]:
    """Return the user's Desktop on Windows, accounting for OneDrive
    redirection. Returns None on non-Windows or if no candidate exists.
    """
    if sys.platform != "win32":
        return None
    candidates: list[Path] = []
    onedrive = os.environ.get("OneDrive")
    if onedrive:
        candidates.append(Path(onedrive) / "Desktop")
    profile = os.environ.get("USERPROFILE")
    if profile:
        candidates.append(Path(profile) / "Desktop")
    for c in candidates:
        if c.exists():
            return c
    return candidates[0] if candidates else None


def _windowed_python() -> Path:
    """Resolve pythonw.exe (no console) sitting next to sys.executable.
    Falls back to sys.executable when pythonw is unavailable.
    """
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return pyw if pyw.exists() else exe


def _psq(value) -> str:
    """Escape a value for embedding in a PowerShell single-quoted string."""
    return str(value).replace("'", "''")


def _create_shortcut(
    shortcut: Path,
    target: Path,
    arguments: str,
    working_dir: Path,
    icon: Optional[Path],
) -> None:
    icon_line = (
        f"$s.IconLocation = '{_psq(icon)},0';"
        if icon and icon.exists()
        else ""
    )
    ps = (
        "$ws = New-Object -ComObject WScript.Shell;"
        f"$s = $ws.CreateShortcut('{_psq(shortcut)}');"
        f"$s.TargetPath = '{_psq(target)}';"
        f"$s.Arguments = '{_psq(arguments)}';"
        f"$s.WorkingDirectory = '{_psq(working_dir)}';"
        f"{icon_line}"
        "$s.Save()"
    )
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        check=True,
        capture_output=True,
        creationflags=creationflags,
    )


def ensure_desktop_shortcut() -> Optional[Path]:
    """Create the desktop shortcut on first run. Returns the shortcut
    path if created or already present, None otherwise.
    """
    if sys.platform != "win32":
        return None
    desktop = desktop_dir()
    if not desktop:
        return None
    shortcut = desktop / SHORTCUT_NAME
    if shortcut.exists():
        return shortcut

    root = project_root()
    launcher = root / "launcher.py"
    if not launcher.exists():
        log.warning("launcher.py not found at %s; skipping shortcut.", launcher)
        return None

    pyw = _windowed_python()
    icon = root / "assets" / "icon.ico"

    try:
        _create_shortcut(
            shortcut=shortcut,
            target=pyw,
            arguments=f'"{launcher}"',
            working_dir=root,
            icon=icon if icon.exists() else None,
        )
    except FileNotFoundError:
        log.warning("powershell.exe not found; cannot create desktop shortcut.")
        return None
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        log.warning("Desktop shortcut creation failed: %s", stderr.strip())
        return None

    log.info("Desktop shortcut created: %s", shortcut)
    return shortcut
