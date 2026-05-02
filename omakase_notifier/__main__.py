"""エントリポイント。

サブコマンド一覧:
  run (default)        監視を開始
  discover             店舗一覧をクロール
  restaurants          店舗キャッシュを表示/検索
  subscribers          配信先一覧
  add-subscriber       配信先を追加
  remove-subscriber    配信先を削除
  subscribe            店舗を購読
  unsubscribe          購読を解除
"""
from __future__ import annotations

import logging
import signal
import sys
import threading

from .app import App
from .cli import COMMANDS, build_parser
from .config import load_config
from .logging_setup import setup_logging
from .tray import run_tray

LOGGER = logging.getLogger(__name__)


def _run_app(config, once: bool, no_tray: bool) -> int:
    app = App(config)

    if once:
        app.check_all()
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

    if config.tray_enabled and not no_tray:
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"設定エラー: {e}", file=sys.stderr)
        return 2

    setup_logging(config.log_file, config.log_level)

    cmd = args.command or "run"
    if cmd == "run":
        once = bool(getattr(args, "once", False))
        no_tray = bool(getattr(args, "no_tray", False))
        LOGGER.info("起動: config=%s once=%s no_tray=%s", args.config, once, no_tray)
        return _run_app(config, once=once, no_tray=no_tray)

    handler = COMMANDS.get(cmd)
    if handler is None:
        parser.print_help()
        return 2
    return handler(config, args)


if __name__ == "__main__":
    sys.exit(main())
