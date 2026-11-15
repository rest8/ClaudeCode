"""メールアドレスのドメインが存在するかの確認（無料・PC の DNS を使うだけ）.

AI が作った企業リストには、実在しないドメインのアドレスが混ざることがある。
存在しないドメインへ送ると不達になり、送信アカウントの評価が下がる原因になるため、取り込み時に確認する。
ネットワークにつながっていないなど確認できない場合は「不明」として扱い、送信対象から外さない。
"""

from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable

from .db import email_domain

Resolver = Callable[[str], object]


class DomainChecker:
    def __init__(self, resolver: Resolver | None = None, probe_host: str = "www.google.com"):
        self._resolve = resolver or (lambda host: socket.getaddrinfo(host, None))
        self._probe_host = probe_host
        self._cache: dict[str, bool | None] = {}
        self._online: bool | None = None

    def online(self) -> bool:
        """DNS が使えるか（使えなければ確認自体をしない）."""
        if self._online is None:
            try:
                self._resolve(self._probe_host)
                self._online = True
            except OSError:
                self._online = False
        return self._online

    def domain_exists(self, domain: str) -> bool | None:
        """True: 存在する / False: 存在しない / None: 確認できない."""
        domain = (domain or "").strip().lower()
        if not domain:
            return None
        if domain not in self._cache:
            if not self.online():
                return None
            try:
                self._resolve(domain)
                self._cache[domain] = True
            except UnicodeError:
                self._cache[domain] = False
            except OSError:
                # 「www.」付きでも確認（メール用ドメインの直下に Web サーバーが無い会社もある）
                try:
                    self._resolve("www." + domain)
                    self._cache[domain] = True
                except (OSError, UnicodeError):
                    self._cache[domain] = False
        return self._cache[domain]

    def check_emails(self, emails: Iterable[str], progress: Callable[[int, int], None] | None = None,
                     workers: int = 8) -> dict[str, bool | None]:
        """メールアドレス → ドメインが存在するか。同じドメインは1回だけ確認する."""
        emails = [e for e in emails if e]
        domains = sorted({email_domain(e) for e in emails if email_domain(e)})
        results: dict[str, bool | None] = {}
        if domains and self.online():
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for i, (domain, ok) in enumerate(zip(domains, pool.map(self.domain_exists, domains)), 1):
                    results[domain] = ok
                    if progress:
                        progress(i, len(domains))
        return {e: results.get(email_domain(e)) if email_domain(e) else False for e in emails}
