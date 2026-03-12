"""GUI launcher - entry point for the desktop application."""

import logging
import sys
from pathlib import Path
from tkinter import messagebox

from ..config import Config


def launch():
    """Launch the Omakase Auto-Booker GUI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config_path = Path("config.yaml")
    if not config_path.exists():
        # Try to show a GUI error before falling back to console
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "設定ファイルが見つかりません",
                "config.yaml が見つかりません。\n"
                "config.example.yaml をコピーして config.yaml を作成してください。",
            )
            root.destroy()
        except Exception:
            pass
        print("Error: config.yaml not found.")
        print("Copy config.example.yaml to config.yaml and fill in your settings.")
        sys.exit(1)

    config = Config.from_yaml(config_path)

    if not config.omakase_email or not config.omakase_password:
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "設定エラー",
                "config.yaml に Omakase のメール・パスワードが設定されていません。",
            )
            root.destroy()
        except Exception:
            pass
        print("Error: Omakase email and password must be set in config.yaml")
        sys.exit(1)

    # Import here to defer tkinter initialization
    from .app import OmakaseApp
    from .tray import create_tray_icon

    app = OmakaseApp(config)

    # System tray icon (optional, fails silently if pystray not available)
    tray_icon = None
    try:
        tray_icon = create_tray_icon(
            on_open=lambda: app.root.after(0, app.root.deiconify),
            on_quit=lambda: app.root.after(0, app._on_close),
        )
    except Exception:
        pass

    try:
        app.run()
    finally:
        if tray_icon:
            try:
                tray_icon.stop()
            except Exception:
                pass
