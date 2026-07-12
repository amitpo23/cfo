"""תכנון תזכורות גבייה מחשבוניות אמיתיות (ללא שליחה — ראו dispatch).

מודל הקצב (ספק הבעלים, 2026-07-12):
- ``pre_due``: תזכורת אחת יום לפני מועד התשלום.
- ``overdue``: הודעה יומית מהיום הראשון לאיחור ועד התשלום, עם מספר ימי
  האיחור המעודכן ("אתה מאחר ב-N ימים בהתאם להסכם ותנאי התשלום").
- תשלום שמזוהה — יתרת חשבונית שנסגרה (קבלה ב-SUMIT) או תנועת בנק נכנסת
  שהותאמה לחשבונית (Open Finance) — עוצר את התזכורות מיידית.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from ..models import BankTransaction, Contact, Invoice, CollectionReminder
from .ar_service import AccountsReceivableService

OVERDUE_STATUSES = ["sent", "partially_paid", "overdue"]

# ברירת המחדל 20 שעות: ריצת cron יומית קבועה לא תיחסם על ידי ריצה של אתמול
# (24h מדויקות היו מדלגות על יום בגלל סטיות דקות), אבל ריצה ידנית באותו יום כן.
DAILY_COOLDOWN_HOURS = 20

_LOCAL_TEMPLATES = {
    "pre_due": """
שלום {customer_name},

תזכורת ידידותית: מועד התשלום של חשבונית {invoice_numbers} על סך ₪{amount:,.0f} חל מחר, בהתאם להסכם ותנאי התשלום.

בברכה,
{company_name}
""",
    "overdue": """
שלום {customer_name},

אתה מאחר {days_phrase} בתשלום חשבונית {invoice_numbers} על סך ₪{amount:,.0f}, בהתאם להסכם ותנאי התשלום.
נודה על הסדרת התשלום.

בברכה,
{company_name}
""",
}


def _days_phrase(days: int) -> str:
    if days == 1:
        return "ביום אחד"
    return f"ב-{days} ימים"


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


class CollectionService:
    def __init__(self, db: Session, org_id: int):
        self.db = db
        self.org_id = org_id
        templates = dict(AccountsReceivableService(db, org_id).reminder_templates)
        templates.update(_LOCAL_TEMPLATES)
        self._templates = templates

    def plan_reminders(self, today: date,
                       cooldown_hours: int = DAILY_COOLDOWN_HOURS) -> List[PlannedReminder]:
        planned: List[PlannedReminder] = []
        planned += self._plan(today, "overdue", Invoice.due_date < today, cooldown_hours)
        planned += self._plan(today, "pre_due",
                              Invoice.due_date == today + timedelta(days=1), cooldown_hours)
        return planned

    def _plan(self, today: date, rtype: str, due_filter,
              cooldown_hours: int) -> List[PlannedReminder]:
        rows = self.db.query(Invoice, Contact).join(
            Contact, Invoice.contact_id == Contact.id
        ).filter(
            Invoice.organization_id == self.org_id,
            Invoice.due_date.isnot(None),
            due_filter,
            Invoice.status.in_(OVERDUE_STATUSES),
            Invoice.balance > 0,
        ).all()
        rows = [(inv, c) for inv, c in rows if not self._bank_payment_detected(inv)]

        by_contact: dict = {}
        for inv, contact in rows:
            g = by_contact.setdefault(contact.id, {"contact": contact, "invoices": []})
            g["invoices"].append(inv)

        planned: List[PlannedReminder] = []
        for cid, g in by_contact.items():
            contact = g["contact"]
            invoices = g["invoices"]
            days = max((today - inv.due_date).days for inv in invoices)
            if self._recently_sent(cid, rtype, cooldown_hours):
                continue
            total = float(sum(inv.balance or 0 for inv in invoices))
            numbers = [inv.invoice_number or f"#{inv.id}" for inv in invoices]
            message = self._render(rtype, contact.name, numbers, total, days)
            planned.append(PlannedReminder(
                contact_id=cid, contact_name=contact.name, email=contact.email,
                phone=contact.phone, invoice_numbers=numbers, total_amount=total,
                days_overdue=max(days, 0), reminder_type=rtype, message=message,
            ))
        return planned

    def _bank_payment_detected(self, invoice: Invoice) -> bool:
        """תקבול בבנק שהותאם לחשבונית עוצר גבייה גם לפני שהקבלה נרשמה ב-SUMIT."""
        return self.db.query(BankTransaction.id).filter(
            BankTransaction.organization_id == self.org_id,
            BankTransaction.matched_entity_type == "invoice",
            BankTransaction.matched_entity_id == invoice.id,
            BankTransaction.amount > 0,
        ).first() is not None

    def _recently_sent(self, contact_id: int, rtype: str, cooldown_hours: int) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)
        return self.db.query(CollectionReminder).filter(
            CollectionReminder.organization_id == self.org_id,
            CollectionReminder.contact_id == contact_id,
            CollectionReminder.reminder_type == rtype,
            CollectionReminder.sent_at >= cutoff,
            CollectionReminder.status == "sent",
        ).first() is not None

    def _render(self, rtype, name, numbers, amount, days_overdue) -> str:
        tmpl = self._templates.get(rtype, self._templates["overdue"])
        return tmpl.format(
            customer_name=name, invoice_numbers=", ".join(numbers),
            amount=amount, days_overdue=days_overdue,
            days_phrase=_days_phrase(days_overdue),
            due_date="", company_name=self._company_name(),
        )

    def _company_name(self) -> str:
        from ..models import Organization
        org = self.db.get(Organization, self.org_id)
        return org.name if org else ""


async def dispatch_reminders(db, org_id, planned, sms_sender, email_sender,
                             sms_sender_name=None) -> dict:
    from decimal import Decimal
    summary = {"sms_sent": 0, "email_sent": 0, "failed": 0}
    for p in planned:
        for channel, target, send in (
            ("sms", p.phone, sms_sender),
            ("email", p.email, email_sender),
        ):
            if not target:
                continue
            try:
                if channel == "sms":
                    ok = await send(target, p.message)
                else:
                    ok = await send(target, "תזכורת תשלום", p.message)
            except Exception as exc:  # record failure, never crash the batch
                _record(db, org_id, p, channel, "failed", str(exc))
                summary["failed"] += 1
                continue
            if ok:
                _record(db, org_id, p, channel, "sent", None)
                summary["sms_sent" if channel == "sms" else "email_sent"] += 1
            else:
                _record(db, org_id, p, channel, "failed", "sender returned False")
                summary["failed"] += 1
    db.commit()
    return summary


def _record(db, org_id, p, channel, status, error):
    from decimal import Decimal
    db.add(CollectionReminder(
        organization_id=org_id, contact_id=p.contact_id,
        invoice_numbers=", ".join(p.invoice_numbers), reminder_type=p.reminder_type,
        channel=channel, amount=Decimal(str(p.total_amount)), days_overdue=p.days_overdue,
        status=status, error=error, sent_at=datetime.now(timezone.utc),
    ))
