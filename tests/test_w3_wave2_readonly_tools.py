"""W3 גל 2 (המשך, 21/08/2026) — סגירת הכיסוי קריאה-בלבד: מלאי, CRM,
טריגרים, סטטוס סליקה.

3 מ-4 התחומים כוסו כבר בגל הקודם (20/08): `list_stock` (מלאי),
`list_crm_entities`/`get_crm_entity`/... (CRM). התחום הרביעי — סטטוס
עסקאות סליקה — לא היה חשוף כלי מושקו (רק כ-route ב-payments.py,
ALREADY_COVERED במניפסט). טריגרים/webhook: SUMIT חושפת רק
subscribe/unsubscribe (כתיבה) — אין מתודה עטופה לרשימת מנויים קיימים,
ולכן לא נוסף כלי קריאה (ר' דוח המשימה).

הקובץ הזה סוגר את הפער: get_billing_status + get_transaction_status,
שני כלי קריאה עוטפים מתודות שכבר עטופות בקונקטור (Credit Card Terminal
— Billing/Gateway), אותו התחום שכבר נחשף בו get_reference_numbers
("עסקאות סליקה"). שני ה-endpoints אינם ברשימת PAID_ACTION_ENDPOINTS —
קריאות חינמיות תחת המגביל הכללי בלבד.
"""
import asyncio

import pytest

from cfo.integrations.sumit_integration import SumitAPIError
from cfo.services import ai_chat_tools
from cfo.services import sumit_tool_manifest as manifest
from cfo.services.ai_chat_tools import TOOLS, tool_target_system


READ_TOOLS = ("get_billing_status", "get_transaction_status")


# ==================================================================== #
# רישום בקטלוג — דפוס גל 1
# ==================================================================== #

def test_wave2_readonly_tools_are_registered_as_read():
    for name in READ_TOOLS:
        assert name in TOOLS, name
        assert TOOLS[name].category == "read", name
        assert TOOLS[name].policy_action is None, name
        assert not TOOLS[name].office, name


def test_wave2_readonly_tools_target_sumit():
    for name in READ_TOOLS:
        assert tool_target_system(name, arguments={}) == "sumit", name
        assert name in ai_chat_tools._SUMIT_TOOLS, name


# ==================================================================== #
# מניפסט הכיסוי — נשארים בדיוק בדלת אחת (disjoint), עם עדות ל-route הקיים
# ==================================================================== #

def test_billing_and_transaction_status_moved_to_tool_map():
    assert manifest.TOOL_METHOD_MAP["get_billing_status"] == ("get_billing_status",)
    assert manifest.TOOL_METHOD_MAP["get_transaction_status"] == ("get_transaction",)
    # לא נשארים גם ב-ALREADY_COVERED — הכרעה יחידה לכל מתודה.
    assert "get_billing_status" not in manifest.ALREADY_COVERED
    assert "get_transaction" not in manifest.ALREADY_COVERED


def test_inventory_and_crm_already_covered_no_duplication():
    """מלאי/CRM כוסו בגל הקודם — לא מוסיפים כלי כפול, רק מוודאים שהם שם."""
    for name in ("list_stock", "list_crm_entities", "get_crm_entity"):
        assert name in TOOLS, name
        assert TOOLS[name].category == "read", name


def test_no_read_tool_for_triggers_because_no_wrapped_list_method():
    """SUMIT חושפת subscribe/unsubscribe בלבד לטריגרים — אין מתודה עטופה
    לרשימת מנויים קיימים, ולכן אין כלי קריאה חדש (המשימה אוסרת לעטוף
    endpoint חדש). subscribe/unsubscribe נשארים כלי כתיבה בלבד."""
    assert TOOLS["subscribe_trigger"].category == "write"
    assert TOOLS["unsubscribe_trigger"].category == "write"
    assert "list_triggers" not in TOOLS
    assert "list_subscribed_triggers" not in TOOLS


# ==================================================================== #
# התנהגות הכלים — פלט וכשל כן (honest-null)
# ==================================================================== #

def test_get_billing_status_returns_provider_status(monkeypatch):
    async def _fake_call(_db, _org_id, _call):
        return {
            "Status": 0,
            "Data": {"Status": "Completed", "Transactions": [{"ID": 1, "Amount": 100}]},
        }

    monkeypatch.setattr(ai_chat_tools, "_sumit_call", _fake_call)
    result = asyncio.run(TOOLS["get_billing_status"].fn(
        None, 1, transaction_id="42",
    ))
    assert result["transaction_id"] == "42"
    assert "response" in result


def test_get_transaction_status_returns_provider_status(monkeypatch):
    from datetime import datetime
    from decimal import Decimal
    from cfo.integrations.sumit_models import TransactionResponse

    async def _fake_call(_db, _org_id, _call):
        return TransactionResponse(
            transaction_id="99", status="Completed", amount=Decimal("150"),
            currency="ILS", created_at=datetime(2026, 8, 20),
        )

    monkeypatch.setattr(ai_chat_tools, "_sumit_call", _fake_call)
    result = asyncio.run(TOOLS["get_transaction_status"].fn(
        None, 1, transaction_id="99",
    ))
    assert result == {
        "transaction_id": "99", "status": "Completed",
        "amount": 150.0, "currency": "ILS",
    }


def test_get_billing_status_propagates_provider_error_honestly(monkeypatch):
    """מודול הסליקה עשוי לא להיות מותקן בעסק — הכלי לא בולע את השגיאה
    ולא מחזיר "בהצלחה" מומצא; היא מטופלת honest-null ברמת ai_chat_service
    (מנגנון כללי לכל הכלים, לא ייחודי לכלי הזה)."""
    async def _boom(_db, _org_id, _call):
        raise SumitAPIError("SUMIT API error: מודול הסליקה לא מותקן בעסק")

    monkeypatch.setattr(ai_chat_tools, "_sumit_call", _boom)
    with pytest.raises(SumitAPIError, match="מודול הסליקה"):
        asyncio.run(TOOLS["get_billing_status"].fn(None, 1, transaction_id="1"))


def test_get_transaction_status_propagates_provider_error_honestly(monkeypatch):
    async def _boom(_db, _org_id, _call):
        raise SumitAPIError("SUMIT API error: מודול הסליקה לא מותקן בעסק")

    monkeypatch.setattr(ai_chat_tools, "_sumit_call", _boom)
    with pytest.raises(SumitAPIError, match="מודול הסליקה"):
        asyncio.run(TOOLS["get_transaction_status"].fn(None, 1, transaction_id="1"))
