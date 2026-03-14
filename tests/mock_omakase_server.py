"""Mock Omakase.in server for integration testing.

Simulates the key pages and booking flow of omakase.in:
  - Login page (/users/sign_in)
  - Top page with area/genre navigation (/)
  - Area listing pages (/ja/area/tokyo, etc.)
  - Genre listing pages (/ja/genre/sushi, etc.)
  - Restaurant detail page (/r/{id})
  - Booking flow: select party size → date → time → confirm → payment
  - Search (/search?q=...)

State is managed in-memory so tests can control available slots,
cancellation behavior, etc.
"""

import json
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from urllib.parse import urlparse, parse_qs

# ── Mock Data ──────────────────────────────────────────────

MOCK_EMAIL = "test@example.com"
MOCK_PASSWORD = "testpassword"

# Areas and genres for browsing
MOCK_AREAS = [
    {"id": "tokyo", "name": "東京"},
    {"id": "osaka", "name": "大阪"},
    {"id": "kyoto", "name": "京都"},
]

MOCK_GENRES = [
    {"id": "sushi", "name": "鮨"},
    {"id": "tempura", "name": "天ぷら"},
    {"id": "kaiseki", "name": "懐石"},
]

# Restaurants per area/genre
MOCK_RESTAURANTS = {
    "tokyo": [
        {"id": "rest001", "name": "鮨 テスト太郎", "genre": "鮨", "area": "東京・銀座", "price": "¥30,000〜"},
        {"id": "rest002", "name": "天ぷら テスト", "genre": "天ぷら", "area": "東京・赤坂", "price": "¥20,000〜"},
        {"id": "rest003", "name": "割烹 テスト", "genre": "懐石", "area": "東京・六本木", "price": "¥25,000〜"},
    ],
    "osaka": [
        {"id": "rest004", "name": "鮨 大阪テスト", "genre": "鮨", "area": "大阪・北新地", "price": "¥28,000〜"},
    ],
    "kyoto": [
        {"id": "rest005", "name": "京懐石 テスト", "genre": "懐石", "area": "京都・祇園", "price": "¥35,000〜"},
    ],
    "sushi": [
        {"id": "rest001", "name": "鮨 テスト太郎", "genre": "鮨", "area": "東京・銀座", "price": "¥30,000〜"},
        {"id": "rest004", "name": "鮨 大阪テスト", "genre": "鮨", "area": "大阪・北新地", "price": "¥28,000〜"},
    ],
    "tempura": [
        {"id": "rest002", "name": "天ぷら テスト", "genre": "天ぷら", "area": "東京・赤坂", "price": "¥20,000〜"},
    ],
    "kaiseki": [
        {"id": "rest003", "name": "割烹 テスト", "genre": "懐石", "area": "東京・六本木", "price": "¥25,000〜"},
        {"id": "rest005", "name": "京懐石 テスト", "genre": "懐石", "area": "京都・祇園", "price": "¥35,000〜"},
    ],
}

ALL_RESTAURANTS = {
    "rest001": {"name": "鮨 テスト太郎", "genre": "鮨", "area": "東京・銀座", "price": "¥30,000〜"},
    "rest002": {"name": "天ぷら テスト", "genre": "天ぷら", "area": "東京・赤坂", "price": "¥20,000〜"},
    "rest003": {"name": "割烹 テスト", "genre": "懐石", "area": "東京・六本木", "price": "¥25,000〜"},
    "rest004": {"name": "鮨 大阪テスト", "genre": "鮨", "area": "大阪・北新地", "price": "¥28,000〜"},
    "rest005": {"name": "京懐石 テスト", "genre": "懐石", "area": "京都・祇園", "price": "¥35,000〜"},
}


class MockOmakaseState:
    """Mutable server state for controlling test scenarios."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.logged_in = False
        # Available slots per restaurant: {rest_id: [{date, time, available}]}
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        next_week = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        self.available_slots: dict[str, list[dict]] = {
            "rest001": [
                {"date": tomorrow, "time": "18:00", "available": True},
                {"date": tomorrow, "time": "19:00", "available": True},
                {"date": next_week, "time": "18:00", "available": True},
            ],
            "rest002": [
                {"date": tomorrow, "time": "18:00", "available": True},
                {"date": tomorrow, "time": "20:00", "available": True},
            ],
        }
        # Open times per restaurant
        self.open_times: dict[str, str] = {
            "rest001": "予約開始: 2026年4月1日 10:00",
            "rest002": "受付開始: 2026年3月20日 12:00",
        }
        # Cancellation policies
        self.cancellation_policies: dict[str, str] = {
            "rest001": "キャンセルポリシー：前日50%、当日100%のキャンセル料が発生します。",
            "rest002": "キャンセルポリシー：3日前まで無料、前日50%、当日100%。",
        }
        # Reservation in progress
        self.current_reservation: dict | None = None
        # Completed bookings
        self.completed_bookings: list[dict] = []
        # Payment should succeed
        self.payment_succeeds = True
        # Lottery state
        self.lottery_entries: set[str] = set()
        self.lottery_winners: set[str] = set()


# Global state instance
state = MockOmakaseState()


# ── HTML Templates ─────────────────────────────────────────

def _html_page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ja">
<head><meta charset="utf-8"><title>{title}</title></head>
<body>{body}</body>
</html>"""


