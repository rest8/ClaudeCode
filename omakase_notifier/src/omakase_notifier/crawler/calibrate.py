"""Selector calibration helper.

Run this once against a real listing page and a real restaurant page to
print out anchors and elements that look like availability cells. Use the
output to update LIST_SELECTORS and AVAILABILITY_SELECTORS in
`omakase_notifier.crawler.omakase`.

    python -m omakase_notifier.crawler.calibrate list https://omakase.in/ja/restaurants
    python -m omakase_notifier.crawler.calibrate availability https://omakase.in/ja/r/<id>
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright


def _print_anchors(page) -> None:
    anchors = page.query_selector_all("a")
    seen = set()
    for a in anchors:
        href = a.get_attribute("href") or ""
        if "/r/" in href or "/restaurants/" in href:
            text = (a.inner_text() or "").strip()[:60]
            key = (href, text)
            if key not in seen:
                seen.add(key)
                print(f"LINK  {href!r:70} {text!r}")


def _print_candidate_slots(page) -> None:
    candidate_selectors = [
        '[data-availability="available"]',
        ".calendar-cell.is-available",
        'button[data-status="open"]',
        "[data-datetime]",
        "[data-date]",
        "[aria-label*='空席']",
    ]
    for sel in candidate_selectors:
        els = page.query_selector_all(sel)
        if els:
            print(f"\nSELECTOR  {sel}  matched {len(els)} elements")
            for el in els[:5]:
                attrs = {}
                for k in ("data-datetime", "data-date", "data-price", "aria-label"):
                    v = el.get_attribute(k)
                    if v:
                        attrs[k] = v
                text = (el.inner_text() or "").strip()[:60]
                print(f"    attrs={attrs}  text={text!r}")


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    mode, url = sys.argv[1], sys.argv[2]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(locale="ja-JP")
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle")
        if mode == "list":
            _print_anchors(page)
        elif mode == "availability":
            _print_candidate_slots(page)
        else:
            print(f"Unknown mode: {mode}")
        input("\nPress Enter to close browser...")
        browser.close()


if __name__ == "__main__":
    main()
