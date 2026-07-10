"""Manual collection-case routes (org-scoped). Separate from the automated
SMS/email reminders in financial_management.py's /collection/* routes."""
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ...database import get_db_session
from ...models import Contact, Invoice
from ..dependencies import get_current_org_id
from ...services import collection_case_service as svc

router = APIRouter(prefix="/collections", tags=["Collections"])


def _enrich(db: Session, org_id: int, cases: list) -> list[dict]:
    """Add a human-readable contact name/phone and the invoices' outstanding
    balance to each case dict — a bare contact_id/invoice_ids list isn't
    usable in a collections worklist."""
    dicts = [svc.case_to_dict(c) for c in cases]
    contact_ids = {d["contact_id"] for d in dicts}
    contacts = {
        c.id: c for c in db.query(Contact).filter(
            Contact.organization_id == org_id, Contact.id.in_(contact_ids)
        ).all()
    } if contact_ids else {}
    invoice_ids = {inv_id for d in dicts for inv_id in d["invoice_ids"]}
    balances = {
        inv.id: float(inv.balance or 0) for inv in db.query(Invoice).filter(
            Invoice.organization_id == org_id, Invoice.id.in_(invoice_ids)
        ).all()
    } if invoice_ids else {}
    for d in dicts:
        contact = contacts.get(d["contact_id"])
        d["contact_name"] = contact.name if contact else None
        d["contact_phone"] = contact.phone if contact else None
        d["contact_email"] = contact.email if contact else None
        d["total_balance"] = sum(balances.get(inv_id, 0) for inv_id in d["invoice_ids"])
    return dicts


@router.post("/open")
async def open_cases(
    days_threshold: int = 30,
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Open a case per contact with invoices overdue by >= days_threshold days.
    Idempotent — safe to call repeatedly (e.g. from a daily job)."""
    opened = svc.open_cases_for_overdue(db, org_id, date.today(), days_threshold=days_threshold)
    return {"opened": len(opened), "cases": _enrich(db, org_id, opened)}


@router.get("/cases")
async def list_cases(
    status: str = None,
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    cases = svc.list_cases(db, org_id, status=status)
    return {"cases": _enrich(db, org_id, cases)}


@router.post("/cases/{case_id}/attempt")
async def log_attempt(
    case_id: int,
    body: dict = Body(...),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    promise_date_raw = body.get("promise_date")
    promise_date = date.fromisoformat(promise_date_raw) if promise_date_raw else None
    try:
        case = svc.log_attempt(
            db, org_id, case_id,
            channel=body.get("channel", ""), outcome=body.get("outcome", ""),
            notes=body.get("notes", ""), promise_date=promise_date,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return _enrich(db, org_id, [case])[0]


@router.post("/cases/{case_id}/status")
async def set_status(
    case_id: int,
    body: dict = Body(...),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    try:
        case = svc.set_status(db, org_id, case_id, body.get("status", ""))
    except ValueError as exc:
        detail = str(exc)
        code = 404 if "not found" in detail else 400
        raise HTTPException(code, detail)
    return _enrich(db, org_id, [case])[0]
