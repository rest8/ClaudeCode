"""
Time Manager - Transparent click-through overlay for Windows.

Uses Win32 SetLayeredWindowAttributes with:
  - LWA_COLORKEY: #00FF00 (green) pixels become fully transparent + click-through
  - LWA_ALPHA: non-green pixels rendered semi-transparently (see desktop behind)

Usage: python app.py
Requires: pip install pywebview
"""

import os
import sys
import threading
import time
import webview


DIRECTORY = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(DIRECTORY, "index_browser.html")

# COLORREF for pure green: RGB(0,255,0) = 0x0000FF00
COLOR_KEY = 0x0000FF00
# Window-level alpha for non-green pixels (0-255). Lower = more see-through.
WINDOW_ALPHA = 230

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
    Win32 layered window with color key + alpha.
    - Green (#00FF00) pixels: fully transparent + click-through
    - Other pixels: semi-transparent (alpha) so desktop is faintly visible
    """
    if sys.platform != "win32":
        return

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    LWA_COLORKEY = 0x00000001
    LWA_ALPHA = 0x00000002

    # Retry to find the window (may take a moment to appear)
    hwnd = None
    for attempt in range(20):
        hwnd = user32.FindWindowW(None, "Time Manager")
        if hwnd:
            break
        time.sleep(0.2)

    if not hwnd:
        print("[WARN] Could not find Time Manager window for transparency setup")
        return

    # Add WS_EX_LAYERED style
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)

    # Apply color key + alpha
    # - Pixels matching COLOR_KEY → fully transparent + click-through
    # - Other pixels → rendered at WINDOW_ALPHA opacity
    result = user32.SetLayeredWindowAttributes(
        hwnd, COLOR_KEY, WINDOW_ALPHA, LWA_COLORKEY | LWA_ALPHA
    )

    if result:
        print("[OK] Transparent click-through enabled")
    else:
        print("[WARN] SetLayeredWindowAttributes failed")


def on_ready():
    """Wait for window to appear, then apply Win32 transparency."""
    time.sleep(1.0)
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
        transparent=False,
        on_top=True,
        js_api=api,
        easy_drag=False,
    )

    # Apply click-through in background thread after window appears
    threading.Thread(target=on_ready, daemon=True).start()

    webview.start()


if __name__ == "__main__":
    main()
