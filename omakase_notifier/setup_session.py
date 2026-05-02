"""Bootstrap (or recover) the persistent Chromium profile that the
crawler uses to bypass Cloudflare.

Most users will NEVER need to run this — the main app uses the same
persistent profile and self-bootstraps. Run this only if:

- It's your very first launch and you want to pre-warm the profile
  without going through the web UI's "リスト更新" flow.
- The auto-warmup job has been failing for several days (Cloudflare
  blocks persisting), and you want to manually pass a fresh challenge.

Usage:
    python setup_session.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))

from playwright.sync_api import sync_playwright  # noqa: E402

PROFILE_DIR = Path(HERE) / "data" / "chrome_profile"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def main() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Using persistent Chromium profile at: {PROFILE_DIR}")
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            user_agent=UA,
            locale="ja-JP",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.goto("https://omakase.in/r")

        print()
        print("=" * 64)
        print(" 1. Wait until the restaurant LIST is visible.")
        print(" 2. If a 'Just a moment...' / red 'X' page appears, wait")
        print("    or refresh until the listing actually loads.")
        print(" 3. Optional but recommended: also visit /r/page/2 once")
        print("    so the cookie is exercised on a paginated URL.")
        print(" 4. Switch back here and press Enter.")
        print("=" * 64)
        try:
            input(" >>> Press Enter when the listing is visible <<< ")
        except (EOFError, KeyboardInterrupt):
            print("Aborted.")
            context.close()
            return

        # The persistent context flushes cookies on close.
        context.close()
        print()
        print(f"Profile saved at {PROFILE_DIR}.")
        print(
            "The main app will reuse this profile automatically. "
            "An auto-warmup task running every 12h will keep the "
            "Cloudflare cookie alive thereafter."
        )


if __name__ == "__main__":
    main()
