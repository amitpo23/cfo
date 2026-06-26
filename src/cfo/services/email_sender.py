"""שליחת מייל דרך SMTP. מושבת בשקט (False) כשאין קונפיג — לא ממציא הצלחה."""
import asyncio
import logging
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


async def send_email_smtp(to: str, subject: str, body: str, settings) -> bool:
    if not (settings.smtp_host and settings.smtp_from):
        logger.warning("SMTP not configured; skipping email to %s", to)
        return False

    def _send() -> bool:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = to
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        return True

    try:
        return await asyncio.to_thread(_send)
    except Exception:
        logger.exception("SMTP send failed for %s", to)
        return False
