"""Per-business capability menu route (תפריט יכולות לעסק). Organization-scoped."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database import get_db_session
from ..dependencies import get_current_org_id
from ...services import business_menu

router = APIRouter()


@router.get("/business/menu")
def get_business_menu(
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """The full capability catalog for this business, each with live status."""
    return business_menu.build_menu(db, org_id)
