"""Pytest fixtures for Omakase auto-booker tests."""

import json
import pytest
import urllib.request

from .mock_omakase_server import start_mock_server, stop_mock_server, state, MOCK_EMAIL, MOCK_PASSWORD
from omakase_booker.config import Config, RestaurantTarget
from omakase_booker.omakase_client import OmakaseClient


@pytest.fixture(scope="session")
def mock_server():
    """Start the mock Omakase server for the test session."""
    server, port = start_mock_server()
    yield port
    stop_mock_server(server)


@pytest.fixture(autouse=True)
def reset_state(mock_server):
    """Reset mock server state before each test."""
    req = urllib.request.Request(
        f"http://127.0.0.1:{mock_server}/_test/reset",
        method="POST",
    )
    urllib.request.urlopen(req)
    yield


@pytest.fixture
def mock_port(mock_server):
    """Provide the mock server port."""
    return mock_server


@pytest.fixture
def base_url(mock_port):
    """Base URL for the mock server."""
    return f"http://127.0.0.1:{mock_port}"


@pytest.fixture
def config(base_url):
    """Config pointed at the mock server."""
    return Config(
        omakase_email=MOCK_EMAIL,
        omakase_password=MOCK_PASSWORD,
        headless=True,
        browser_timeout_ms=10000,
        check_interval_seconds=1,
        fast_poll_interval_seconds=0.1,
        approval_fee_per_person=390,
        continuous_mode=False,
        cancellation_check_interval_seconds=1,
        target_restaurants=[
            RestaurantTarget(
                name="鮨 テスト太郎",
                omakase_url=f"{base_url}/r/rest001",
                party_size=2,
                preferred_times=["18:00", "19:00"],
                booking_mode="first_come",
            ),
        ],
    )


@pytest.fixture
async def client(config, base_url, monkeypatch):
    """Create and start an OmakaseClient pointed at the mock server."""
    # Patch the base URL and login URL
    import omakase_booker.omakase_client as client_mod
    monkeypatch.setattr(client_mod, "OMAKASE_BASE_URL", base_url)
    monkeypatch.setattr(client_mod, "LOGIN_URL", f"{base_url}/users/sign_in")

    c = OmakaseClient(config)
    await c.start()
    yield c
    await c.close()


def set_slots(port: int, restaurant_id: str, slots: list[dict]):
    """Helper: set available slots on the mock server."""
    data = json.dumps({"restaurant_id": restaurant_id, "slots": slots}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/_test/set_slots",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req)


def set_payment(port: int, succeeds: bool):
    """Helper: control whether payment succeeds."""
    data = json.dumps({"succeeds": succeeds}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/_test/set_payment",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req)


def cancel_slot(port: int, restaurant_id: str, date: str, time: str):
    """Helper: simulate a cancellation (make a slot available again)."""
    data = json.dumps({"restaurant_id": restaurant_id, "date": date, "time": time}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/_test/cancel_slot",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req)


def get_server_state(port: int) -> dict:
    """Helper: get current server state."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}/_test/state")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())
