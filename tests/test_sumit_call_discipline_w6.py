"""ביקורת קריאות SUMIT ‏(הנחיית בעלים 21/08: "שלא נחזור לאותה בעיה").

שני סגרים:
1. `beginredirect` (יצירת דף תשלום) — לא היה בשער הפעולות-בתשלום.
   לא ידוע בוודאות אם SUMIT מחייבת עליו — ולכן fail-closed: נספר.
2. מחזור הבוקר (שעומד לחזור ל-cron ב-W6.8) חייב להיות **אפס רשת מול
   SUMIT** — השרשרת ההיסטורית morning_brief→send_sms היא שחייבה בעבר.
   ה-SMS כבוי כברירת מחדל (morning_brief_sms_enabled=False) והטסט מקבע
   שהמחזור כולו לא מגיע לרשת SUMIT.
"""
from datetime import date

import pytest

from cfo.integrations.sumit_integration import PAID_ACTION_ENDPOINTS


def test_beginredirect_endpoints_are_paid_gated():
    assert "/billing/payments/beginredirect/" in PAID_ACTION_ENDPOINTS
    assert "/creditguy/gateway/beginredirect/" in PAID_ACTION_ENDPOINTS


def test_morning_cycle_makes_zero_sumit_network_calls(monkeypatch, fresh_org):
    """W6.8: לפני החזרת bookkeeper-morning ל-cron — הוכחה שהמחזור המלא
    אינו יוצר אף בקשת SUMIT. כל ניסיון רשת מפיל את הטסט."""
    from cfo.database import SessionLocal
    from cfo.integrations.sumit_integration import SumitIntegration
    from cfo.services import morning_cycle_service as cycle

    async def _forbidden(self, *args, **kwargs):
        raise AssertionError(
            f"morning cycle reached SUMIT network: {args[:1]} {kwargs.get('endpoint','')}"
        )

    monkeypatch.setattr(SumitIntegration, "_make_request", _forbidden)
    monkeypatch.setattr(SumitIntegration, "_post_binary", _forbidden)

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = cycle.run_morning_cycle(db, org_id, date.today(), force=True)
    finally:
        db.close()
    assert result["status"] == "ok"
    # אף צעד לא נכשל על ניסיון רשת (הצעדים בולעים חריגות — בודקים במפורש).
    for name, step in result["steps"].items():
        step_text = str(step)
        assert "reached SUMIT network" not in step_text, (name, step)
