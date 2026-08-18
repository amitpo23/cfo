"""מושקו יוצר פרופיל רכב **מהתשובה של הבעלים** — לא מנחש.

**הממצא (18/08/2026).** `VehicleProfile` (עיקר-שימוש פר-רכב, קובע ניכוי
מע"מ תשומות רכב) ריק לגמרי בפרוד — 0 שורות. כל הוצאת רכב נופלת לתור
הכרעה. **אין** לו כלי בכלל — קיים API+כלי ל-`VehicleDeductionProfile`
(עלויות שנתיות לטופס 1301/1214, שונה) אבל לא לפרופיל השימוש השוטף.

**למה לא סתם זרעתי שורה.** `primarily_business` הוא עובדת-מס אמיתית —
טעות בו משנה ניכוי מע"מ בפועל. honest-null אוסר להמציא אותה. הפתרון:
כלי **כתיבה** שמושקו מפעיל רק מתוך תשובה מפורשת של המשתמש בשיחה, לא
מהזיכרון ולא בברירת מחדל — ועובר באישור הסטנדרטי לפני שמתבצע (כמו כל
כלי כתיבה אחר, ר' BASE_SYSTEM_PROMPT).
"""
import asyncio

import pytest

from cfo.database import SessionLocal
from cfo.models import VehicleProfile
from cfo.services.ai_chat_tools import TOOLS


def test_the_tool_is_registered():
    assert "set_vehicle_profile" in TOOLS


def test_it_is_a_write_tool():
    """כתיבה — עוברת דרך מסלול האישור הסטנדרטי, לא מתבצעת מיד."""
    assert TOOLS["set_vehicle_profile"].category == "write"


def test_it_creates_a_profile_from_explicit_fields(fresh_org):
    """הלב: השדות מגיעים מהקריאה (שהמודל ממלא מדברי המשתמש בשיחה),
    לא מנוחשים בתוך הכלי."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]

    result = asyncio.run(TOOLS["set_vehicle_profile"].fn(
        db, org_id, label="קורולה 12-345-67",
        vehicle_kind="commercial", primarily_business=True,
    ))

    assert result["status"] == "saved"
    row = db.query(VehicleProfile).filter(
        VehicleProfile.organization_id == org_id).one()
    assert row.label == "קורולה 12-345-67"
    assert row.vehicle_kind == "commercial"
    assert row.primarily_business is True


def test_primarily_business_defaults_to_unknown_not_true():
    """honest-null: אם המשתמש לא אמר, אסור לכלי להניח 'עסקי בעיקר'.
    None נשאר None עד שמישהו אומר בפירוש."""
    import inspect

    from cfo.services import ai_chat_tools

    sig = inspect.signature(ai_chat_tools._set_vehicle_profile)
    default = sig.parameters["primarily_business"].default

    assert default is None


def test_repeated_calls_update_not_duplicate(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]

    asyncio.run(TOOLS["set_vehicle_profile"].fn(
        db, org_id, label="קורולה", vehicle_kind="private"))
    asyncio.run(TOOLS["set_vehicle_profile"].fn(
        db, org_id, label="קורולה", vehicle_kind="commercial",
        primarily_business=True))

    rows = db.query(VehicleProfile).filter(
        VehicleProfile.organization_id == org_id,
        VehicleProfile.label == "קורולה",
    ).all()
    assert len(rows) == 1
    assert rows[0].vehicle_kind == "commercial"


def test_org_scoped(fresh_org):
    db = SessionLocal()
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]

    asyncio.run(TOOLS["set_vehicle_profile"].fn(
        db, org_a, label="רכב א", vehicle_kind="private"))

    rows_b = db.query(VehicleProfile).filter(
        VehicleProfile.organization_id == org_b).all()
    assert rows_b == []
