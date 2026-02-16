"""
Time Manager - Python launcher
Pythonの標準ライブラリだけで動作します。追加インストール不要です。
使い方: python app.py
"""

import http.server
import os
import sys
import threading
import webbrowser

PORT = 8080
DIRECTORY = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        # Serve index_browser.html as the default page
        if self.path == "/" or self.path == "":
            self.path = "/index_browser.html"
        return super().do_GET()

    def log_message(self, format, *args):
        # Suppress noisy access logs
        pass


def main():
    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Time Manager を起動しています...")
    print(f"ブラウザで http://127.0.0.1:{PORT} を開いています...")
    print(f"終了するには Ctrl+C を押してください。")

    # Open browser after a short delay
    threading.Timer(0.5, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了しました。")
        server.server_close()
        sys.exit(0)


if __name__ == "__main__":
    main()
