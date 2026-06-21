"""Annual tax-return DRAFT routes (1301 / 1214). Organization-scoped, draft-only."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...database import get_db_session
from ..dependencies import get_current_org_id
from ...services import annual_report_service

router = APIRouter()


@router.get("/annual-reports/1301")
def report_1301(
    year: int = Query(...),
    credit_points: float = Query(2.25),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return annual_report_service.form_1301(db, org_id, year, credit_points=credit_points)


@router.get("/annual-reports/1214")
def report_1214(
    year: int = Query(...),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return annual_report_service.form_1214(db, org_id, year)
