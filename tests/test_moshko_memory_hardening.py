"""W1.4 — הקשחת זיכרון מושקו.

הפערים שנמצאו ב-20/08:
- `approved_at` היה דקורטיבי: זיכרון לא-מאושר הוזרק לפרומפט; כפתור
  "ביטול אישור" בדשבורד לא שינה דבר בהתנהגות.
- `last_used_at` לא נכתב מעולם — אי-אפשר לדעת איזה זיכרון השפיע.
- תקרת 2000 תווים לארגון חנקה את לולאת האימון (תיקון של 2001+ תווים
  לא ניתן לקידום לעולם).
"""
from datetime import datetime

import pytest

from cfo.database import SessionLocal
from cfo.models import MoshkoMemory
from cfo.services import moshko_memory


@pytest.fixture()
def org(fresh_org):
    return fresh_org()["org_id"]


@pytest.fixture(autouse=True)
def _clean_memory(client, fresh_org):
    yield
    db = SessionLocal()
    try:
        db.query(MoshkoMemory).delete()
        db.commit()
    finally:
        db.close()


def test_unapproved_memory_is_not_injected(org):
    db = SessionLocal()
    try:
        db.add(MoshkoMemory(
            organization_id=org, user_id=None,
            content="עובדה מאושרת", category="business_fact", source="admin",
            approved_at=datetime.utcnow(),
        ))
        db.add(MoshkoMemory(
            organization_id=org, user_id=None,
            content="עובדה שאושרה ובוטלה", category="business_fact", source="admin",
            approved_at=None,
        ))
        db.commit()

        block = moshko_memory.render_memory_block(db, org, None)
        assert "עובדה מאושרת" in block
        assert "עובדה שאושרה ובוטלה" not in block
    finally:
        db.close()


def test_chat_remember_is_auto_approved(org):
    """"תזכור ש..." בצ'אט הוא הוראה מפורשת של המשתמש — זה האישור.
    בלעדי זה, אכיפת approved_at הייתה משתיקה את כלי הזיכרון של מושקו."""
    db = SessionLocal()
    try:
        result = moshko_memory.remember(
            db, org, content="הספק הקבוע לחשמל הוא חברת אלקטרה",
        )
        assert result["status"] == "ok"
        row = db.query(MoshkoMemory).filter(MoshkoMemory.id == result["id"]).first()
        assert row.approved_at is not None
    finally:
        db.close()


def test_injected_memories_are_stamped_last_used(org):
    db = SessionLocal()
    try:
        db.add(MoshkoMemory(
            organization_id=org, user_id=None,
            content="עובדה בשימוש", category="business_fact", source="admin",
            approved_at=datetime.utcnow(),
        ))
        db.commit()

        moshko_memory.render_memory_block(db, org, None)
        db.commit()

        row = db.query(MoshkoMemory).filter(
            MoshkoMemory.organization_id == org,
        ).first()
        assert row.last_used_at is not None
    finally:
        db.close()


def test_org_cap_allows_a_real_training_loop():
    """8000 תווי correction מתקבלים ב-API — התקרה חייבת להכיל לפחות
    תיקון אחד מלא ועוד זיכרונות קיימים."""
    assert moshko_memory.ORG_MEMORY_CHAR_CAP >= 6000