def _login_page() -> str:
    return _html_page("ログイン - Omakase", """
    <h1>ログイン</h1>
    <form method="POST" action="/users/sign_in">
        <input type="email" name="email" placeholder="メールアドレス">
        <input type="password" name="password" placeholder="パスワード">
        <button type="submit">ログイン</button>
    </form>
    """)


def _top_page() -> str:
    nav_links = []
    for area in MOCK_AREAS:
        nav_links.append(f'<a href="/ja/area/{area["id"]}" class="area-link">{area["name"]}</a>')
    for genre in MOCK_GENRES:
        nav_links.append(f'<a href="/ja/genre/{genre["id"]}" class="genre-link">{genre["name"]}</a>')

    return _html_page("Omakase - レストラン予約", f"""
    <h1>Omakase</h1>
    <nav class="main-nav">
        <div class="area-nav">
            <h2>エリア</h2>
            {"".join(nav_links[:len(MOCK_AREAS)])}
        </div>
        <div class="genre-nav">
            <h2>ジャンル</h2>
            {"".join(nav_links[len(MOCK_AREAS):])}
        </div>
    </nav>
    <form action="/search" method="GET">
        <input type="search" name="q" placeholder="検索">
    </form>
    """)


def _listing_page(category_name: str, restaurants: list[dict]) -> str:
    cards = []
    for r in restaurants:
        cards.append(f"""
        <article class="restaurant-card">
            <a href="/r/{r['id']}">
                <h3 class="restaurant-name">{r['name']}</h3>
            </a>
            <span class="area-tag">{r.get('area', '')}</span>
            <span class="genre-tag">{r.get('genre', '')}</span>
            <span class="price-tag">{r.get('price', '')}</span>
            <p class="description">{r['name']}のおまかせコース</p>
        </article>
        """)

    return _html_page(f"{category_name} - Omakase", f"""
    <h1>{category_name}</h1>
    <div class="restaurant-list">
        {"".join(cards)}
    </div>
    """)


def _restaurant_page(rest_id: str) -> str:
    info = ALL_RESTAURANTS.get(rest_id, {"name": "Unknown", "genre": "", "area": "", "price": ""})
    slots = state.available_slots.get(rest_id, [])
    open_time = state.open_times.get(rest_id, "")
    cancel_policy = state.cancellation_policies.get(rest_id, "")

    # Build slot display
    slot_html = []
    for s in slots:
        if s["available"]:
            slot_html.append(
                f'<button class="time-slot available" '
                f'onclick="location.href=\'/r/{rest_id}/reserve?date={s["date"]}&time={s["time"]}\'">'
                f'{s["date"]} {s["time"]}</button>'
            )

    # Lottery button for lottery restaurants
    lottery_html = ""
    if rest_id in state.lottery_entries:
        lottery_html = '<p class="lottery-status">エントリー済み</p>'
    elif rest_id in state.lottery_winners:
        lottery_html = f'<a href="/r/{rest_id}/reserve" class="winner-link">当選しました！予約する</a>'
    else:
        lottery_html = f"""
        <form method="POST" action="/r/{rest_id}/lottery">
            <button type="submit" class="lottery-btn">抽選エントリー</button>
        </form>
        """

    return _html_page(f"{info['name']} - Omakase", f"""
    <h1>{info['name']}</h1>
    <div class="restaurant-info">
        <p class="area">{info['area']}</p>
        <p class="genre">{info['genre']}</p>
        <p class="price">{info['price']}</p>
    </div>
    <div class="open-time">{open_time}</div>
    <div class="cancellation-policy">
        <h3>キャンセルポリシー</h3>
        <p>{cancel_policy}</p>
    </div>
    <div class="availability">
        <h2>空き状況</h2>
        <select name="party_size" class="party-size-select">
            <option value="1">1名</option>
            <option value="2" selected>2名</option>
            <option value="3">3名</option>
            <option value="4">4名</option>
        </select>
        <div class="slots">
            {"".join(slot_html) if slot_html else '<p>現在空き枠はありません</p>'}
        </div>
    </div>
    <div class="lottery-section">
        {lottery_html}
    </div>
    """)


