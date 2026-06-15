"""
מלאי — דוח מלאי קיים, ניהול פריטים, וסנכרון מ-SUMIT
Inventory routes.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..dependencies import get_db, get_current_org_id
from ...services.inventory_service import InventoryService

router = APIRouter(prefix="/inventory", tags=["Inventory"])


class InventoryItemRequest(BaseModel):
    id: Optional[int] = None
    sku: Optional[str] = None
    name: str
    unit: Optional[str] = "unit"
    quantity: Optional[float] = 0
    unit_cost: Optional[float] = 0
    unit_price: Optional[float] = 0
    reorder_level: Optional[float] = 0


@router.get("/report")
async def get_inventory_report(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """דוח מלאי קיים: פריטים, שערוך, מלאי נמוך/אזל."""
    service = InventoryService(db, organization_id=org_id)
    return {"status": "success", "data": service.get_report()}


@router.post("/items")
async def upsert_inventory_item(
    request: InventoryItemRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """יצירה/עדכון פריט מלאי (כולל עלות וסף התראה)."""
    service = InventoryService(db, organization_id=org_id)
    item = service.upsert_item(request.model_dump(exclude_none=True))
    return {"status": "success", "data": {"id": item.id, "name": item.name}}


@router.post("/sync")
async def sync_inventory(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """סנכרון מלאי מ-SUMIT."""
    service = InventoryService(db, organization_id=org_id)
    try:
        result = await service.sync_from_sumit()
    except ValueError as exc:
        # תצורה חסרה (אין חיבור SUMIT)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # כשל בתקשורת/אימות מול SUMIT
        raise HTTPException(status_code=502, detail=f"סנכרון SUMIT נכשל: {exc}")
    return {"status": "success", "data": result}
