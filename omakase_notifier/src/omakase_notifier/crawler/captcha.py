"""3rd-party CAPTCHA solver integration (2captcha for now).

Used by the crawler when Cloudflare Turnstile is detected. The user
provides a 2captcha API key in `config.captcha.api_key`. Each solved
captcha costs roughly $0.001-0.003 USD.

Docs: https://2captcha.com/2captcha-api#solving_turnstile
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

_2C_IN = "https://2captcha.com/in.php"
_2C_OUT = "https://2captcha.com/res.php"


def solve_turnstile_2captcha(
    api_key: str,
    sitekey: str,
    page_url: str,
    timeout_seconds: int = 180,
    action: Optional[str] = None,
) -> str:
    """Submit a Cloudflare Turnstile challenge to 2captcha and block
    until the solver returns a token (or `timeout_seconds` elapses).
    Returns the cf-turnstile-response token to inject into the page.
    """
    submit_data = {
        "key": api_key,
        "method": "turnstile",
        "sitekey": sitekey,
        "pageurl": page_url,
        "json": 1,
    }
    if action:
        submit_data["action"] = action

    log.info("2captcha: submitting Turnstile challenge for %s", page_url)
    r = requests.post(_2C_IN, data=submit_data, timeout=30).json()
    if r.get("status") != 1:
        raise RuntimeError(f"2captcha submit failed: {r}")
    captcha_id = r["request"]

    deadline = time.time() + timeout_seconds
    poll_interval = 5
    while time.time() < deadline:
        time.sleep(poll_interval)
        rr = requests.get(
            _2C_OUT,
            params={
                "key": api_key,
                "action": "get",
                "id": captcha_id,
                "json": 1,
            },
            timeout=30,
        ).json()
        if rr.get("status") == 1:
            log.info("2captcha: solved (id=%s)", captcha_id)
            return rr["request"]
        msg = rr.get("request", "")
        if msg != "CAPCHA_NOT_READY":
            raise RuntimeError(f"2captcha solver error: {rr}")
    raise TimeoutError(
        f"2captcha did not return a solution within {timeout_seconds}s"
    )


def solve_turnstile(provider: str, api_key: str, sitekey: str,
                    page_url: str, timeout_seconds: int = 180) -> str:
    """Provider-agnostic dispatcher. Currently only "2captcha"."""
    if provider == "2captcha":
        return solve_turnstile_2captcha(api_key, sitekey, page_url,
                                        timeout_seconds=timeout_seconds)
    raise ValueError(f"unsupported captcha provider: {provider!r}")
