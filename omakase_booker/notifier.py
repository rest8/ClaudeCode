"""Simple notification system for booking results."""

import logging
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def notify_success(restaurant_name: str, date: str, time: str):
    """Log a successful booking notification."""
    msg = f"予約成功！ {restaurant_name} - {date} {time}"
    logger.info(msg)
    print(f"\n{'='*50}")
    print(f"  ✅ {msg}")
    print(f"{'='*50}\n")


def notify_failure(restaurant_name: str, reason: str):
    """Log a failed booking notification."""
    msg = f"予約失敗: {restaurant_name} - {reason}"
    logger.warning(msg)
    print(f"\n{'='*50}")
    print(f"  ❌ {msg}")
    print(f"{'='*50}\n")


def send_email_notification(
    smtp_host: str,
    smtp_port: int,
    sender: str,
    password: str,
    recipient: str,
    subject: str,
    body: str,
):
    """Send an email notification (optional, configure if needed)."""
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = recipient

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        logger.info("Email notification sent to %s", recipient)
    except Exception:
        logger.exception("Failed to send email notification")
