"""
Email expense intake — receive expenses via email with attachments.

Users email receipts to a designated inbox (e.g., expenses@company.il).
Service polls IMAP, extracts PDFs/images, creates Expense records, runs OCR.
"""
from __future__ import annotations

import logging
from email.mime.text import MIMEText
from typing import Any

from sqlalchemy.orm import Session

from ..models import Expense

logger = logging.getLogger(__name__)


class EmailExpenseIntakeService:
    """Poll email inbox for expense submissions."""

    def __init__(
        self,
        db: Session,
        organization_id: int,
        imap_host: str,
        imap_port: int,
        email_address: str,
        email_password: str,
    ):
        self.db = db
        self.organization_id = organization_id
        self.imap_host = imap_host
        self.imap_port = imap_port
        self.email_address = email_address
        self.email_password = email_password
        self._imap_client = None

    async def poll_inbox(
        self,
        folder: str = "INBOX",
        unseen_only: bool = True,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Poll IMAP inbox for new expense emails with attachments.

        Args:
            folder: IMAP folder (default INBOX)
            unseen_only: Only process unread messages
            limit: Max emails to process per run

        Returns:
            Summary: {processed, created, errors, results}
        """
        try:
            import imaplib
        except ImportError:
            raise ValueError("imap support requires Python imaplib (stdlib)")

        try:
            client = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
            client.login(self.email_address, self.email_password)
            client.select(folder)

            # Search for unseen or all emails
            search_query = "UNSEEN" if unseen_only else "ALL"
            _, message_nums = client.search(None, search_query)
            msg_ids = message_nums[0].split()[-limit:]

            results = []
            created = 0
            errors = 0

            for msg_id in msg_ids:
                try:
                    _, msg_data = client.fetch(msg_id, "(BODY.PEEK[])")
                    email_body = msg_data[0][1]
                    result = await self._process_email(email_body)
                    results.append(result)
                    created += result.get("created", 0)
                    errors += result.get("errors", 0)
                    # Keep partial failures unread. Replay deduplicates saved siblings.
                    if not result.get("errors"):
                        client.store(msg_id, "+FLAGS", "\\Seen")
                except Exception as exc:
                    logger.exception("Failed to process email %s: %s", msg_id, exc)
                    errors += 1
                    results.append({"msg_id": msg_id.decode(), "status": "error", "error": str(exc)})

            client.close()
            client.logout()

            return {
                "processed": len(msg_ids),
                "created": created,
                "errors": errors,
                "results": results,
            }
        except Exception as exc:
            logger.error("IMAP connection failed: %s", exc)
            return {
                "error": str(exc),
                "processed": 0,
                "created": 0,
                "errors": 1,
            }

    async def _process_email(self, email_bytes: bytes) -> dict[str, Any]:
        """Preserve every relevant attachment; no OCR or invented expense amounts."""
        import email
        from .document_intake import DocumentIntakeService, MEDIA_TYPES

        msg = email.message_from_bytes(email_bytes)
        sender = email.utils.parseaddr(msg.get("From", ""))[1]
        service = DocumentIntakeService(self.db, self.organization_id)
        results = []
        for index, part in enumerate(msg.walk()):
            if part.is_multipart():
                continue
            filename = part.get_filename() or f"attachment-{index}"
            media_type = part.get_content_type()
            if media_type == 'application/octet-stream':
                import mimetypes
                media_type = mimetypes.guess_type(filename)[0]
            if media_type not in MEDIA_TYPES:
                continue
            try:
                result = service.receive(part.get_payload(decode=True) or b'',
                    media_type=media_type, source='email', filename=filename,
                    source_reference=f"{msg.get('Message-ID', '')}:{index}")
                results.append(dict(result, filename=filename))
            except Exception:
                self.db.rollback()
                logger.exception("Attachment intake failed")
                results.append({'filename': filename, 'status': 'error',
                    'error': 'Attachment could not be saved; retry this message'})
        created = sum(r['status'] == 'queued' for r in results)
        errors = sum(r['status'] == 'error' for r in results)
        return {'sender': sender, 'subject': msg.get('Subject', ''),
            'status': 'error' if errors else ('queued' if results else 'skipped'),
            'created': created, 'duplicates': sum(r['status'] == 'duplicate' for r in results),
            'errors': errors, 'attachments': len(results), 'results': results}

    async def send_confirmation(
        self,
        to_email: str,
        expense_id: int,
        status: str = "received",
    ) -> dict[str, Any]:
        """Send confirmation email to submitter."""
        try:
            import smtplib
        except ImportError:
            raise ValueError("SMTP support requires Python smtplib (stdlib)")

        exp = (
            self.db.query(Expense)
            .filter(
                Expense.organization_id == self.organization_id,
                Expense.id == expense_id,
            )
            .first()
        )
        if not exp:
            raise ValueError(f"Expense {expense_id} not found")

        msg = MIMEText(
            f"Your expense submission has been {status}.\n\n"
            f"Expense ID: {exp.id}\n"
            f"Status: {exp.status}\n"
            f"Amount: ₪{float(exp.total or 0):,.2f}\n"
            f"Date: {exp.expense_date}\n"
        )
        msg["Subject"] = f"Expense Submission {status.upper()}"
        msg["From"] = self.email_address
        msg["To"] = to_email

        try:
            # Note: Would require SMTP credentials in config
            # smtplib.SMTP_SSL(self.smtp_host, 465).send_message(msg)
            logger.info("Confirmation email prepared for %s (expense %s)", to_email, expense_id)
            return {"status": "prepared", "sent": False, "to": to_email}
        except Exception as exc:
            logger.error("Failed to send confirmation: %s", exc)
            return {"status": "error", "error": str(exc)}
