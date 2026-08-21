"""W1.5 — regression runner לשאלות שקודמו לידע (תוכנית העומק 20/08).

כשתשובת בעלים מקודמת לזיכרון ("ענה וקדם לידע"), השאלה המקורית נשארת על
אותה שורת MoshkoGap (promoted_memory_id לא-ריק) — זה מקרה הרגרסיה. הרצה
מריצה אותה מחדש דרך AIChatService ובודקת: (א) הזיכרון שקודם אכן הוזרק
להקשר (דרך moshko_memory.render_memory_block — אותו מנגנון בדיוק), (ב)
התשובה אינה תשובת-ויתור (הגלאי הקיים מ-W1.1, is_giveup_answer). מקרה
שנכשל נפתח מחדש כפער (status='open') — סיבוב הלולאה. ריצה ידנית בלבד.
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from cfo.auth import create_access_token
from cfo.database import SessionLocal
from cfo.models import MoshkoGap, MoshkoMemory, User, UserRole
from cfo.services.ai_chat_service import AIChatService
from cfo.services.moshko_regression import run_regression

from tests.test_ai_chat_service import FakeAnthropicClient, _patch_client, _text_block


def _end_turn(text):
    return SimpleNamespace(stop_reason="end_turn", content=[_text_block(text)])


@pytest.fixture(autouse=True)
def _clean(client):
    db = SessionLocal()
    try:
        db.query(MoshkoGap).delete()
        db.query(MoshkoMemory).delete()
        db.commit()
        yield
    finally:
        db.query(MoshkoGap).delete()
        db.query(MoshkoMemory).delete()
        db.commit()
        db.close()


@pytest.fixture
def super_admin(client, fresh_org):
    actor = fresh_org()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.organization_id == actor["org_id"]).first()
        user.role = UserRole.SUPER_ADMIN
        db.commit()
        token = create_access_token(data={
            "sub": str(user.id),
            "role": UserRole.SUPER_ADMIN.value,
            "org_id": user.organization_id,
        })
        return {
            "headers": {"Authorization": f"Bearer {token}"},
            "user_id": user.id, "org_id": user.organization_id,
        }
    finally:
        db.close()


def _seed_promoted_case(
    db, org_id, user_id, *,
    question="מה השם המסחרי של הארגון?",
    memory_content="השם המסחרי של הארגון הוא 'עסק לדוגמה'.",
    approved=True,
):
    memory = MoshkoMemory(
        organization_id=org_id, user_id=None,
        content=memory_content, category="correction", source="admin",
        approved_at=datetime.utcnow() if approved else None,
    )
    db.add(memory)
    db.flush()
    gap = MoshkoGap(
        organization_id=org_id, user_id=user_id, session_id="orig-s1",
        question=question, answer="לא הצלחתי",
        gap_kind="model_gave_up", status="answered",
        resolution=memory_content,
        promoted_memory_id=memory.id,
    )
    db.add(gap)
    db.commit()
    db.refresh(gap)
    return gap, memory


def _org_user_id(db, org_id):
    return db.query(User.id).filter(User.organization_id == org_id).scalar()


# ---------------------------------------------------------------------- #
# Service-level behaviour.
# ---------------------------------------------------------------------- #

def test_case_passes_when_memory_injected_and_no_giveup(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        user_id = _org_user_id(db, org_id)
        gap, memory = _seed_promoted_case(db, org_id, user_id)

        _patch_client(monkeypatch, responses=[
            _end_turn("השם המסחרי הוא 'עסק לדוגמה', בהתאם למה שכבר ידוע."),
        ])

        result = asyncio.run(run_regression(db, organization_id=org_id))
        assert result == {
            "total": 1, "passed": 1, "failed": 0, "skipped": 0, "errored": 0,
            "cases": result["cases"],
        }
        assert result["cases"][0]["memory_injected"] is True
        assert result["cases"][0]["gave_up"] is False

        db.refresh(gap)
        assert gap.regression_status == "passed"
        assert gap.regression_checked_at is not None
        # מקרה שעבר לא נוגע בסטטוס הגאפ המקורי.
        assert gap.status == "answered"
    finally:
        db.close()


def test_case_fails_and_reopens_gap_when_model_gives_up(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        user_id = _org_user_id(db, org_id)
        gap, memory = _seed_promoted_case(db, org_id, user_id)

        _patch_client(monkeypatch, responses=[
            _end_turn("לא הצלחתי להשלים את הבקשה."),
        ])

        result = asyncio.run(run_regression(db, organization_id=org_id))
        assert result["failed"] == 1
        assert result["cases"][0]["gave_up"] is True

        db.refresh(gap)
        assert gap.regression_status == "failed"
        assert gap.status == "open"  # סיבוב הלולאה

        # אין שורת gap כפולה מ-W1.1 (session_id של הרגרסיה) — מקור-אמת
        # יחיד: אותה שורה מקורית שנפתחה מחדש.
        all_gaps = db.query(MoshkoGap).filter(MoshkoGap.organization_id == org_id).all()
        assert len(all_gaps) == 1
        assert all_gaps[0].id == gap.id
    finally:
        db.close()


def test_case_fails_when_promoted_memory_not_approved(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        user_id = _org_user_id(db, org_id)
        gap, memory = _seed_promoted_case(db, org_id, user_id, approved=False)

        # תשובה תקינה לגמרי, לא ויתור — אבל הזיכרון לא מאושר ולכן לא מוזרק.
        _patch_client(monkeypatch, responses=[
            _end_turn("הנה תשובה תקינה כלשהי."),
        ])

        result = asyncio.run(run_regression(db, organization_id=org_id))
        assert result["failed"] == 1
        assert result["cases"][0]["memory_injected"] is False
        assert result["cases"][0]["gave_up"] is False

        db.refresh(gap)
        assert gap.regression_status == "failed"
        assert gap.status == "open"
    finally:
        db.close()


def test_case_skipped_when_no_original_question(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        user_id = _org_user_id(db, org_id)
        gap, memory = _seed_promoted_case(db, org_id, user_id, question=None)

        fake = _patch_client(monkeypatch, responses=[])
        result = asyncio.run(run_regression(db, organization_id=org_id))

        assert result == {
            "total": 1, "passed": 0, "failed": 0, "skipped": 1, "errored": 0,
            "cases": result["cases"],
        }
        # לא נקראה שום בקשת LLM עבור מקרה מדולג — עקביות עם משמעת העלויות.
        assert fake.messages.calls == []

        db.refresh(gap)
        assert gap.regression_status is None
    finally:
        db.close()


def test_case_skipped_when_promoted_memory_deleted(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        user_id = _org_user_id(db, org_id)
        gap, memory = _seed_promoted_case(db, org_id, user_id)
        db.delete(memory)
        db.commit()

        fake = _patch_client(monkeypatch, responses=[])
        result = asyncio.run(run_regression(db, organization_id=org_id))
        assert result["skipped"] == 1
        assert fake.messages.calls == []
    finally:
        db.close()


def test_non_promoted_gaps_are_not_regression_cases(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        user_id = _org_user_id(db, org_id)
        db.add(MoshkoGap(
            organization_id=org_id, user_id=user_id, session_id="s1",
            question="שאלה כלשהי", answer="לא הצלחתי",
            gap_kind="model_gave_up", status="open",
        ))
        db.commit()

        result = asyncio.run(run_regression(db, organization_id=org_id))
        assert result["total"] == 0
    finally:
        db.close()


def test_one_case_error_does_not_discard_earlier_committed_cases(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        user_id = _org_user_id(db, org_id)
        gap_a, _ = _seed_promoted_case(db, org_id, user_id, question="שאלה א")
        gap_b, _ = _seed_promoted_case(db, org_id, user_id, question="שאלה ב")

        class _BoomMessages:
            def __init__(self):
                self.calls = []

            async def create(self, **kwargs):
                self.calls.append(kwargs)
                raise RuntimeError("upstream boom")

        class _BoomClient:
            def __init__(self):
                self.messages = _BoomMessages()

        state = {"n": 0}

        def _flaky_make_client(self):
            state["n"] += 1
            if state["n"] == 1:
                # מקרה א נכשל ברמת ה-API.
                return _BoomClient()
            # מקרה ב עובר כרגיל.
            return FakeAnthropicClient([_end_turn("תשובה תקינה")])

        monkeypatch.setattr(AIChatService, "_make_client", _flaky_make_client)

        result = asyncio.run(run_regression(db, organization_id=org_id))
        assert result["errored"] == 1
        assert result["passed"] == 1

        db.refresh(gap_a)
        db.refresh(gap_b)
        # מקרה א: לא הוערך בכלל (honest-null) — לא passed ולא failed.
        assert gap_a.regression_status is None
        assert gap_a.status == "answered"
        # מקרה ב: הצליח ונשמר.
        assert gap_b.regression_status == "passed"
    finally:
        db.close()


def test_run_regression_respects_limit(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        user_id = _org_user_id(db, org_id)
        for i in range(3):
            _seed_promoted_case(db, org_id, user_id, question=f"שאלה {i}")

        _patch_client(monkeypatch, responses=[
            _end_turn("תשובה"),
        ])
        result = asyncio.run(run_regression(db, organization_id=org_id, limit=1))
        assert result["total"] == 1
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# Admin route.
# ---------------------------------------------------------------------- #

def test_admin_route_runs_regression_and_updates_gap(monkeypatch, client, super_admin):
    db = SessionLocal()
    try:
        gap, memory = _seed_promoted_case(db, super_admin["org_id"], super_admin["user_id"])
    finally:
        db.close()

    _patch_client(monkeypatch, responses=[
        _end_turn("לא הצלחתי להשלים את הבקשה."),
    ])

    r = client.post(
        "/api/admin/moshko/regression/run",
        params={"organization_id": super_admin["org_id"]},
        headers=super_admin["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["failed"] == 1

    listing = client.get(
        "/api/admin/moshko/gaps",
        params={"status": "open", "organization_id": super_admin["org_id"]},
        headers=super_admin["headers"],
    )
    rows = listing.json()["gaps"]
    reopened = next(row for row in rows if row["id"] == gap.id)
    assert reopened["regression_status"] == "failed"
    assert reopened["regression_checked_at"] is not None


def test_regression_route_requires_super_admin(client, fresh_org):
    iso = fresh_org()
    r = client.post(
        "/api/admin/moshko/regression/run",
        params={"organization_id": iso["org_id"]},
        headers=iso["headers"],
    )
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------- #
# Manual-only — CRITICAL constraint from the brief.
# ---------------------------------------------------------------------- #

def test_no_cron_entry_references_regression():
    config = json.loads((Path(__file__).resolve().parents[1] / "vercel.json").read_text())
    for job in config.get("crons", []):
        assert "regression" not in job["path"]
