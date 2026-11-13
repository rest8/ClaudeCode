"""営業メール自動化の起動スクリプト（PyInstaller のエントリポイント）.

    python run_app.py                    ターミナル版（既定。デスクトップのアイコンから起動される画面）
    python run_app.py --tab follow       指定したタブで開く（companies/research/newmail/follow/
                                         templates/history/settings）
    python run_app.py --gui              ウィンドウ版（Tkinter）
    python run_app.py --install-shortcut デスクトップにアイコンを作成
    python run_app.py --self-test        依存関係の読み込みだけ確認して終了（ビルド確認用）
"""

import sys


def self_test() -> int:
    import tempfile
    from pathlib import Path

    import anthropic  # AI 機能で使用
    import textual  # ターミナル版の画面

    from sales_mailer import __version__
    from sales_mailer.db import Database
    from sales_mailer.shortcut import assets_dir
    from sales_mailer.tui.app import SalesMailerTUI  # noqa: F401

    with tempfile.TemporaryDirectory() as tmp:
        assert Database(Path(tmp) / "check.db").list_templates()
    assert (assets_dir() / "icon.png").exists(), "icon.png が同梱されていません"
    print(f"SalesMailer {__version__} self-test OK (anthropic {anthropic.__version__}, textual {textual.__name__})")
    return 0


def install_shortcut() -> int:
    from sales_mailer.shortcut import create_desktop_shortcut

    path = create_desktop_shortcut()
    print(f"デスクトップにアイコンを作成しました: {path}")
    return 0


def setup_console() -> None:
    """Windows のコンソールでも日本語を正しく表示・出力できるよう UTF-8 にする."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main() -> int:
    setup_console()
    args = sys.argv[1:]
    if "--self-test" in args:
        return self_test()
    if "--install-shortcut" in args:
        return install_shortcut()
    if "--gui" in args:
        from sales_mailer.gui.app import main as gui_main

        gui_main()
        return 0
    from sales_mailer.tui.app import main as tui_main

    tab = args[args.index("--tab") + 1] if "--tab" in args and args.index("--tab") + 1 < len(args) else None
    tui_main(initial_tab=tab)
    return 0


if __name__ == "__main__":
    sys.exit(main())
