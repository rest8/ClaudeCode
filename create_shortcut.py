"""Create a Windows desktop shortcut for Omakase Auto-Booker.

Run this script once to create a desktop shortcut:
    python create_shortcut.py
"""

import os
import subprocess
import sys
from pathlib import Path


def create_icon(icon_path: Path):
    """Generate an .ico file for the shortcut using Pillow."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow is not installed. Shortcut will be created without a custom icon.")
        return False

    sizes = [16, 32, 48, 64, 128, 256]
    images = []

    for size in sizes:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Orange circle background
        margin = max(1, size // 16)
        draw.ellipse(
            [margin, margin, size - margin, size - margin],
            fill="#ff6b35",
            outline="#cc5500",
            width=max(1, size // 32),
        )

        # White "O" letter in center
        inner = size // 4
        draw.ellipse(
            [inner, inner, size - inner, size - inner],
            fill=None,
            outline="white",
            width=max(2, size // 16),
        )

        images.append(img)

    images[0].save(str(icon_path), format="ICO", sizes=[(s, s) for s in sizes], append_images=images[1:])
    print(f"Icon created: {icon_path}")
    return True


def create_shortcut():
    """Create a Windows desktop shortcut."""
    app_dir = Path(__file__).resolve().parent
    desktop = Path(os.path.expanduser("~/Desktop"))

    if not desktop.exists():
        # Try OneDrive Desktop (common on Windows 11)
        onedrive_desktop = Path(os.path.expanduser("~/OneDrive/Desktop"))
        if onedrive_desktop.exists():
            desktop = onedrive_desktop
        else:
            desktop.mkdir(parents=True, exist_ok=True)

    # Generate icon
    icon_path = app_dir / "omakase_booker" / "gui" / "icon.ico"
    has_icon = create_icon(icon_path)

    # Create launcher .bat (hidden console window)
    launcher_bat = app_dir / "launch_omakase.bat"
    launcher_bat.write_text(
        f'@echo off\r\n'
        f'cd /d "{app_dir}"\r\n'
        f'start /min "" pythonw -m omakase_booker\r\n',
        encoding="utf-8",
    )
    print(f"Launcher script created: {launcher_bat}")

    # Create .lnk shortcut via PowerShell
    shortcut_path = desktop / "Omakase Auto-Booker.lnk"
    icon_arg = f'$s.IconLocation = "{icon_path},0"' if has_icon else ""

    ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$s = $WshShell.CreateShortcut("{shortcut_path}")
$s.TargetPath = "{launcher_bat}"
$s.WorkingDirectory = "{app_dir}"
$s.Description = "Omakase Auto-Booker"
$s.WindowStyle = 7
{icon_arg}
$s.Save()
'''

    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print(f"Desktop shortcut created: {shortcut_path}")
        print("\nDone! Double-click the shortcut on your desktop to launch Omakase Auto-Booker.")
    else:
        print(f"Failed to create shortcut: {result.stderr}")
        print(f"\nAlternatively, you can double-click: {launcher_bat}")


if __name__ == "__main__":
    create_shortcut()
