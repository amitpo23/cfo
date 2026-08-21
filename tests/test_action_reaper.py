"""W6.2 — reaper לפעולות כסף תקועות (סיכון #2 ב-SWOT).

הפער: פעולה שנתקעה ב-`executing` (קריסה באמצע ביצוע) או ב-`unknown`
נשארת שם לנצח — `action_claimed_at` נכתב ואף תהליך לא קורא אותו. אין
תור, אין התרעה; מתגלה רק אם מישהו פותח את השיחה הספציפית.

ה-reaper: executing מעל 15 דקות ⇒ unknown (הספק אולי ביצע — לא retry!),
וכל unknown מקבל שורת פער + CfoInsight — פעם אחת (אידמפוטנטי).
"""
from datetime import datetime, timedelta, timezone

import pytest

from cfo.database import SessionLocal
from cfo.models import CfoInsight, ChatMessage, MoshkoGap, User
from cfo.services import action_reaper


@pytest.fixture(autouse=True)
def _clean(client, fresh_org):
    yield
    db = SessionLocal()
    try:
        db.query(MoshkoGap).delete()
        db.commit()
    finally:
        db.close()


def _stuck_message(db, org_id, user_id, *, status, minutes_ago=30):
    msg = ChatMessage(
        organization_id=org_id, user_id=user_id, session_id="reap",
        role="assistant", content="מבצע...",
        pending_action={"tool": "issue_document", "input": {}},
        action_status=status,
        action_claimed_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db.add(msg)
    db.commit()
    return msg


def test_stale_executing_becomes_unknown_with_gap_and_insight(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.organization_id == org_id).first().id
        msg = _stuck_message(db, org_id, user_id, status="executing", minutes_ago=30)

        result = action_reaper.sweep(db)
        assert result["stale_executing"] >= 1

        db.refresh(msg)
        assert msg.action_status == "unknown"
        gap = db.query(MoshkoGap).filter(MoshkoGap.message_id == msg.id).first()
        assert gap is not None and gap.gap_kind == "tool_failed"
        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "stuck_action",
        ).first()
        assert insight is not None and insight.severity == "critical"
    finally:
        db.close()


def test_fresh_executing_is_left_alone(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.organization_id == org_id).first().id
        msg = _stuck_message(db, org_id, user_id, status="executing", minutes_ago=2)
        action_reaper.sweep(db)
        db.refresh(msg)
        assert msg.action_status == "executing"
    finally:
        db.close()


def test_sweep_is_idempotent(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.organization_id == org_id).first().id
        msg = _stuck_message(db, org_id, user_id, status="unknown", minutes_ago=60)
        action_reaper.sweep(db)
        action_reaper.sweep(db)
        gaps = db.query(MoshkoGap).filter(MoshkoGap.message_id == msg.id).count()
        assert gaps == 1
    finally:
        db.close()


def test_reaper_runs_inside_the_morning_cycle(fresh_org):
    from datetime import date

    from cfo.services import morning_cycle_service as cycle

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = cycle.run_morning_cycle(db, org_id, date.today(), force=True)
        assert "action_reaper" in result["steps"]
    finally:
        db.close()