def _reserve_page(rest_id: str, date_str: str, time_str: str) -> str:
    info = ALL_RESTAURANTS.get(rest_id, {"name": "Unknown"})
    return _html_page(f"予約確認 - {info['name']}", f"""
    <h1>予約確認</h1>
    <div class="booking-summary">
        <p>レストラン: {info['name']}</p>
        <p>日時: {date_str} {time_str}</p>
        <p>人数: 2名</p>
    </div>
    <form method="POST" action="/r/{rest_id}/confirm">
        <input type="hidden" name="date" value="{date_str}">
        <input type="hidden" name="time" value="{time_str}">
        <button type="submit">予約を確定する</button>
    </form>
    """)


def _confirm_page(rest_id: str, date_str: str, time_str: str) -> str:
    info = ALL_RESTAURANTS.get(rest_id, {"name": "Unknown"})
    return _html_page(f"決済 - {info['name']}", f"""
    <h1>お支払い</h1>
    <div class="payment-info">
        <p>レストラン: {info['name']}</p>
        <p>日時: {date_str} {time_str}</p>
        <p class="fee">手数料: ¥390 × 2名 = ¥780</p>
    </div>
    <form method="POST" action="/r/{rest_id}/pay">
        <input type="hidden" name="date" value="{date_str}">
        <input type="hidden" name="time" value="{time_str}">
        <button type="submit">お支払いを確定する</button>
    </form>
    """)


def _payment_success_page(rest_id: str) -> str:
    info = ALL_RESTAURANTS.get(rest_id, {"name": "Unknown"})
    return _html_page(f"予約完了 - {info['name']}", f"""
    <h1>予約が完了しました</h1>
    <p>ありがとうございます。{info['name']}のご予約が確定しました。</p>
    """)


def _payment_failure_page() -> str:
    return _html_page("決済エラー", """
    <h1>決済エラー</h1>
    <p>お支払いに失敗しました。カード情報をご確認ください。</p>
    """)


def _slot_taken_page() -> str:
    return _html_page("満席", """
    <h1>満席</h1>
    <p>申し訳ございません。この枠は満席です。予約できません。</p>
    """)


# ── HTTP Handler ───────────────────────────────────────────

