"""Daily-cumulative intra-month report routes. Organization-scoped, derived."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...database import get_db_session
from ..dependencies import get_current_org_id
from ...services import daily_reports_service

router = APIRouter()


def _parse_as_of(as_of: Optional[str]) -> Optional[date]:
    if not as_of:
        return None
    try:
        return datetime.fromisoformat(as_of).date()
    except ValueError:
        return None


@router.get("/daily-reports/cumulative-pl")
def cumulative_pl(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return daily_reports_service.cumulative_pl(db, org_id, year, month)


@router.get("/daily-reports/ar-aging")
def ar_aging(
    as_of: Optional[str] = Query(None),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return daily_reports_service.ar_aging(db, org_id, _parse_as_of(as_of))


@router.get("/daily-reports/ap-aging")
def ap_aging(
    as_of: Optional[str] = Query(None),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return daily_reports_service.ap_aging(db, org_id, _parse_as_of(as_of))


@router.get("/daily-reports/vat")
def vat_report(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return daily_reports_service.vat_report(db, org_id, year, month)


@router.get("/daily-reports/pcn874")
def pcn874_file(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    company_vat_id: str = Query("000000000"),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """PCN874 detailed-VAT file (fixed-width draft) for the period."""
    from ...services import pcn874
    return pcn874.build_pcn874(db, org_id, year, month, company_vat_id=company_vat_id)


@router.get("/daily-reports/suppliers")
def suppliers(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return daily_reports_service.supplier_breakdown(db, org_id, year, month)


@router.get("/daily-reports/bank-expense-gap")
def bank_expense_gap(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """מנוע פער בנק-חשבוניות: לכל תנועת בנק יוצאת בחודש — האם יש כנגדה
    מסמך הנה"ח, וסיכום הפער הכולל (ראה services/bank_expense_gap.py)."""
    from ...services import bank_expense_gap as bank_expense_gap_service
    return bank_expense_gap_service.gap_report(db, org_id, year, month)
