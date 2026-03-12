"""Google Chat approval workflow for booking payment.

Sends an approval request card to Google Chat via webhook,
then waits for the user to approve or reject via a callback.

Two modes supported:
  1. Interactive card with buttons (requires incoming webhook URL configured
     in Google Chat + a publicly reachable callback URL)
  2. Simple notification + polling (user replies "approve" or "reject" in chat,
     and we poll for the response via the webhook)

For simplicity, this module uses approach 1 with a local HTTP server
that receives the button callback, plus ngrok/cloudflare tunnel or
direct port forwarding for external reachability.

If no callback URL is available, falls back to a simple message +
manual confirmation within the app (GUI dialog or CLI prompt).
"""

import asyncio
import json
import logging
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

import urllib.request

logger = logging.getLogger(__name__)

# Approval states
PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"


class ApprovalState:
    """Thread-safe approval state container."""

    def __init__(self):
        self._state = PENDING
        self._lock = threading.Lock()
        self._event = threading.Event()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def approve(self):
        with self._lock:
            self._state = APPROVED
        self._event.set()

    def reject(self):
        with self._lock:
            self._state = REJECTED
        self._event.set()

    def wait(self, timeout: float | None = None) -> str:
        """Block until a decision is made. Returns the final state."""
        self._event.wait(timeout=timeout)
        return self.state


class _ApprovalCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler that receives approval/rejection callbacks from Google Chat."""

    approval_state: ApprovalState | None = None

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}

        # Google Chat interactive card callback sends action parameters
        action = data.get("action", {}).get("actionMethodName", "")
        if not action:
            # Also check common.formInputs or direct parameters
            action = data.get("commonEventObject", {}).get("parameters", {}).get("action", "")
        if not action:
            # Fallback: check URL path
            path = urlparse(self.path).path.strip("/")
            action = path

        logger.info("Approval callback received: action=%s", action)

        if action == "approve" and self.approval_state:
            self.approval_state.approve()
            self._respond(200, {"text": "承認しました。決済を実行します。"})
        elif action == "reject" and self.approval_state:
            self.approval_state.reject()
            self._respond(200, {"text": "却下しました。決済をキャンセルします。"})
        else:
            self._respond(400, {"text": "不明なアクションです。"})

    def _respond(self, code: int, body: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, format, *args):
        logger.debug("ApprovalServer: %s", format % args)


def start_approval_server(
    approval_state: ApprovalState,
    port: int = 8391,
) -> HTTPServer:
    """Start a local HTTP server to receive approval callbacks.

    Returns the server instance (running in a daemon thread).
    """
    _ApprovalCallbackHandler.approval_state = approval_state

    server = HTTPServer(("0.0.0.0", port), _ApprovalCallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Approval callback server started on port %d", port)
    return server


def send_approval_request(
    webhook_url: str,
    restaurant_name: str,
    booking_date: str,
    booking_time: str,
    party_size: int,
    fee_per_person: int = 390,
    callback_url: str | None = None,
) -> bool:
    """Send an approval request card to Google Chat.

    Args:
        webhook_url: Google Chat incoming webhook URL.
        restaurant_name: Name of the restaurant.
        booking_date: Booking date (YYYY-MM-DD).
        booking_time: Booking time (HH:MM).
        party_size: Number of guests.
        fee_per_person: Seat reservation fee per person (JPY).
        callback_url: Base URL for approval/rejection callbacks.

    Returns:
        True if the message was sent successfully.
    """
    total_fee = fee_per_person * party_size

    if callback_url:
        # Interactive card with approve/reject buttons
        payload = _build_card_message(
            restaurant_name, booking_date, booking_time,
            party_size, fee_per_person, total_fee, callback_url,
        )
    else:
        # Simple text message (user must approve via app)
        payload = _build_text_message(
            restaurant_name, booking_date, booking_time,
            party_size, fee_per_person, total_fee,
        )

    return _post_to_webhook(webhook_url, payload)


def _build_card_message(
    restaurant_name: str,
    booking_date: str,
    booking_time: str,
    party_size: int,
    fee_per_person: int,
    total_fee: int,
    callback_url: str,
) -> dict:
    """Build a Google Chat card message with approval buttons."""
    return {
        "cardsV2": [
            {
                "cardId": "approval_request",
                "card": {
                    "header": {
                        "title": "予約決済の承認依頼",
                        "subtitle": "Omakase Auto-Booker",
                        "imageUrl": "https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/restaurant/default/48px.svg",
                        "imageType": "CIRCLE",
                    },
                    "sections": [
                        {
                            "header": "予約内容",
                            "widgets": [
                                {
                                    "decoratedText": {
                                        "topLabel": "レストラン",
                                        "text": restaurant_name,
                                        "startIcon": {"knownIcon": "RESTAURANT_ICON"},
                                    }
                                },
                                {
                                    "decoratedText": {
                                        "topLabel": "日時",
                                        "text": f"{booking_date} {booking_time}",
                                        "startIcon": {"knownIcon": "CLOCK"},
                                    }
                                },
                                {
                                    "decoratedText": {
                                        "topLabel": "人数",
                                        "text": f"{party_size}名",
                                        "startIcon": {"knownIcon": "PERSON"},
                                    }
                                },
                                {
                                    "decoratedText": {
                                        "topLabel": "席予約手数料",
                                        "text": f"¥{fee_per_person:,} x {party_size}名 = ¥{total_fee:,}",
                                        "startIcon": {"knownIcon": "DOLLAR"},
                                    }
                                },
                            ],
                        },
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "承認（決済実行）",
                                                "color": {
                                                    "red": 0.204,
                                                    "green": 0.659,
                                                    "blue": 0.325,
                                                    "alpha": 1.0,
                                                },
                                                "onClick": {
                                                    "openLink": {
                                                        "url": f"{callback_url}/approve",
                                                    }
                                                },
                                            },
                                            {
                                                "text": "却下（キャンセル）",
                                                "color": {
                                                    "red": 0.918,
                                                    "green": 0.263,
                                                    "blue": 0.208,
                                                    "alpha": 1.0,
                                                },
                                                "onClick": {
                                                    "openLink": {
                                                        "url": f"{callback_url}/reject",
                                                    }
                                                },
                                            },
                                        ]
                                    }
                                }
                            ],
                        },
                    ],
                },
            }
        ]
    }


def _build_text_message(
    restaurant_name: str,
    booking_date: str,
    booking_time: str,
    party_size: int,
    fee_per_person: int,
    total_fee: int,
) -> dict:
    """Build a simple text message for approval notification."""
    return {
        "text": (
            "🔔 *予約決済の承認依頼*\n\n"
            f"レストラン: {restaurant_name}\n"
            f"日時: {booking_date} {booking_time}\n"
            f"人数: {party_size}名\n"
            f"席予約手数料: ¥{fee_per_person:,} x {party_size}名 = ¥{total_fee:,}\n\n"
            "⚠️ アプリ上で承認/却下してください。"
        ),
    }


def _post_to_webhook(webhook_url: str, payload: dict) -> bool:
    """POST a JSON payload to a Google Chat webhook."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json; charset=UTF-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                logger.info("Approval request sent to Google Chat")
                return True
            else:
                logger.warning("Google Chat webhook returned %d", resp.status)
                return False
    except Exception:
        logger.exception("Failed to send approval request to Google Chat")
        return False


