"""One-time Cloudflare clearance helper.

omakase.in is fronted by Cloudflare's bot protection. A normal browsing
session passes the challenge once, gets a cf_clearance cookie that's
valid for ~30 days, and is then trusted.

Run this script whenever you get blocked (typically once per ~30 days):

    python setup_session.py

Steps the script will guide you through:
  1. A real Chromium window opens at https://omakase.in/r.
  2. If you see the red Cloudflare "X" or a "Just a moment..." page,
     wait ~10 seconds and refresh, or wait a few minutes — the IP may
     be in a temporary cooldown. Repeat until the actual restaurant
     list is visible.
  3. Switch to this PowerShell window and press Enter.
  4. The session is saved to data/storage_state.json. All future
     crawls will reuse it and stay below Cloudflare's bot threshold.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))

from playwright.sync_api import sync_playwright  # noqa: E402

STORAGE_PATH = Path(HERE) / "data" / "storage_state.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def main() -> None:
    STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    print("Opening Chromium pointed at https://omakase.in/r ...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=UA,
            locale="ja-JP",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.goto("https://omakase.in/r")

        print()
        print("=" * 64)
        print(" In the Chromium window:")
        print(" 1. Wait until the restaurant LIST (cards) is visible.")
        print(" 2. If a red 'Attention Required' / 'Just a moment...'")
        print("    page appears, wait or refresh until it clears.")
        print(" 3. Optional but recommended: also visit /r/page/2 or")
        print("    /r/page/3 manually so the cookie is exercised once")
        print("    on a paginated URL too.")
        print(" 4. Then switch back here and press Enter.")
        print("=" * 64)
        try:
            input(" >>> Press Enter when the listing is visible <<< ")
        except (EOFError, KeyboardInterrupt):
            print("Aborted.")
            browser.close()
            return

        context.storage_state(path=str(STORAGE_PATH))
        print()
        print(f"Session saved to: {STORAGE_PATH}")
        print(
            "All future crawls will reuse it. Re-run this script "
            "whenever you get blocked again (typically every 25-30 days)."
        )
        browser.close()


if __name__ == "__main__":
    main()
