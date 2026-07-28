"""שליחת מייל דרך SMTP. מושבת בשקט (False) כשאין קונפיג — לא ממציא הצלחה."""
import asyncio
import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Sequence

logger = logging.getLogger(__name__)

# צרופה: (שם קובץ, בייטים, mime subtype). ברירת המחדל של subtype היא
# octet-stream; ל-xlsx נעביר את הטיפוס המלא של OpenXML.
Attachment = tuple[str, bytes, str]

# תקרת גודל למייל אחד. מעליה ספקי SMTP דוחים או חותכים בשקט — עדיף
# להיכשל במפורש מאשר לדווח "נשלח" על מייל שלא הגיע.
MAX_TOTAL_ATTACHMENT_BYTES = 15 * 1024 * 1024


async def send_email_smtp(
    to: str,
    subject: str,
    body: str,
    settings,
    *,
    attachments: Optional[Sequence[Attachment]] = None,
) -> bool:
    """שולח מייל; מחזיר True רק כשהשליחה בוצעה בפועל.

    ``attachments`` הוא רצף של ``(filename, content, mime_subtype)``. בלעדיו
    ההודעה נשארת MIMEText פשוט — בדיוק כפי שהייתה לפני תמיכת הצרופות, כך
    ששלושת הקוראים הקיימים (cron גבייה, גבייה ידנית, בריף הבוקר) אינם
    מושפעים.
    """
    if not (settings.smtp_host and settings.smtp_from):
        logger.warning("SMTP not configured; skipping email to %s", to)
        return False

    if attachments:
        total = sum(len(content) for _, content, _ in attachments)
        if total > MAX_TOTAL_ATTACHMENT_BYTES:
            logger.warning(
                "attachments too large (%d bytes) for %s; refusing to send", total, to
            )
            return False

    def _send() -> bool:
        if attachments:
            msg = MIMEMultipart()
            msg.attach(MIMEText(body, "plain", "utf-8"))
            for filename, content, subtype in attachments:
                part = MIMEApplication(content, _subtype=subtype)
                part.add_header("Content-Disposition", "attachment", filename=filename)
                msg.attach(part)
        else:
            msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = to
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
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
