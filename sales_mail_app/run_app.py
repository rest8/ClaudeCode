"""営業メール自動化の起動スクリプト（PyInstaller のエントリポイント）.

    python run_app.py                    ターミナル版（既定。デスクトップのアイコンから起動される画面）
    python run_app.py --tab autosend     指定したタブで開く（companies/autosend/newmail/follow/
                                         templates/history/settings/research）
    python run_app.py --demo             テスト環境（サンプルデータ・メールは実際には送信しない・費用なし）
    python run_app.py --auto-send        画面を開かずに自動送信して終了（タスク スケジューラから起動される）
    python run_app.py --schedule-auto-send 09:30 [--every-day]  毎日の自動送信を登録（Windows）
    python run_app.py --unschedule-auto-send                    登録を解除
    python run_app.py --gui              ウィンドウ版（Tkinter）
    python run_app.py --install-shortcut デスクトップにアイコンを作成
    python run_app.py --self-test        依存関係の読み込みだけ確認して終了（ビルド確認用）
"""

import sys


def self_test() -> int:
    import tempfile
    from pathlib import Path

    import anthropic  # AI 機能で使用
    import openpyxl  # noqa: F401  Excel の取り込み・書き出し
    import textual  # ターミナル版の画面

    from sales_mailer import __version__
    from sales_mailer.db import Database
    from sales_mailer.shortcut import assets_dir
    from sales_mailer.tui.app import SalesMailerTUI  # noqa: F401

    with tempfile.TemporaryDirectory() as tmp:
        assert Database(Path(tmp) / "check.db").list_templates()
        from sales_mailer.csv_io import read_companies_file, write_import_template

        write_import_template(Path(tmp) / "template.xlsx")
        assert read_companies_file(Path(tmp) / "template.xlsx")[0]
    assert (assets_dir() / "icon.png").exists(), "icon.png が同梱されていません"
    print(f"SalesMailer {__version__} self-test OK (anthropic {anthropic.__version__}, textual {textual.__name__})")
    return 0


def install_shortcut() -> int:
    from sales_mailer.config import is_demo
    from sales_mailer.shortcut import create_desktop_shortcut

    path = create_desktop_shortcut(demo=is_demo())
    print(f"デスクトップにアイコンを作成しました: {path}")
    return 0


def setup_console() -> None:
    """Windows のコンソールでも日本語を正しく表示・出力できるよう UTF-8 にする.

    あわせて「簡易編集モード」を無効にする。有効なままだと、画面をクリックしたときに文字の選択が始まり、
    選択中はアプリの表示が止まる（固まったように見える）ため。
    """
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleOutputCP(65001)
            kernel32.SetConsoleCP(65001)
            handle = kernel32.GetStdHandle(-10)  # 標準入力
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                enable_extended_flags, enable_quick_edit = 0x0080, 0x0040
                kernel32.SetConsoleMode(handle, (mode.value | enable_extended_flags) & ~enable_quick_edit)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def auto_send() -> int:
    """タスク スケジューラなどから起動され、画面を開かずに自動送信して終了する."""
    import threading
    from datetime import datetime

    from sales_mailer.autosend import run_auto_send
    from sales_mailer.config import data_dir, is_demo, load_settings, save_settings, settings_path
    from sales_mailer.db import Database

    if is_demo():
        from sales_mailer.demo import demo_settings, ensure_seeded

        if not settings_path().exists():
            save_settings(demo_settings())
    settings = load_settings()
    db = Database(data_dir() / "sales_mailer.db")
    if is_demo():
        ensure_seeded(db)
    log_path = data_dir() / "auto-send.log"

    def progress(message: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
        print(line, flush=True)
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    progress("=== 自動送信を開始します（このウィンドウを閉じると送信は止まります） ===")
    if not is_demo() and not settings.smtp_user:
        progress("メール送信（SMTP）が設定されていないため送信できません。アプリの設定タブで設定してください。")
        return 1
    try:
        result = run_auto_send(db, settings, progress, threading.Event())
    except KeyboardInterrupt:
        progress("中断しました")
        return 1
    hard_failure = bool(result.aborted_reason) and "上限" not in result.aborted_reason
    return 1 if hard_failure else 0


def schedule(args: list[str]) -> int:
    from sales_mailer import scheduler

    try:
        if "--unschedule-auto-send" in args:
            print(scheduler.unregister())
        else:
            index = args.index("--schedule-auto-send")
            time_str = args[index + 1] if index + 1 < len(args) else "09:30"
            print(scheduler.register(time_str, weekdays_only="--every-day" not in args))
    except scheduler.SchedulerError as e:
        print(f"エラー: {e}")
        return 1
    return 0


def main() -> int:
    setup_console()
    args = sys.argv[1:]
    if "--demo" in args:  # テスト環境（サンプルデータ・実際には送信しない）
        import os

        os.environ["SALES_MAILER_DEMO"] = "1"
    if "--self-test" in args:
        return self_test()
    if "--install-shortcut" in args:
        return install_shortcut()
    if "--auto-send" in args:
        return auto_send()
    if "--schedule-auto-send" in args or "--unschedule-auto-send" in args:
        return schedule(args)
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
