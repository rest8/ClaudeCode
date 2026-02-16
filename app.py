"""
Time Manager - Python native window app
pywebview を使って透明背景のネイティブウィンドウで動作します。
使い方: python app.py
初回のみ: pip install pywebview
"""

import os
import webview


DIRECTORY = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(DIRECTORY, "index_browser.html")

window = None


class Api:
    """JavaScript から呼び出せるPython API"""

    def toggle_pin(self, pinned):
        if window:
            window.on_top = pinned

    def minimize(self):
        if window:
            window.minimize()

    def close_window(self):
        if window:
            window.destroy()


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
    )

    webview.start()


if __name__ == "__main__":
    main()
