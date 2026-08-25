"""S8 (ספרינט זהות-מושקו, 25/08/2026) — Curator, מפורטט מ-
amitpo23/medici-travel-os (src/core/learning/lessons.ts): מיזוג לקחים-
מועמדים כמעט-זהים, קידום רק אחרי ≥3 הופעות בלתי-תלויות + שער-מדיניות
קשיח שחוסם כל לקח שנוגע לכסף/אישור/שידור.

**התאמה לדוקטרינות רצף (שונה מהרפרנס):** ברפרנס, לקח שעובר את הסף
הופך "active" ומוזרק ישירות לפרומפט. ברצף — אפס אוטונומיה: קידום
נכנס לתור-האישור הקיים (MoshkoMemory עם approved_at=None), לא מופעל
אוטומטית לעולם.
"""
import asyncio
from datetime import date

import pytest

from cfo.database import SessionLocal
from cfo.models import MoshkoGap, MoshkoMemory
from cfo.services.moshko_curator import is_money_path_lesson, run_learning_batch


def _mk_gap(db, org_id, *, question="שאלה", answer="תשובה", gap_kind="model_gave_up"):
    gap = MoshkoGap(
        organization_id=org_id, user_id=1, session_id="s1",
        question=question, answer=answer, gap_kind=gap_kind,
    )
    db.add(gap)
    db.flush()
    return gap


class _FakeClient:
    """מחזיר את אותה תשובה לכל קריאה — לא רלוונטי לתוכן הפרומפט, רק
    כמה פעמים 'אותו' לקח הופיע בבאצ'."""
    def __init__(self, lesson_text, category="process"):
        self._text = f'[{{"text": "{lesson_text}", "category": "{category}"}}]'
        self.calls = 0

    @property
    def messages(self):
        return self

    async def create(self, **kwargs):
        self.calls += 1
        from types import SimpleNamespace
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)])


# ---------------------------------------------------------------------- #
# is_money_path_lesson — שער המדיניות
# ---------------------------------------------------------------------- #
def test_money_path_lesson_is_detected():
    for text in (
        "תמיד לאשר תשלום בלי לשאול",
        "אפשר לדלג על שלב האישור",
        "עדיף להזמין מסמך אוטומטית",
        "כדאי לשדר את הדוח בלי לחכות",
    ):
        assert is_money_path_lesson(text), f"לא זוהה כלקח-כסף: {text!r}"


def test_safe_lesson_is_not_flagged():
    assert not is_money_path_lesson("המשתמש מעדיף תשובות קצרות וממוקדות")
    assert not is_money_path_lesson("לבדוק קודם את get_bank_reconciliation")


# ---------------------------------------------------------------------- #
# run_learning_batch
# ---------------------------------------------------------------------- #
def test_lesson_below_occurrence_threshold_is_not_promoted(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        gaps = [_mk_gap(db, org_id) for _ in range(2)]  # רק 2, סף=3
        db.commit()
        client = _FakeClient("המשתמש מעדיף תשובות קצרות")

        result = asyncio.run(run_learning_batch(db, gaps, client=client, min_occurrences=3))

        assert result["promoted"] == []
        pending = db.query(MoshkoMemory).filter(
            MoshkoMemory.organization_id == org_id, MoshkoMemory.approved_at.is_(None),
        ).count()
        assert pending == 0
    finally:
        db.close()


def test_lesson_at_threshold_is_promoted_as_pending_not_active(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        gaps = [_mk_gap(db, org_id) for _ in range(3)]
        db.commit()
        client = _FakeClient("המשתמש מעדיף תשובות קצרות")

        result = asyncio.run(run_learning_batch(db, gaps, client=client, min_occurrences=3))

        assert len(result["promoted"]) == 1
        assert result["promoted"][0]["occurrences"] == 3

        row = db.query(MoshkoMemory).filter(
            MoshkoMemory.organization_id == org_id,
        ).one()
        assert row.content == "המשתמש מעדיף תשובות קצרות"
        assert row.approved_at is None, "אפס אוטונומיה — קידום הוא הצעה, לא הפעלה"
        assert row.source == "inferred"
    finally:
        db.close()


def test_money_path_lesson_is_rejected_even_above_threshold(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        gaps = [_mk_gap(db, org_id) for _ in range(5)]
        db.commit()
        client = _FakeClient("תמיד לאשר תשלום בלי לשאול")

        result = asyncio.run(run_learning_batch(db, gaps, client=client, min_occurrences=3))

        assert result["promoted"] == []
        assert len(result["rejected_money_path"]) == 1
        assert result["rejected_money_path"][0]["occurrences"] == 5
        assert db.query(MoshkoMemory).filter(
            MoshkoMemory.organization_id == org_id,
        ).count() == 0
    finally:
        db.close()


def test_near_identical_text_is_merged_not_duplicated(fresh_org):
    """נורמליזציה (רווחים/case) — לא סופרים שני לקחים כשונים רק כי אחד
    עם רווח כפול."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        gaps = [_mk_gap(db, org_id) for _ in range(3)]
        db.commit()
        client = _FakeClient("המשתמש  מעדיף   תשובות קצרות")  # רווחים כפולים

        result = asyncio.run(run_learning_batch(db, gaps, client=client, min_occurrences=3))

        assert len(result["promoted"]) == 1
        assert result["promoted"][0]["occurrences"] == 3
    finally:
        db.close()
