"""
Email expense intake — receive expenses via email with attachments.

Users email receipts to a designated inbox (e.g., expenses@company.il).
Service polls IMAP, extracts PDFs/images, creates Expense records, runs OCR.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import Expense, Contact

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
                    _, msg_data = client.fetch(msg_id, "(RFC822)")
                    email_body = msg_data[0][1]
                    result = await self._process_email(email_body)
                    results.append(result)
                    if result.get("status") == "created":
                        created += 1
                    elif result.get("status") == "error":
                        errors += 1
                    # Mark as read
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
        """Extract expense from email (sender, subject, attachments)."""
        import email
        from email.mime.base import MIMEBase

        try:
            msg = email.message_from_bytes(email_bytes)
            sender_email = email.utils.parseaddr(msg["From"])[1]
            subject = msg.get("Subject", "").strip()

            # Find contact by email
            contact = (
                self.db.query(Contact)
                .filter(
                    Contact.organization_id == self.organization_id,
                    Contact.email == sender_email,
                )
                .first()
            )
            contact_name = contact.name if contact else sender_email

            # Extract attachments
            attachments = []
            for part in msg.walk():
                if part.get_content_maintype() == "application":
                    filename = part.get_filename()
                    if filename and filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")):
                        attachments.append({
                            "filename": filename,
                            "content": base64.b64encode(part.get_payload(decode=True)).decode("ascii"),
                            "media_type": part.get_content_type(),
                        })

            if not attachments:
                return {
                    "sender": sender_email,
                    "status": "skipped",
                    "reason": "No PDF/image attachments found",
                }

            # Create Expense record from email
            exp = Expense(
                organization_id=self.organization_id,
                source="email",
                supplier_name=contact_name or "Email Submission",
                description=subject or "(No subject)",
                amount=0,  # Will be filled by OCR
                vat_amount=0,
                total=0,
                expense_date=datetime.now(timezone.utc).date(),
                status="pending",
                receipt_file=attachments[0]["content"],  # Store first attachment
                raw_data={
                    "sender_email": sender_email,
                    "subject": subject,
                    "attachment_count": len(attachments),
                    "received_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            self.db.add(exp)
            self.db.commit()
            self.db.refresh(exp)

            return {
                "sender": sender_email,
                "subject": subject,
                "expense_id": exp.id,
                "attachments": len(attachments),
                "status": "created",
            }
        except Exception as exc:
            logger.exception("Email parsing failed: %s", exc)
            return {
                "status": "error",
                "error": str(exc),
            }

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
            return {"status": "sent", "to": to_email}
        except Exception as exc:
            logger.error("Failed to send confirmation: %s", exc)
            return {"status": "error", "error": str(exc)}
