"""Configuration for Omakase auto-booking."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class RestaurantInfo:
    """Restaurant metadata scraped from Omakase listings."""

    name: str
    url: str  # e.g. "https://omakase.in/r/abcdef123"
    area: str = ""  # e.g. "東京", "大阪"
    genre: str = ""  # e.g. "鮨", "天ぷら"
    price_range: str = ""  # e.g. "¥30,000〜"
    rating: str = ""
    image_url: str = ""
    description: str = ""


@dataclass
class RestaurantTarget:
    """A restaurant to monitor and book."""

    name: str
    omakase_url: str  # e.g. "https://omakase.in/r/abcdef123"
    party_size: int = 2
    preferred_times: list[str] = field(default_factory=lambda: ["18:00", "19:00", "20:00"])
    course_keyword: str | None = None  # Keyword to match a specific course
    booking_mode: str = "first_come"  # "first_come" or "lottery"
    # User-specified candidate dates (YYYY-MM-DD). If empty, use Google Calendar.
    candidate_dates: list[str] = field(default_factory=list)
    # Cancellation waitlist: monitor for newly available slots even after initial booking attempt
    watch_cancellations: bool = True


@dataclass
class Config:
    """Application configuration."""

    # Google Calendar
    google_credentials_path: str = "credentials.json"
    google_token_path: str = "token.json"
    calendar_id: str = "primary"

    # Omakase account
    omakase_email: str = ""
    omakase_password: str = ""

    # Booking preferences
    target_restaurants: list[RestaurantTarget] = field(default_factory=list)
    booking_months_ahead: int = 2  # How far ahead to look for slots
    min_free_hours: float = 3.0  # Minimum free block (hours) to consider bookable

    # Scheduling
    check_interval_seconds: int = 30  # How often to poll for new slots
    fast_poll_interval_seconds: float = 0.5  # Interval during fast-polling near open time
    fast_poll_window_minutes: int = 5  # Minutes before/after open time for fast polling
    continuous_mode: bool = True  # Always-on: keep monitoring for cancellations
    cancellation_check_interval_seconds: int = 300  # How often to check for cancellations (5 min)

    # Google Chat approval
    gchat_webhook_url: str = ""  # Google Chat incoming webhook URL
    gchat_callback_url: str = ""  # Public URL for approval callback (e.g. ngrok)
    approval_timeout_seconds: int = 300  # Max seconds to wait for approval (5 min)
    approval_fee_per_person: int = 390  # Seat reservation fee per person (JPY)

    # Browser
    headless: bool = True
    browser_timeout_ms: int = 30000
    dry_run: bool = False  # Dry-run mode: skip actual payment
    block_unnecessary_resources: bool = True  # Block images/fonts/CSS for faster loading
    max_concurrent_checks: int = 3  # Max restaurants to check in parallel

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        path = Path(path)
        with path.open() as f:
            data = yaml.safe_load(f)

        restaurants = [
            RestaurantTarget(**r) for r in data.pop("target_restaurants", [])
        ]
        return cls(target_restaurants=restaurants, **data)
