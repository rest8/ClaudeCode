"""Test availability checking and open time detection against mock server."""

import pytest

from tests.conftest import set_slots


@pytest.mark.asyncio
async def test_check_availability_finds_slots(client, mock_port, config):
    """Verify check_availability returns available slots."""
    restaurant = config.target_restaurants[0]
    slots = await client.check_availability(restaurant)

    assert len(slots) >= 1
    assert all("date" in s or "time" in s for s in slots)


@pytest.mark.asyncio
async def test_check_availability_no_slots(client, mock_port, config, base_url):
    """Verify empty slots when none are available."""
    set_slots(mock_port, "rest001", [])

    restaurant = config.target_restaurants[0]
    slots = await client.check_availability(restaurant)

    assert len(slots) == 0


@pytest.mark.asyncio
async def test_detect_open_time(client, config):
    """Verify open time detection from restaurant page."""
    restaurant = config.target_restaurants[0]
    open_time = await client.detect_reservation_open_time(restaurant)

    assert open_time is not None
    assert "2026" in open_time
    assert "10:00" in open_time


@pytest.mark.asyncio
async def test_scrape_cancellation_policy(client, config):
    """Verify cancellation policy scraping."""
    restaurant = config.target_restaurants[0]
    policy = await client.scrape_cancellation_policy(restaurant)

    assert "キャンセル" in policy
    assert "50%" in policy or "100%" in policy
