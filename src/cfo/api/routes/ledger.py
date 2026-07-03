"""Derived double-entry ledger routes (מנוע הנהלת חשבונות כפולה).

Organization-scoped. All output is DERIVED from synced documents (not SUMIT's
official books) and labeled accordingly. See services/ledger_service.py.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from ...database import get_db_session
from ..dependencies import get_current_org_id
from ...services import ledger_service

router = APIRouter()


def _period(year: Optional[int], month: Optional[int]) -> tuple[Optional[date], Optional[date]]:
    if not year:
        return None, None
    if month:
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        from datetime import timedelta
        return start, end - timedelta(days=1)
    return date(year, 1, 1), date(year, 12, 31)


@router.get("/ledger/journal")
def get_journal(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    start, end = _period(year, month)
    entries = ledger_service.build_journal(db, org_id, start=start, end=end)
    return {
        "entries": [e.as_dict() for e in entries],
        "count": len(entries),
        "all_balanced": all(e.balanced for e in entries),
        "derived": True,
        "disclaimer": ledger_service.DISCLAIMER,
    }


@router.post("/ledger/entries")
def post_manual_entry(
    payload: dict = Body(...),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """פקודת יומן ידנית (התאמת רו"ח). גוף: {entry_date, memo, lines:[{account,debit,credit,description}]}."""
    from fastapi import HTTPException
    raw_date = payload.get("entry_date")
    try:
        entry_date = date.fromisoformat(raw_date) if raw_date else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="entry_date לא תקין (YYYY-MM-DD)")
    try:
        row = ledger_service.add_manual_entry(
            db, org_id, entry_date=entry_date,
            memo=payload.get("memo", ""), lines=payload.get("lines", []),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return {"id": row.id, "status": "created", "derived": True,
            "disclaimer": ledger_service.DISCLAIMER}


@router.get("/ledger/trial-balance")
def get_trial_balance(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    start, end = _period(year, month)
    return ledger_service.trial_balance(db, org_id, start=start, end=end)


@router.get("/ledger/account/{account_code}")
def get_general_ledger(
    account_code: str,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    start, end = _period(year, month)
    return ledger_service.general_ledger(db, org_id, account_code, start=start, end=end)


@router.get("/ledger/balance-sheet")
def get_balance_sheet(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    start, end = _period(year, month)
    return ledger_service.balance_sheet(db, org_id, start=start, end=end)


@router.get("/ledger/opening-balances")
def get_opening_balances(
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return ledger_service.get_opening_balances(db, org_id)


@router.post("/ledger/opening-balances")
def set_opening_balances(
    payload: dict = Body(...),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Set opening balances. Body: {as_of: 'YYYY-MM-DD', balances: [{account, debit, credit}]}."""
    from datetime import datetime, timezone
    as_of_raw = payload.get("as_of")
    as_of = datetime.fromisoformat(as_of_raw).date() if as_of_raw else datetime.now(timezone.utc).date()
    return ledger_service.set_opening_balances(db, org_id, as_of, payload.get("balances", []))


@router.get("/ledger/chart")
def get_chart(org_id: int = Depends(get_current_org_id)):
    """The fixed Israeli chart of accounts the postings use."""
    return {"chart": [{"account": k, **v} for k, v in ledger_service.CHART.items()]}
