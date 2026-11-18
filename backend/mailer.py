"""Outgoing email for one-time codes (SPEC-079).

Gmail SMTP with an app password from ``SMTP_USERNAME``／``SMTP_PASSWORD``. The app
holds one ``Mailer`` (or ``None`` when email is not configured) on ``app.state.mailer``
so tests inject a fake and no test ever sends real mail. Logs never contain the
recipient, the code or the credentials.
"""

import logging
import smtplib
from collections.abc import Callable
from email.message import EmailMessage
from email.utils import formataddr

from backend.settings import Settings

logger = logging.getLogger("running_shoes.mail")

SENDER_NAME = "跑鞋追蹤"
Mailer = Callable[[str, str, str], None]


class MailError(Exception):
    """Sending failed; the message is safe to show to users."""


def smtp_mailer(settings: Settings) -> Mailer | None:
    """A sender bound to the configured SMTP account, or None when email is off."""
    if not settings.mail_enabled:
        return None
    username = settings.smtp_username or ""
    password = settings.smtp_password or ""

    def send(to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = formataddr((SENDER_NAME, username))
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as client:
                client.starttls()
                client.login(username, password)
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            logger.warning("email send failed: %s", type(error).__name__)
            raise MailError("寄信失敗，請稍後再試") from None

    return send
