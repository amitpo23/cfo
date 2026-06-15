"""
שירות מלאי — דוח מלאי קיים, שערוך, והתראות מלאי נמוך
Inventory service: current-stock report, valuation, low-stock alerts, SUMIT sync.
"""
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import InventoryItem


class InventoryService:
    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id

    def _items(self) -> List[InventoryItem]:
        return (
            self.db.query(InventoryItem)
            .filter(
                InventoryItem.organization_id == self.organization_id,
                InventoryItem.is_active == True,  # noqa: E712
            )
            .order_by(InventoryItem.name)
            .all()
        )

    def get_report(self) -> Dict:
        """דוח מלאי קיים: פריטים, שערוך, ומלאי נמוך/אזל."""
        items = self._items()
        rows = []
        total_value = Decimal("0")
        total_units = Decimal("0")
        low_stock = 0
        out_of_stock = 0

        for it in items:
            qty = Decimal(str(it.quantity or 0))
            cost = Decimal(str(it.unit_cost or 0))
            reorder = Decimal(str(it.reorder_level or 0))
            value = qty * cost
            total_value += value
            total_units += qty

            is_out = qty <= 0
            is_low = (not is_out) and reorder > 0 and qty <= reorder
            if is_out:
                out_of_stock += 1
            if is_low:
                low_stock += 1

            rows.append({
                "id": it.id,
                "sku": it.sku,
                "name": it.name,
                "quantity": float(qty),
                "unit": it.unit,
                "unit_cost": float(cost),
                "unit_price": float(it.unit_price or 0),
                "reorder_level": float(reorder),
                "value": float(value),
                "status": "out_of_stock" if is_out else ("low" if is_low else "ok"),
                "source": it.source,
                "last_updated": it.last_updated.isoformat() if it.last_updated else None,
            })

        return {
            "items": rows,
            "summary": {
                "total_items": len(rows),
                "total_units": float(total_units),
                "total_value": float(total_value),
                "low_stock_count": low_stock,
                "out_of_stock_count": out_of_stock,
            },
        }

    def upsert_item(self, data: Dict) -> InventoryItem:
        """יצירה/עדכון של פריט מלאי ידני (כולל הגדרת עלות/סף התראה)."""
        item = None
        if data.get("id"):
            item = (
                self.db.query(InventoryItem)
                .filter(
                    InventoryItem.organization_id == self.organization_id,
                    InventoryItem.id == data["id"],
                )
                .first()
            )
        if item is None:
            item = InventoryItem(
                organization_id=self.organization_id,
                source=data.get("source", "manual"),
            )
            self.db.add(item)

        for field in (
            "sku", "name", "unit", "quantity",
            "unit_cost", "unit_price", "reorder_level",
        ):
            if field in data and data[field] is not None:
                setattr(item, field, data[field])

        self.db.commit()
        self.db.refresh(item)
        return item

    async def sync_from_sumit(self) -> Dict:
        """משיכת רשימת המלאי מ-SUMIT ועדכון הטבלה המקומית."""
        from .sync_engine import get_connector_for_org

        connector, _conn_id, source = get_connector_for_org(
            self.db, self.organization_id, preferred_source="sumit"
        )
        if source != "sumit" or not hasattr(connector, "list_stock"):
            raise ValueError("SUMIT אינו מחובר עבור ארגון זה")

        stock = await connector.list_stock()
        created = 0
        updated = 0
        for s in stock:
            ext = str(s.item_id)
            item = (
                self.db.query(InventoryItem)
                .filter(
                    InventoryItem.organization_id == self.organization_id,
                    InventoryItem.external_id == ext,
                    InventoryItem.source == "sumit",
                )
                .first()
            )
            if item is None:
                item = InventoryItem(
                    organization_id=self.organization_id,
                    external_id=ext,
                    source="sumit",
                )
                self.db.add(item)
                created += 1
            else:
                updated += 1
            # מסנכרן רק שם וכמות; עלות/מחיר/סף נשמרים אם הוגדרו ידנית
            item.name = s.name or item.name or ext
            item.quantity = s.quantity
            item.unit = s.unit or item.unit or "unit"
            item.last_updated = datetime.utcnow()

        self.db.commit()
        return {"synced": created + updated, "created": created, "updated": updated}
