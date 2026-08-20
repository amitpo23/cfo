"""W3 גל 1 — חשיפת כלי SUMIT למושקו (אישור בעלים 20/08, תוכנית העומק).

עד היום רק 4 מ-89 מתודות היו נגישות למושקו. גל 1 מוסיף: הוראות קבע
(list/create/cancel/update עם ולידציות חוק 18), ביטול מסמך, פרטי מסמך,
דוח חוב לקוחות, ו-SMS גבייה — כל כלי write עובר שער אישור מפורש.

חוק 18 (SUMIT_KNOWLEDGE_BASE): תאריך רטרואקטיבי ⇒ חיובי catch-up
כפולים; אין יום חיוב אחרי ה-28; אסור לשנות לקוח/מוצר בהוראה פעילה.
"""
import asyncio
from datetime import date

import pytest

from cfo.services import recurring_billing_service as recurring
from cfo.services.ai_chat_tools import TOOLS, tool_target_system


# ==================================================================== #
# רישום בקטלוג
# ==================================================================== #

READ_TOOLS = ("list_recurring", "get_customer_debt_report")
WRITE_TOOLS = (
    "create_recurring", "cancel_recurring", "update_recurring",
    "cancel_document", "send_collection_sms",
)


def test_wave1_tools_are_registered_with_correct_categories():
    for name in READ_TOOLS:
        assert name in TOOLS, name
        assert TOOLS[name].category == "read", name
    for name in WRITE_TOOLS:
        assert name in TOOLS, name
        assert TOOLS[name].category == "write", name
        assert not TOOLS[name].office, name


def test_wave1_tools_target_sumit():
    for name in READ_TOOLS + WRITE_TOOLS:
        assert tool_target_system(name, arguments={}) == "sumit", name


# ==================================================================== #
# חוק 18 — ולידציות מלכודות ההוראות
# ==================================================================== #

def test_retroactive_start_date_is_rejected():
    with pytest.raises(recurring.RecurringValidationError, match="רטרואקטיבי"):
        recurring.validate_new_recurring(
            start_date=date(2026, 8, 1), today=date(2026, 8, 20),
        )


def test_charge_day_after_the_28th_is_rejected():
    with pytest.raises(recurring.RecurringValidationError, match="28"):
        recurring.validate_new_recurring(
            start_date=date(2026, 9, 30), today=date(2026, 8, 20),
        )


def test_valid_future_start_passes():
    recurring.validate_new_recurring(
        start_date=date(2026, 9, 15), today=date(2026, 8, 20),
    )
    recurring.validate_new_recurring(start_date=None, today=date(2026, 8, 20))


def test_customer_or_product_change_on_active_recurring_is_rejected():
    with pytest.raises(recurring.RecurringValidationError, match="לקוח"):
        recurring.validate_recurring_update(new_customer_id="999")
    with pytest.raises(recurring.RecurringValidationError, match="מוצר"):
        recurring.validate_recurring_update(new_item_name="מוצר אחר")
    recurring.validate_recurring_update()  # שינוי סכום/תאריך בלבד — מותר


# ==================================================================== #
# הכלי חוסם לפני רשת
# ==================================================================== #

def test_create_recurring_tool_rejects_retroactive_before_any_network(monkeypatch, fresh_org):
    from cfo.database import SessionLocal

    org_id = fresh_org()["org_id"]

    def _no_network(*_a, **_k):
        raise AssertionError("connector was built despite invalid input")

    monkeypatch.setattr(recurring, "_client_for_org", _no_network)

    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["create_recurring"].fn(
            db, org_id,
            customer_id="123", item_name="ריטיינר", unit_price=200.0,
            recurrence_months=12, start_date="2026-01-01",
        ))
    finally:
        db.close()
    assert "error" in result
    assert "רטרואקטיבי" in result["error"]
