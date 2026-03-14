"""Test dry-run mode: reserve succeeds but payment is skipped."""

import pytest
from datetime import datetime, timedelta

from tests.conftest import get_server_state


@pytest.mark.asyncio
async def test_dry_run_skips_payment(client, mock_port, config):
    """In dry-run mode, reserve_slot works but complete_payment is a no-op."""
    config.dry_run = True
    restaurant = config.target_restaurants[0]
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    # Reserve works normally
    reserved = await client.reserve_slot(restaurant, tomorrow, "18:00")
    assert reserved is True

    # Payment returns True but doesn't actually charge
    paid = await client.complete_payment()
    assert paid is True

    # Server should NOT have a completed booking (payment was skipped)
    server_state = get_server_state(mock_port)
    assert len(server_state["completed_bookings"]) == 0


@pytest.mark.asyncio
async def test_non_dry_run_completes_payment(client, mock_port, config):
    """Without dry-run, payment actually completes."""
    config.dry_run = False
    restaurant = config.target_restaurants[0]
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    reserved = await client.reserve_slot(restaurant, tomorrow, "18:00")
    assert reserved is True

    paid = await client.complete_payment()
    assert paid is True

    # Server should have a completed booking
    server_state = get_server_state(mock_port)
    assert len(server_state["completed_bookings"]) == 1
