"""Authentication handling for iFOREX."""

from playwright.sync_api import Page
from loguru import logger

from .config import Config


def login(page: Page, config: Config) -> bool:
    """Log in to iFOREX web platform.

    Returns True on success, False on failure.
    The actual selectors may need adjustment based on iFOREX's current UI.
    """
    logger.info("Navigating to login page: {}", config.login_url)
    page.goto(config.login_url, wait_until="networkidle", timeout=30000)

    try:
        # Wait for the login form to appear
        page.wait_for_selector('input[type="email"], input[name="email"], #email', timeout=10000)

        # Fill credentials — selectors are best-guesses and may need updating
        email_input = page.locator('input[type="email"], input[name="email"], #email').first
        email_input.fill(config.email)

        password_input = page.locator('input[type="password"], input[name="password"], #password').first
        password_input.fill(config.password)

        # Click login button
        login_btn = page.locator('button[type="submit"], input[type="submit"], .login-button').first
        login_btn.click()

        # Wait for navigation after login
        page.wait_for_load_state("networkidle", timeout=30000)
        logger.info("Login submitted. Checking result...")

        # Verify login succeeded by checking for trading UI elements or URL change
        page.wait_for_url("**/trading**", timeout=15000)
        logger.info("Login successful — trading platform loaded.")
        return True

    except Exception as e:
        logger.error("Login failed: {}", e)
        page.screenshot(path="login_error.png")
        return False
