"""תכנון תזכורות גבייה מחשבוניות באיחור אמיתיות (ללא שליחה — ראו dispatch)."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from ..models import Contact, Invoice, CollectionReminder
from .ar_service import AccountsReceivableService

OVERDUE_STATUSES = ["sent", "partially_paid", "overdue"]


@dataclass
class PlannedReminder:
    contact_id: int
    contact_name: str
    email: Optional[str]
    phone: Optional[str]
    invoice_numbers: List[str]
    total_amount: float
    days_overdue: int
    reminder_type: str
    message: str


def _reminder_type(days_overdue: int) -> str:
    if days_overdue >= 30:
        return "final"
    if days_overdue >= 14:
        return "second"
    return "first"


class CollectionService:
    def __init__(self, db: Session, org_id: int):
        self.db = db
        self.org_id = org_id
        self._templates = AccountsReceivableService(db, org_id).reminder_templates

    def plan_reminders(self, today: date, cooldown_days: int = 7) -> List[PlannedReminder]:
        rows = self.db.query(Invoice, Contact).join(
            Contact, Invoice.contact_id == Contact.id
        ).filter(
            Invoice.organization_id == self.org_id,
            Invoice.due_date.isnot(None),
            Invoice.due_date < today,
            Invoice.status.in_(OVERDUE_STATUSES),
            Invoice.balance > 0,
        ).all()

        # group by contact
        by_contact: dict = {}
        for inv, contact in rows:
            g = by_contact.setdefault(contact.id, {"contact": contact, "invoices": []})
            g["invoices"].append(inv)

        planned: List[PlannedReminder] = []
        for cid, g in by_contact.items():
            contact = g["contact"]
            invoices = g["invoices"]
            oldest_days = max((today - inv.due_date).days for inv in invoices)
            rtype = _reminder_type(oldest_days)
            if self._recently_sent(cid, rtype, today, cooldown_days):
                continue
            total = float(sum(inv.balance or 0 for inv in invoices))
            numbers = [inv.invoice_number or f"#{inv.id}" for inv in invoices]
            message = self._render(rtype, contact.name, numbers, total, oldest_days)
            planned.append(PlannedReminder(
                contact_id=cid, contact_name=contact.name, email=contact.email,
                phone=contact.phone, invoice_numbers=numbers, total_amount=total,
                days_overdue=oldest_days, reminder_type=rtype, message=message,
            ))
        return planned

    def _recently_sent(self, contact_id: int, rtype: str, today: date, cooldown_days: int) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(days=cooldown_days)
        return self.db.query(CollectionReminder).filter(
            CollectionReminder.organization_id == self.org_id,
            CollectionReminder.contact_id == contact_id,
            CollectionReminder.reminder_type == rtype,
            CollectionReminder.sent_at >= cutoff,
            CollectionReminder.status == "sent",
        ).first() is not None

    def _render(self, rtype, name, numbers, amount, days_overdue) -> str:
        tmpl = self._templates.get(rtype, self._templates["first"])
        return tmpl.format(
            customer_name=name, invoice_numbers=", ".join(numbers),
            amount=amount, days_overdue=days_overdue,
            due_date="", company_name=self._company_name(),
        )

    def _company_name(self) -> str:
        from ..models import Organization
        org = self.db.get(Organization, self.org_id)
        return org.name if org else ""
