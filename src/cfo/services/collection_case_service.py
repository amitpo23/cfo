"""מעקב מקרי גבייה ידניים — נפרד מהתזכורות האוטומטיות (collection_service.py).

מייצג את העבודה של אדם (הנהלת חשבונות/גבייה) שמתקשר/כותב ללקוח, רושם מה קרה,
ועוקב אחרי הבטחת תשלום עד שהחוב נסגר. לעולם לא נוגע במסמכי SUMIT — עוקב בלבד.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from .collection_service import OVERDUE_STATUSES

# outcome -> status transition. Ambiguous/no-progress outcomes (e.g. no_answer)
# intentionally leave status unchanged — only a real signal advances it.
_OUTCOME_STATUS = {
    "promised": "promised",
    "paid": "paid",
    "escalate": "escalated",
}


def open_cases_for_overdue(db: Session, org_id: int, today: date, days_threshold: int = 30) -> list:
    """Open a new case per contact with invoices overdue by >= days_threshold days,
    unless that contact already has an open/promised case (idempotent — safe to
    call repeatedly, e.g. from a daily job)."""
    from ..models import Contact, Invoice, CollectionCase

    cutoff = today - timedelta(days=days_threshold)
    rows = db.query(Invoice, Contact).join(
        Contact, Invoice.contact_id == Contact.id
    ).filter(
        Invoice.organization_id == org_id,
        Invoice.due_date.isnot(None),
        Invoice.due_date <= cutoff,
        Invoice.status.in_(OVERDUE_STATUSES),
        Invoice.balance > 0,
    ).all()

    by_contact: dict = {}
    for inv, contact in rows:
        g = by_contact.setdefault(contact.id, [])
        g.append(inv.id)

    opened = []
    for contact_id, invoice_ids in by_contact.items():
        existing = db.query(CollectionCase).filter(
            CollectionCase.organization_id == org_id,
            CollectionCase.contact_id == contact_id,
            CollectionCase.status.in_(["open", "promised"]),
        ).first()
        if existing:
            continue
        case = CollectionCase(
            organization_id=org_id, contact_id=contact_id,
            invoice_ids=invoice_ids, status="open", attempts=[],
        )
        db.add(case)
        opened.append(case)
    db.commit()
    return opened


def log_attempt(db: Session, org_id: int, case_id: int, *, channel: str, outcome: str,
                notes: str = "", promise_date: Optional[date] = None) -> Any:
    """Record a collection attempt and advance status when the outcome signals
    progress (promised/paid/escalate). Any other outcome (e.g. no_answer,
    refused) is logged but leaves status unchanged — no silent status jump."""
    from ..models import CollectionCase

    case = db.query(CollectionCase).filter(
        CollectionCase.organization_id == org_id, CollectionCase.id == case_id,
    ).first()
    if not case:
        raise ValueError(f"Collection case {case_id} not found")

    attempts = list(case.attempts or [])
    attempts.append({
        "date": datetime.now(timezone.utc).isoformat(),
        "channel": channel,
        "outcome": outcome,
        "notes": notes,
    })
    case.attempts = attempts

    new_status = _OUTCOME_STATUS.get(outcome)
    if new_status:
        case.status = new_status
    if promise_date is not None:
        case.promise_date = promise_date

    db.commit()
    db.refresh(case)
    return case


def set_status(db: Session, org_id: int, case_id: int, status: str) -> Any:
    """Direct status override (manual correction — bypasses outcome inference)."""
    from ..models import CollectionCase

    valid = {"open", "promised", "paid", "escalated"}
    if status not in valid:
        raise ValueError(f"Invalid status '{status}' — must be one of {sorted(valid)}")

    case = db.query(CollectionCase).filter(
        CollectionCase.organization_id == org_id, CollectionCase.id == case_id,
    ).first()
    if not case:
        raise ValueError(f"Collection case {case_id} not found")

    case.status = status
    db.commit()
    db.refresh(case)
    return case


def list_cases(db: Session, org_id: int, status: Optional[str] = None) -> list:
    from ..models import CollectionCase

    q = db.query(CollectionCase).filter(CollectionCase.organization_id == org_id)
    if status:
        q = q.filter(CollectionCase.status == status)
    return q.order_by(CollectionCase.created_at.desc()).all()


def case_to_dict(case: Any) -> dict:
    return {
        "id": case.id,
        "contact_id": case.contact_id,
        "invoice_ids": case.invoice_ids or [],
        "status": case.status,
        "attempts": case.attempts or [],
        "promise_date": case.promise_date.isoformat() if case.promise_date else None,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
    }
