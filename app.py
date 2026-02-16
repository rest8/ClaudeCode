"""
Time Manager - Python native window app
pywebview + Win32 API for true transparent click-through overlay.
Uses color key #010101: pixels of that color become invisible and click-through.

Usage: python app.py
First time: pip install pywebview
"""

import os
import sys
import threading
import webview


DIRECTORY = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(DIRECTORY, "index_browser.html")

window = None


class Api:
    """JavaScript API callable from the HTML frontend."""

    def toggle_pin(self, pinned):
        if window:
            window.on_top = pinned

    def minimize(self):
        if window:
            window.minimize()

    def close_window(self):
        if window:
            window.destroy()


def apply_click_through():
    """
    Win32 color key transparency.
    Makes all #010101 pixels fully transparent AND click-through.
    """
    if sys.platform != "win32":
        return

    import ctypes

    user32 = ctypes.windll.user32

    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    LWA_COLORKEY = 0x00000001

    # Color key in BGR format: #010101 -> 0x00010101
    COLOR_KEY = 0x00010101

    hwnd = user32.FindWindowW(None, "Time Manager")
    if not hwnd:
        return

    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
    user32.SetLayeredWindowAttributes(hwnd, COLOR_KEY, 0, LWA_COLORKEY)


def on_shown():
    """Called after the window is displayed. Apply Win32 transparency."""
    # Small delay to ensure the window is fully ready
    import time
    time.sleep(0.3)
    apply_click_through()


def main():
    global window
    api = Api()

    window = webview.create_window(
        "Time Manager",
        url=HTML_FILE,
        width=420,
        height=520,
        resizable=True,
        frameless=True,
        transparent=True,
        on_top=True,
        js_api=api,
        easy_drag=False,
    )

    # Apply click-through after window is shown
    threading.Thread(target=on_shown, daemon=True).start()

    webview.start()


if __name__ == "__main__":
    main()
