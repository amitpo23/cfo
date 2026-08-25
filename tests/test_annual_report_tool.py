"""get_annual_report_draft — הפער שנמצא במיפוי-הארכיטקטורה (Fable,
24-25/08/2026): `annual_report_service.py` (form_1301/form_1214) קיים
ובדוק, אך מעולם לא היה חשוף ככלי-מושקו — "אפס מופעי 'annual' ב-
ai_chat_tools.py". הבעלים ביקש במפורש (18/08): "מושקו גם צריך לדעת
לעשות דוח שנתי ולאמת". שני הטפסים כבר draft=True + disclaimer +
notes — עוטפים בלבד, לא בונים לוגיקה חדשה.
"""
import asyncio

from cfo.database import SessionLocal
from cfo.services.ai_chat_tools import TOOLS


def test_the_tool_is_registered():
    assert "get_annual_report_draft" in TOOLS
    assert TOOLS["get_annual_report_draft"].category == "read"


def test_form_1301_for_an_individual(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["get_annual_report_draft"].fn(
            db, org_id, form="1301", year=2026,
        ))
        assert result["form"] == "1301"
        assert result["draft"] is True
        assert result["disclaimer"]
    finally:
        db.close()


def test_form_1214_for_a_company(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["get_annual_report_draft"].fn(
            db, org_id, form="1214", year=2026,
        ))
        assert result["form"] == "1214"
        assert result["draft"] is True
    finally:
        db.close()


def test_unknown_form_is_an_honest_error_not_a_guess(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["get_annual_report_draft"].fn(
            db, org_id, form="9999", year=2026,
        ))
        assert "error" in result
    finally:
        db.close()