async def request_approval(
    webhook_url: str,
    restaurant_name: str,
    booking_date: str,
    booking_time: str,
    party_size: int,
    fee_per_person: int = 390,
    callback_url: str | None = None,
    timeout_seconds: int = 300,
) -> str:
    """Send an approval request and wait for the response.

    This is the main high-level function used by the booking flow.

    Args:
        webhook_url: Google Chat webhook URL.
        restaurant_name: Restaurant name.
        booking_date: Date (YYYY-MM-DD).
        booking_time: Time (HH:MM).
        party_size: Number of guests.
        fee_per_person: Fee per person in JPY.
        callback_url: Callback URL for interactive buttons.
        timeout_seconds: Max wait time for approval.

    Returns:
        "approved", "rejected", or "pending" (timeout).
    """
    state = ApprovalState()
    server = None

    try:
        # Start callback server if callback URL is provided
        if callback_url:
            parsed = urlparse(callback_url)
            port = parsed.port or 8391
            server = start_approval_server(state, port)

        # Send the approval request
        sent = send_approval_request(
            webhook_url,
            restaurant_name,
            booking_date,
            booking_time,
            party_size,
            fee_per_person,
            callback_url,
        )

        if not sent:
            logger.warning("Failed to send approval request, proceeding without approval")
            return APPROVED  # Fallback: don't block booking if notification fails

        logger.info(
            "Waiting for approval (timeout: %ds)...",
            timeout_seconds,
        )

        # Wait asynchronously
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            state.wait,
            timeout_seconds,
        )

        logger.info("Approval result: %s", result)
        return result

    finally:
        if server:
            server.shutdown()
