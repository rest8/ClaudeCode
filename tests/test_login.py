"""Test login flow against mock server."""

import pytest


@pytest.mark.asyncio
async def test_login_success(client):
    """Verify login succeeds with correct credentials."""
    # client fixture already logs in; if we get here, login worked
    page = client._page
    assert "sign_in" not in page.url


@pytest.mark.asyncio
async def test_login_failure(config, base_url, monkeypatch):
    """Verify login fails with wrong credentials."""
    import omakase_booker.omakase_client as client_mod
    from omakase_booker.omakase_client import OmakaseClient, OmakaseBookingError

    monkeypatch.setattr(client_mod, "OMAKASE_BASE_URL", base_url)
    monkeypatch.setattr(client_mod, "LOGIN_URL", f"{base_url}/users/sign_in")

    config.omakase_password = "wrong_password"
    c = OmakaseClient(config)

    with pytest.raises(OmakaseBookingError, match="Login failed"):
        await c.start()

    await c.close()