class MockOmakaseHandler(BaseHTTPRequestHandler):
    """HTTP handler simulating omakase.in."""

    def log_message(self, format, *args):
        # Suppress logs during tests
        pass

    def _send_html(self, html: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _redirect(self, location: str):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def _read_body(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        params = {}
        for pair in body.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                params[k] = v
        return params

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        # Login page
        if path == "/users/sign_in":
            self._send_html(_login_page())
            return

        # Top page
        if path in ("/", "/ja", "/ja/"):
            self._send_html(_top_page())
            return

        # Area listing
        if path.startswith("/ja/area/"):
            area_id = path.split("/ja/area/")[-1].strip("/")
            restaurants = MOCK_RESTAURANTS.get(area_id, [])
            area_name = next((a["name"] for a in MOCK_AREAS if a["id"] == area_id), area_id)
            self._send_html(_listing_page(area_name, restaurants))
            return

        # Genre listing
        if path.startswith("/ja/genre/"):
            genre_id = path.split("/ja/genre/")[-1].strip("/")
            restaurants = MOCK_RESTAURANTS.get(genre_id, [])
            genre_name = next((g["name"] for g in MOCK_GENRES if g["id"] == genre_id), genre_id)
            self._send_html(_listing_page(genre_name, restaurants))
            return

        # Search
        if path == "/search":
            query = qs.get("q", [""])[0].lower()
            results = [
                r for r_id, r in ALL_RESTAURANTS.items()
                if query in r["name"].lower() or query in r.get("genre", "").lower()
                    or query in r.get("area", "").lower()
            ]
            # Convert to listing format with IDs
            result_list = []
            for r_id, r in ALL_RESTAURANTS.items():
                if query in r["name"].lower() or query in r.get("genre", "").lower() \
                        or query in r.get("area", "").lower():
                    result_list.append({"id": r_id, **r})
            self._send_html(_listing_page(f"検索: {query}", result_list))
            return

        # Restaurant detail page
        if path.startswith("/r/"):
            parts = path.split("/r/")[-1].strip("/").split("/")
            rest_id = parts[0]

            if len(parts) > 1 and parts[1] == "reserve":
                date_str = qs.get("date", [""])[0]
                time_str = qs.get("time", [""])[0]
                self._send_html(_reserve_page(rest_id, date_str, time_str))
                return

            if rest_id in ALL_RESTAURANTS:
                self._send_html(_restaurant_page(rest_id))
                return

            self._send_html(_html_page("Not Found", "<h1>404</h1>"), status=404)
            return

        # State API (for test control)
        if path == "/_test/state":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "logged_in": state.logged_in,
                "completed_bookings": state.completed_bookings,
                "lottery_entries": list(state.lottery_entries),
            }).encode())
            return

        self._send_html(_html_page("Not Found", "<h1>404</h1>"), status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_body()

        # Login
        if path == "/users/sign_in":
            email = body.get("email", "")
            password = body.get("password", "")
            if email == MOCK_EMAIL and password == MOCK_PASSWORD:
                state.logged_in = True
                self._redirect("/")
            else:
                self._send_html(_login_page())
            return

        # Confirm booking
        if path.startswith("/r/") and path.endswith("/confirm"):
            rest_id = path.split("/r/")[-1].split("/confirm")[0]
            date_str = body.get("date", "")
            time_str = body.get("time", "")

            # Check if slot is still available
            slots = state.available_slots.get(rest_id, [])
            slot_found = False
            for s in slots:
                if s["date"] == date_str and s["time"] == time_str and s["available"]:
                    slot_found = True
                    break

            if not slot_found:
                self._send_html(_slot_taken_page())
                return

            state.current_reservation = {
                "restaurant_id": rest_id,
                "date": date_str,
                "time": time_str,
            }
            self._send_html(_confirm_page(rest_id, date_str, time_str))
            return

        # Pay
        if path.startswith("/r/") and path.endswith("/pay"):
            rest_id = path.split("/r/")[-1].split("/pay")[0]

            if state.payment_succeeds:
                # Mark slot as taken
                if state.current_reservation:
                    res = state.current_reservation
                    for s in state.available_slots.get(res["restaurant_id"], []):
                        if s["date"] == res["date"] and s["time"] == res["time"]:
                            s["available"] = False
                    state.completed_bookings.append(dict(res))
                    state.current_reservation = None
                self._send_html(_payment_success_page(rest_id))
            else:
                self._send_html(_payment_failure_page())
            return

        # Lottery entry
        if path.startswith("/r/") and path.endswith("/lottery"):
            rest_id = path.split("/r/")[-1].split("/lottery")[0]
            state.lottery_entries.add(rest_id)
            self._send_html(_html_page("エントリー完了", f"""
            <h1>エントリー完了</h1>
            <p>抽選にエントリーしました。結果をお待ちください。</p>
            """))
            return

        self._send_html(_html_page("Not Found", "<h1>404</h1>"), status=404)


# ── Test control API endpoints ─────────────────────────────

class MockOmakaseTestHandler(MockOmakaseHandler):
    """Extended handler with test control endpoints."""

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Test control: reset state
        if path == "/_test/reset":
            state.reset()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            return

        # Test control: set available slots
        if path == "/_test/set_slots":
            body_raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            data = json.loads(body_raw)
            rest_id = data.get("restaurant_id")
            slots = data.get("slots", [])
            state.available_slots[rest_id] = slots
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            return

        # Test control: set payment success/failure
        if path == "/_test/set_payment":
            body_raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            data = json.loads(body_raw)
            state.payment_succeeds = data.get("succeeds", True)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            return

        # Test control: simulate cancellation (make a slot available again)
        if path == "/_test/cancel_slot":
            body_raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            data = json.loads(body_raw)
            rest_id = data["restaurant_id"]
            for s in state.available_slots.get(rest_id, []):
                if s["date"] == data["date"] and s["time"] == data["time"]:
                    s["available"] = True
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            return

        # Test control: set lottery winner
        if path == "/_test/set_lottery_winner":
            body_raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            data = json.loads(body_raw)
            state.lottery_winners.add(data["restaurant_id"])
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            return

        super().do_POST()


# ── Server Start/Stop ──────────────────────────────────────

def start_mock_server(port: int = 0) -> tuple[HTTPServer, int]:
    """Start the mock server on the given port (0 = auto-assign).

    Returns (server, actual_port).
    """
    server = HTTPServer(("127.0.0.1", port), MockOmakaseTestHandler)
    actual_port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, actual_port


def stop_mock_server(server: HTTPServer):
    """Stop the mock server."""
    server.shutdown()
