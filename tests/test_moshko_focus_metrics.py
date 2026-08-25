"""S9 (ספרינט זהות-מושקו, 24-25/08/2026) — מדד המיקוד. שלושה מספרים
מהנתונים הקיימים בלבד, בלי מנוע חדש: אחוז תשובות-ויתור, gaps ל-100
תורים, ואחוז regression-pass. **בייסליין לפני S5/S6** — בלי מדד "לפני"
אין דרך לדעת אם פיצול הפרומפט/פרוטוקול-התור בכלל שיפרו משהו, רק
"מרגיש יותר טוב". honest-null: אין תורים בתקופה ⇒ None, לא 0%.
"""
from datetime import date, datetime, timedelta

import pytest

from cfo.database import SessionLocal
from cfo.models import ChatMessage, MoshkoGap
from cfo.services.moshko_focus_metrics import compute_focus_metrics


def _mk_message(db, org_id, user_id, *, role="assistant", content="תשובה", days_ago=0):
    msg = ChatMessage(
        organization_id=org_id, user_id=user_id, session_id="s1",
        role=role, content=content,
        created_at=datetime.utcnow() - timedelta(days=days_ago),
    )
    db.add(msg)
    db.flush()
    return msg


def _mk_gap(db, org_id, user_id, *, gap_kind="model_gave_up",
            regression_status=None, days_ago=0):
    gap = MoshkoGap(
        organization_id=org_id, user_id=user_id, session_id="s1",
        question="שאלה", answer="תשובה", gap_kind=gap_kind,
        regression_status=regression_status,
        created_at=datetime.utcnow() - timedelta(days=days_ago),
    )
    db.add(gap)
    db.flush()
    return gap


def test_no_data_in_period_is_honest_null_not_zero(fresh_org):
    org = fresh_org()
    db = SessionLocal()
    try:
        metrics = compute_focus_metrics(db, organization_id=org["org_id"])
        assert metrics["assistant_turns"] == 0
        assert metrics["giveup_rate"] is None
        assert metrics["gaps_per_100_turns"] is None
        assert metrics["regression_pass_rate"] is None
    finally:
        db.close()


def test_giveup_rate_computed_from_assistant_turns_and_gaps(fresh_org):
    org = fresh_org()
    org_id, user_id = org["org_id"], 1
    db = SessionLocal()
    try:
        for _ in range(4):
            _mk_message(db, org_id, user_id)
        _mk_gap(db, org_id, user_id, gap_kind="model_gave_up")
        db.commit()

        metrics = compute_focus_metrics(db, organization_id=org_id)
        assert metrics["assistant_turns"] == 4
        assert metrics["giveup_count"] == 1
        assert metrics["giveup_rate"] == 25.0
    finally:
        db.close()


def test_gaps_per_100_turns_normalizes_correctly(fresh_org):
    org = fresh_org()
    org_id, user_id = org["org_id"], 1
    db = SessionLocal()
    try:
        for _ in range(10):
            _mk_message(db, org_id, user_id)
        _mk_gap(db, org_id, user_id, gap_kind="tool_failed")
        _mk_gap(db, org_id, user_id, gap_kind="user_flagged")
        db.commit()

        metrics = compute_focus_metrics(db, organization_id=org_id)
        assert metrics["gaps_opened"] == 2
        assert metrics["gaps_per_100_turns"] == 20.0
    finally:
        db.close()


def test_regression_pass_rate_uses_latest_run_only(fresh_org):
    org = fresh_org()
    org_id, user_id = org["org_id"], 1
    db = SessionLocal()
    try:
        _mk_gap(db, org_id, user_id, gap_kind="model_gave_up", regression_status="passed")
        _mk_gap(db, org_id, user_id, gap_kind="model_gave_up", regression_status="passed")
        _mk_gap(db, org_id, user_id, gap_kind="model_gave_up", regression_status="failed")
        _mk_gap(db, org_id, user_id, gap_kind="model_gave_up", regression_status=None)  # לא הורץ
        db.commit()

        metrics = compute_focus_metrics(db, organization_id=org_id)
        assert metrics["regression_total"] == 3
        assert metrics["regression_passed"] == 2
        assert round(metrics["regression_pass_rate"], 2) == 66.67
    finally:
        db.close()


def test_org_scoped(fresh_org):
    org_a = fresh_org()
    org_b = fresh_org()
    db = SessionLocal()
    try:
        _mk_message(db, org_b["org_id"], 1)
        _mk_gap(db, org_b["org_id"], 1)
        db.commit()

        metrics = compute_focus_metrics(db, organization_id=org_a["org_id"])
        assert metrics["assistant_turns"] == 0
        assert metrics["gaps_opened"] == 0
    finally:
        db.close()


def test_period_filter_excludes_old_data(fresh_org):
    org = fresh_org()
    org_id, user_id = org["org_id"], 1
    db = SessionLocal()
    try:
        _mk_message(db, org_id, user_id, days_ago=1)
        _mk_message(db, org_id, user_id, days_ago=30)  # מחוץ לחלון
        db.commit()

        metrics = compute_focus_metrics(
            db, organization_id=org_id,
            since=datetime.utcnow() - timedelta(days=7),
        )
        assert metrics["assistant_turns"] == 1
    finally:
        db.close()
