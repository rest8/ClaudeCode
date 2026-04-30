"""エントリポイント: `python -m omakase_notifier --config config.yaml`。"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading

from .app import App
from .config import load_config
from .logging_setup import setup_logging
from .tray import run_tray

LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Omakase 空席通知アプリ")
    parser.add_argument("--config", default="config.yaml", help="設定ファイル (YAML)")
    parser.add_argument(
        "--once", action="store_true", help="1回だけチェックして終了 (テスト用)"
    )
    parser.add_argument(
        "--no-tray", action="store_true", help="システムトレイを無効化"
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"設定エラー: {e}", file=sys.stderr)
        return 2

    setup_logging(config.log_file, config.log_level)
    LOGGER.info("起動: config=%s", args.config)

    app = App(config)

    if args.once:
        app._check_all()  # noqa: SLF001 - テスト用に内部メソッドを直接呼ぶ
        return 0

    def _handle_signal(signum, _frame) -> None:
        LOGGER.info("シグナル受信: %s", signum)
        app.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except (ValueError, OSError):
            pass

    worker = threading.Thread(target=app.run, name="poller", daemon=True)
    worker.start()

    if config.tray_enabled and not args.no_tray:
        try:
            run_tray(on_quit=app.stop, on_check_now=app.trigger_check_now)
        except Exception as e:  # noqa: BLE001
            LOGGER.warning("トレイ起動失敗、CLIモードで続行: %s", e)
            worker.join()
    else:
        worker.join()

    app.stop()
    worker.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
