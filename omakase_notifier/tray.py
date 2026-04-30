"""システムトレイ常駐 (pystray)。GUI 不可な環境では呼び出さない。"""
from __future__ import annotations

import logging
import threading
from typing import Callable

LOGGER = logging.getLogger(__name__)


def run_tray(on_quit: Callable[[], None], on_check_now: Callable[[], None]) -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError as e:
        LOGGER.warning("pystray/Pillow が利用できないためトレイを無効化: %s", e)
        return

    image = Image.new("RGB", (64, 64), (24, 24, 24))
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 10, 54, 54), fill=(220, 38, 38))
    draw.text((24, 22), "O", fill=(255, 255, 255))

    def _quit(icon: "pystray.Icon", _item) -> None:
        icon.stop()
        on_quit()

    def _check(_icon, _item) -> None:
        threading.Thread(target=on_check_now, daemon=True).start()

    icon = pystray.Icon(
        "OmakaseNotifier",
        image,
        "Omakase 空席通知",
        menu=pystray.Menu(
            pystray.MenuItem("今すぐチェック", _check),
            pystray.MenuItem("終了", _quit),
        ),
    )
    icon.run()
