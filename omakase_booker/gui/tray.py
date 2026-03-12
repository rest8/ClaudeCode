"""System tray icon for Omakase Auto-Booker."""

import threading
from PIL import Image, ImageDraw


def create_tray_icon(on_open, on_quit):
    """Create and run a system tray icon.

    Args:
        on_open: Callback to show the main window.
        on_quit: Callback to quit the application.
    """
    try:
        import pystray
    except ImportError:
        return None

    icon_image = _create_icon_image()

    menu = pystray.Menu(
        pystray.MenuItem("開く", on_open, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("終了", on_quit),
    )

    icon = pystray.Icon(
        "omakase_booker",
        icon_image,
        "Omakase Auto-Booker",
        menu,
    )

    thread = threading.Thread(target=icon.run, daemon=True)
    thread.start()
    return icon


def _create_icon_image() -> Image.Image:
    """Create a simple tray icon image (sushi emoji-style)."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Orange circle background
    draw.ellipse([2, 2, size - 2, size - 2], fill="#ff6b35", outline="#cc5500", width=2)

    # White "O" letter
    draw.ellipse([16, 16, size - 16, size - 16], fill=None, outline="white", width=3)

    return img
