"""Desktop launcher: starts the FastAPI server in a background thread,
then opens a native window via pywebview pointing at it.

If pywebview fails to import or initialize (no WebView2 runtime, etc.),
falls back to opening the system default browser.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import requests
import uvicorn

from .bootstrap import ensure_desktop_shortcut
from .config import Config, default_config_path
from .db import init_engine
from .service import Service
from .webapp import create_app

log = logging.getLogger(__name__)


class _UvicornThread(threading.Thread):
    def __init__(self, app, host: str, port: int):
        super().__init__(daemon=True)
        self._config = uvicorn.Config(
            app, host=host, port=port, log_level="warning", access_log=False
        )
        self._server = uvicorn.Server(self._config)

    def run(self) -> None:
        self._server.run()

    def shutdown(self) -> None:
        self._server.should_exit = True


def _wait_for_server(url: str, timeout: float = 10.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url, timeout=0.5)
            if r.ok:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.1)
    return False


def _open_window(url: str, title: str) -> bool:
    try:
        import webview  # type: ignore
    except Exception as exc:  # noqa: BLE001
        log.warning("pywebview unavailable (%s); falling back to browser.", exc)
        return False
    try:
        webview.create_window(title, url, width=1200, height=820, min_size=(900, 640))
        webview.start()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("pywebview window failed (%s); falling back to browser.", exc)
        return False


def _open_browser(url: str) -> None:
    import webbrowser

    webbrowser.open(url)


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = Config.load(default_config_path())
    init_engine(config)
    ensure_desktop_shortcut()

    service = Service(config)
    service.start()

    host = config.app.web_host
    port = config.app.web_port
    base = f"http://{host}:{port}"

    app = create_app(service)
    server = _UvicornThread(app, host=host, port=port)
    server.start()

    if not _wait_for_server(f"{base}/api/status", timeout=10.0):
        log.error("Web server did not become ready in time.")

    try:
        opened = _open_window(base, "Omakase Notifier")
        if not opened:
            _open_browser(base)
            # Browser is detached; keep process alive until Ctrl+C.
            log.info("Press Ctrl+C to stop the service.")
            try:
                while True:
                    time.sleep(60)
            except KeyboardInterrupt:
                pass
    finally:
        service.stop()
        server.shutdown()
