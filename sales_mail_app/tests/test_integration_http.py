"""ローカル HTTP サーバーを使った結合テスト（サイト巡回・Google Places・Claude API のリクエスト形式）."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sales_mailer import research
from sales_mailer.research import EmailCrawler, GooglePlacesSearcher


class _Server:
    def __init__(self, handler_cls):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


SITE = {
    "/robots.txt": ("text/plain", "User-agent: *\nDisallow: /private/\n"),
    "/": ("text/html; charset=utf-8",
          '<html><body><a href="/company/">会社概要</a><a href="/contact/">お問い合わせ</a>'
          '<a href="/private/">秘密</a><a href="https://other.example.org/contact">外部</a></body></html>'),
    "/company/": ("text/html", "<p>採用: recruit@127.0.0.1.test</p>"),
    "/contact/": ("text/html; charset=shift_jis", "<p>メール: info[at]127.0.0.1.test</p>".encode("cp932")),
    "/private/": ("text/html", "<p>secret@127.0.0.1.test</p>"),
}


class SiteHandler(BaseHTTPRequestHandler):
    requested: list[str] = []

    def do_GET(self):  # noqa: N802
        SiteHandler.requested.append(self.path)
        if self.path not in SITE:
            self.send_response(404)
            self.end_headers()
            return
        ctype, body = SITE[self.path]
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def test_crawler_follows_contact_pages_and_respects_robots(monkeypatch):
    server = _Server(SiteHandler)
    try:
        # テスト用サーバーのホスト名に合わせて「同じドメイン」の判定を行う
        monkeypatch.setattr(research, "url_domain", lambda url: "127.0.0.1.test" if "127.0.0.1" in (url or "") else "x")
        crawler = EmailCrawler(max_pages=5, timeout=5, delay=0)
        emails = crawler.find_emails(server.url + "/")
    finally:
        server.close()
    # 問い合わせページ（Shift_JIS・[at] 表記）を優先して巡回し、見つかった時点で終了する
    assert emails == ["info@127.0.0.1.test"]
    assert "/company/" not in SiteHandler.requested
    assert "/private/" not in SiteHandler.requested  # robots.txt で禁止されたページは見ない


class PlacesHandler(BaseHTTPRequestHandler):
    bodies: list[dict] = []
    headers_seen: list = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length))
        PlacesHandler.bodies.append(body)
        PlacesHandler.headers_seen.append(self.headers)
        page = 2 if body.get("pageToken") else 1
        resp = {"places": [{"id": f"id{page}", "displayName": {"text": f"会社{page}"},
                            "formattedAddress": "日本、〒980-0811 宮城県仙台市青葉区一番町1-1"}]}
        if page == 1:
            resp["nextPageToken"] = "next"
        data = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def test_places_search_paginates(monkeypatch):
    server = _Server(PlacesHandler)
    monkeypatch.setattr(GooglePlacesSearcher, "ENDPOINT", server.url + "/v1/places:searchText")
    monkeypatch.setattr(research.time, "sleep", lambda s: None)
    try:
        results = GooglePlacesSearcher("KEY").search("製造業 宮城県", max_results=40)
    finally:
        server.close()
    assert [p.name for p in results] == ["会社1", "会社2"]
    assert results[0].prefecture == "宮城県" and results[0].city == "仙台市"
    first = PlacesHandler.bodies[0]
    assert first["textQuery"] == "製造業 宮城県" and first["languageCode"] == "ja" and first["pageSize"] == 20
    assert PlacesHandler.bodies[1]["pageToken"] == "next"
    assert PlacesHandler.headers_seen[0].get("X-Goog-Api-Key") == "KEY"
    assert "places.websiteUri" in PlacesHandler.headers_seen[0].get("X-Goog-FieldMask")


class ClaudeHandler(BaseHTTPRequestHandler):
    requests: list = []
    responses: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers["Content-Length"])
        ClaudeHandler.requests.append((self.path, self.headers, json.loads(self.rfile.read(length))))
        resp = ClaudeHandler.responses.pop(0)
        data = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def _message(text: str, stop_reason: str = "end_turn") -> dict:
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": text}], "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1}}


@pytest.fixture
def claude_server(monkeypatch):
    pytest.importorskip("anthropic")
    server = _Server(ClaudeHandler)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", server.url)
    ClaudeHandler.requests.clear()
    yield ClaudeHandler
    server.close()


def test_personalize_email_request(claude_server):
    from sales_mailer.ai import FALLBACK_BETA, personalize_email

    claude_server.responses = [_message(json.dumps({"subject": "件名A", "body": "本文A"}))]
    subject, body = personalize_email("sk-test", "claude-opus-5-5", "件名", "本文", {"name": "A社", "industry": "IT"})
    assert (subject, body) == ("件名A", "本文A")
    path, headers, req = claude_server.requests[0]
    assert path.startswith("/v1/messages")
    assert FALLBACK_BETA in headers.get("anthropic-beta", "")
    assert req["model"] == "claude-opus-5-5"
    assert req["fallbacks"] == "default"
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert "A社" in req["messages"][0]["content"]


def test_research_with_claude_handles_pause_turn(claude_server):
    from sales_mailer.ai import research_with_claude

    claude_server.responses = [
        _message("調査中", stop_reason="pause_turn"),
        _message('結果です\n```json\n[{"name": "株式会社テスト", "website": "https://t.co.jp", '
                 '"address": "宮城県仙台市青葉区1-1", "email": "info@t.co.jp"}]\n```'),
    ]
    found = research_with_claude("sk-test", "claude-opus-5-5", [("製造業 宮城県", "宮城県")], 10,
                                 lambda pref: ["既存株式会社"], lambda msg: None, threading.Event())
    assert [(p.name, p.prefecture, p.city, p.email) for p in found] == [
        ("株式会社テスト", "宮城県", "仙台市", "info@t.co.jp")]
    first, second = claude_server.requests[0][2], claude_server.requests[1][2]
    assert {t["type"] for t in first["tools"]} == {"web_search_20260209", "web_fetch_20260209"}
    assert "既存株式会社" in first["messages"][0]["content"]
    # pause_turn の後は、ユーザー発話とアシスタント応答をそのまま送り直して再開する
    assert [m["role"] for m in second["messages"]] == ["user", "assistant"]


def test_refusal_raises(claude_server):
    from sales_mailer.ai import AIError, personalize_email

    claude_server.responses = [_message("", stop_reason="refusal")]
    with pytest.raises(AIError):
        personalize_email("sk-test", "claude-opus-5-5", "件名", "本文", {"name": "A社"})
