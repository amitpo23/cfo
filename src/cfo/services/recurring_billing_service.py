"""הוראות קבע ב-SUMIT ככלי מושקו — W3 גל 1 (תוכנית העומק 20/08).

מקורות אמת:
- swagger 19/08: אין endpoint "create recurring" ייעודי — יצירה היא
  `/billing/recurring/charge/` עם `Recurrence`; ‏`PaymentMethod` אופציונלי
  (nullable) — בהיעדרו SUMIT משתמשת באמצעי התשלום השמור של הלקוח.
  **לעולם לא מקבלים כאן פרטי כרטיס** — אם ללקוח אין אמצעי שמור, השגיאה
  של SUMIT מוחזרת כמו שהיא.
- חוק 18 (SUMIT_KNOWLEDGE_BASE): תאריך רטרואקטיבי ⇒ חיובי catch-up
  כפולים; אין יום חיוב אחרי ה-28; אסור לשנות לקוח/מוצר בהוראה פעילה.
  הוולידציות כאן אוכפות את החוק **לפני** כל קריאת רשת.

כל פעולת כתיבה מגיעה לכאן רק אחרי שער האישור של הצ'אט (write tool ⇒
confirm_action מפורש), והרשת עצמה עוברת את שערי המכסה (limiter + שער
פעולות-בתשלום ל-charge).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Optional


class RecurringValidationError(ValueError):
    """קלט שמפר את חוק 18 — נחסם לפני כל רשת."""


def validate_new_recurring(*, start_date: Optional[date], today: date) -> None:
    if start_date is None:
        return
    if start_date < today:
        raise RecurringValidationError(
            f"תאריך התחלה רטרואקטיבי ({start_date.isoformat()}): SUMIT מבצעת "
            "חיובי catch-up על כל התקופה שעברה — חיובים כפולים בפועל (חוק 18)."
        )
    if start_date.day > 28:
        raise RecurringValidationError(
            f"יום חיוב {start_date.day} אינו קיים בכל החודשים — אין יום חיוב "
            "אחרי ה-28 (חוק 18)."
        )


def validate_recurring_update(
    *, new_customer_id: Optional[str] = None, new_item_name: Optional[str] = None,
) -> None:
    if new_customer_id is not None:
        raise RecurringValidationError(
            "אסור לשנות לקוח בהוראת קבע פעילה (חוק 18) — יש לבטל וליצור חדשה."
        )
    if new_item_name is not None:
        raise RecurringValidationError(
            "אסור לשנות מוצר בהוראת קבע פעילה (חוק 18) — יש לבטל וליצור חדשה."
        )


async def _client_for_org(db, org_id: int):
    """קליינט SUMIT של הארגון — דרך אותו מפעל שהסנכרון משתמש בו
    (מפתח מ-IntegrationConnection, מגביל אמיתי פר-ארגון)."""
    from .sync_engine import get_connector_for_org

    connector, _conn_id, _source = get_connector_for_org(
        db, org_id, preferred_source="sumit",
    )
    return await connector._get_client()


async def list_recurring(db, org_id: int, *, customer_id: str) -> dict[str, Any]:
    client = await _client_for_org(db, org_id)
    try:
        items = await client.list_customer_recurring(customer_id)
    finally:
        await client.client.aclose()
    return {"recurring": [
        {
            "recurring_id": i.recurring_id,
            "customer_id": i.customer_id,
            "amount": float(i.amount),
            "status": i.status,
            "next_charge_date": i.next_charge_date.isoformat() if i.next_charge_date else None,
        }
        for i in items
    ]}


async def cancel_recurring(
    db, org_id: int, *, recurring_id: str, customer_id: Optional[str] = None,
) -> dict[str, Any]:
    client = await _client_for_org(db, org_id)
    try:
        result = await client.cancel_recurring(recurring_id, customer_id=customer_id)
    finally:
        await client.client.aclose()
    return {"status": "cancelled", "recurring_id": recurring_id, "response": result}


async def update_recurring_amount(
    db, org_id: int, *, recurring_id: str, customer_id: str,
    amount: float, next_payment_date: Optional[str] = None,
) -> dict[str, Any]:
    """עדכון סכום/תאריך-הבא בלבד — שינוי לקוח/מוצר חסום בוולידציה."""
    from ..integrations.sumit_models import RecurringPaymentRequest

    next_date = date.fromisoformat(next_payment_date) if next_payment_date else None
    validate_new_recurring(start_date=next_date, today=date.today())

    client = await _client_for_org(db, org_id)
    try:
        updated = await client.update_recurring(recurring_id, RecurringPaymentRequest(
            customer_id=customer_id,
            amount=Decimal(str(amount)),
            currency="ILS",
            frequency="monthly",
            start_date=next_date,
        ))
    finally:
        await client.client.aclose()
    return {
        "status": "updated",
        "recurring_id": updated.recurring_id,
        "amount": float(updated.amount),
        "next_charge_date": updated.next_charge_date.isoformat() if updated.next_charge_date else None,
    }


async def create_recurring(
    db, org_id: int, *, customer_id: str, item_name: str, unit_price: float,
    recurrence_months: int, start_date: Optional[str] = None,
    description: Optional[str] = None,
) -> dict[str, Any]:
    """יצירת הוראת קבע דרך `/billing/recurring/charge/` + `Recurrence`.

    בלי PaymentMethod — SUMIT מחייבת מאמצעי התשלום השמור של הלקוח; אם
    אין כזה, השגיאה מוחזרת כמו שהיא (honest-null, אפס טיפול בכרטיסים).
    """
    parsed_start = date.fromisoformat(start_date) if start_date else None
    validate_new_recurring(start_date=parsed_start, today=date.today())
    if recurrence_months < 1 or recurrence_months > 120:
        raise RecurringValidationError("Recurrence חייב להיות 1–120 חודשים")
    if unit_price <= 0:
        raise RecurringValidationError("סכום ההוראה חייב להיות חיובי")

    payload: dict[str, Any] = {
        "Customer": {"ID": int(customer_id), "SearchMode": 1},
        "Items": [{
            "Item": {"Name": item_name, "SearchMode": 0},
            "Quantity": 1.0,
            "UnitPrice": float(unit_price),
            "Duration_Months": 1,
            "Recurrence": int(recurrence_months),
        }],
        "VATIncluded": True,
    }
    if description:
        payload["FirstDocumentDescription"] = description

    client = await _client_for_org(db, org_id)
    try:
        result = await client._make_request("/billing/recurring/charge/", data=payload)
    finally:
        await client.client.aclose()
    return {
        "status": "created",
        "customer_id": customer_id,
        "item": item_name,
        "unit_price": unit_price,
        "recurrence_months": recurrence_months,
        "response_status": result.get("Status"),
        "response": result.get("Data"),
    }
