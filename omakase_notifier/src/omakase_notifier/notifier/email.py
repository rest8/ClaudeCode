from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from ..config import EmailConfig

log = logging.getLogger(__name__)


class EmailNotifier:
    def __init__(self, config: EmailConfig):
        self.config = config

    def send(self, to_address: str, subject: str, body: str) -> None:
        if not self.config.configured:
            raise RuntimeError("SMTP is not configured (see config.yaml)")
        msg = EmailMessage()
        msg["From"] = self.config.from_address
        msg["To"] = to_address
        msg["Subject"] = subject
        msg.set_content(body)

        with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            if self.config.use_starttls:
                smtp.starttls()
                smtp.ehlo()
            if self.config.smtp_user:
                smtp.login(self.config.smtp_user, self.config.smtp_password)
            smtp.send_message(msg)
        log.info("Email sent to %s: %s", to_address, subject)
