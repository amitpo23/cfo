"""Fixed assets & depreciation routes (רכוש קבוע ופחת) — Wave 2 addition E.

Organization-scoped. Depreciation output is derived/draft (see
services/depreciation_service.py) — decision support for an accountant.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...database import get_db_session
from ..dependencies import get_current_org_id
from ...services import depreciation_service as svc

router = APIRouter(prefix="/assets", tags=["Fixed Assets & Depreciation"])


def _parse_date(raw: str, field: str) -> date:
    try:
        return datetime.fromisoformat(raw).date()
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field} לא תקין (YYYY-MM-DD)")


@router.post("")
def create_asset(
    payload: dict = Body(...),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    name = (payload.get("name") or "").strip()
    category = (payload.get("category") or "").strip()
    if not name or not category:
        raise HTTPException(status_code=400, detail="name ו-category נדרשים")
    purchase_date = _parse_date(payload.get("purchase_date"), "purchase_date")
    asset = svc.create_asset(
        db, org_id, name=name, category=category,
        cost=payload.get("cost") or 0, purchase_date=purchase_date,
        depreciation_rate=payload.get("depreciation_rate"),
        salvage_value=payload.get("salvage_value") or 0,
        notes=payload.get("notes"),
    )
    return svc.asset_to_dict(asset)


@router.get("")
def list_assets(
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return {"assets": [svc.asset_to_dict(a) for a in svc.list_assets(db, org_id)]}


@router.get("/depreciation/annual")
def annual_depreciation(
    year: int = Query(...),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    total = svc.annual_depreciation_total(db, org_id, year)
    return {"year": year, "total_depreciation": total, "derived": True}


@router.get("/form-1342")
def form_1342(
    year: int = Query(...),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return svc.form_1342_draft(db, org_id, year)


@router.get("/{asset_id}/schedule")
def asset_schedule(
    asset_id: int,
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    asset = svc.get_asset(db, org_id, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="נכס קבוע לא נמצא")
    return {"asset": svc.asset_to_dict(asset), "schedule": svc.depreciation_schedule(asset)}


@router.delete("/{asset_id}")
def delete_asset(
    asset_id: int,
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    try:
        svc.delete_asset(db, org_id, asset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "deleted", "id": asset_id}
