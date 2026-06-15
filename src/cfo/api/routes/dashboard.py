"""
דשבורד מנהלים מאוחד
Executive dashboard routes.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..dependencies import get_db, get_current_org_id
from ...services.executive_dashboard_service import ExecutiveDashboardService
from ...services.fees_service import FeesService

router = APIRouter(prefix="/dashboard", tags=["Executive Dashboard"])


@router.get("/executive")
async def get_executive_dashboard(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """דשבורד מנהלים מאוחד — כל 8 הפאנלים של מצב העסק."""
    service = ExecutiveDashboardService(db, organization_id=org_id)
    return {"status": "success", "data": service.build(start_date, end_date)}


@router.get("/fees")
async def get_fees_report(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """דוח עמלות — בנק, סליקה/אשראי, וריבית הלוואות."""
    service = FeesService(db, organization_id=org_id)
    return {"status": "success", "data": service.get_fees_report(start_date, end_date)}
