"""Read-only accounting event plane routes."""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...database import get_db_session
from ...services import accounting_event_service
from ..dependencies import get_current_org_id

router = APIRouter()


@router.get("/accounting-events")
def list_accounting_events(
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    event_type: Optional[str] = Query(None, pattern="^(invoice|bill|payment|expense|bank_transaction)$"),
    limit: int = Query(500, ge=1, le=1000),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return accounting_event_service.build_events(
        db,
        org_id,
        start=start,
        end=end,
        event_type=event_type,
        limit=limit,
    )
