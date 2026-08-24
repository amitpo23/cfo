"""W1.1 — תור הכישלונות/פערי-היכולת של מושקו (`moshko_gaps`).

הפער שנמצא ב-20/08: כישלון של מושקו — כלי שנפל, "לא הצלחתי", בקשה שאין
לה כלי — לא נלכד כתור ניתוח. תשובת ויתור נשמרת כהודעה רגילה בלי סימון,
והבעלים לא רואה שורה שאפשר לענות עליה ולהזין הקשר.
"""
import asyncio
from datetime import datetime

import pytest

from cfo.auth import create_access_token
from cfo.database import SessionLocal
from cfo.models import ChatMessage, MoshkoGap, MoshkoMemory, User, UserRole


@pytest.fixture(autouse=True)
def _clean(client):
    db = SessionLocal()
    try:
        db.query(MoshkoGap).delete()
        db.commit()
        yield
    finally:
        db.query(MoshkoGap).delete()
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


def _service(db, org_id, user_id):
    from cfo.services.ai_chat_service import AIChatService
    return AIChatService(db, org_id, user_id, is_super_admin=True)


def _seed_exchange(db, org_id, user_id, question="כמה מע\"מ אני חייב?",
                   answer="לא הצלחתי להשלים את הבקשה."):
    user_msg = ChatMessage(
        organization_id=org_id, user_id=user_id, session_id="s1",
        role="user", content=question,
    )
    db.add(user_msg)
    db.flush()
    assistant = ChatMessage(
        organization_id=org_id, user_id=user_id, session_id="s1",
        role="assistant", content=answer,
    )
    db.add(assistant)
    db.commit()
    return user_msg, assistant


def test_a_failed_tool_call_creates_an_open_gap(fresh_org):
    iso = fresh_org()
    org_id = iso["org_id"]
    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.organization_id == org_id).first().id
        user_msg, _ = _seed_exchange(db, org_id, user_id)
        svc = _service(db, org_id, user_id)

        class _Tool:
            name = "get_pnl"
            needs_user = False

            @staticmethod
            async def fn(db_, org, **_kw):
                raise RuntimeError("db exploded")

        asyncio.run(svc._execute_tool_observed(
            tool=_Tool, call_kwargs={}, logged_arguments={},
            session_id="s1", message_id=user_msg.id, propagate=False,
        ))
        db.commit()

        gap = db.query(MoshkoGap).filter(
            MoshkoGap.organization_id == org_id,
        ).first()
        assert gap is not None
        assert gap.gap_kind == "tool_failed"
        assert gap.status == "open"
        assert gap.tool_name == "get_pnl"
        assert "db exploded" in (gap.error or "")
        assert gap.question  # שאלת המשתמש נלכדה מההודעה
    finally:
        db.close()


def test_a_giveup_reply_creates_a_gap(fresh_org):
    iso = fresh_org()
    org_id = iso["org_id"]
    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.organization_id == org_id).first().id
        svc = _service(db, org_id, user_id)
        svc._capture_gap_if_giveup(
            session_id="s1", message_id=None,
            question="תכין לי דוח כספי לשנת 2025",
            final_text="לא הצלחתי להשלים את הבקשה בתוך מספר הצעדים המותר.",
        )
        db.commit()
        gap = db.query(MoshkoGap).filter(MoshkoGap.organization_id == org_id).first()
        assert gap is not None and gap.gap_kind == "model_gave_up"
        assert gap.question == "תכין לי דוח כספי לשנת 2025"
    finally:
        db.close()


def test_a_normal_reply_does_not_create_a_gap(fresh_org):
    iso = fresh_org()
    org_id = iso["org_id"]
    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.organization_id == org_id).first().id
        svc = _service(db, org_id, user_id)
        svc._capture_gap_if_giveup(
            session_id="s1", message_id=None,
            question="מה המע\"מ ליולי?",
            final_text="דוח המע\"מ ליולי מוכן: עסקאות 0, תשומות 3,200 ש\"ח.",
        )
        db.commit()
        assert db.query(MoshkoGap).filter(
            MoshkoGap.organization_id == org_id,
        ).count() == 0
    finally:
        db.close()


def test_unknown_feedback_creates_a_user_flagged_gap(client, fresh_org):
    iso = fresh_org()
    org_id = iso["org_id"]
    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.organization_id == org_id).first().id
        _, assistant = _seed_exchange(db, org_id, user_id)
        assistant_id = assistant.id
    finally:
        db.close()

    r = client.post(
        f"/api/ai/chat/{assistant_id}/feedback",
        json={"category": "unknown", "comment": "הוא לא ידע לענות"},
        headers=iso["headers"],
    )
    assert r.status_code == 201, r.text

    db = SessionLocal()
    try:
        gap = db.query(MoshkoGap).filter(MoshkoGap.organization_id == org_id).first()
        assert gap is not None and gap.gap_kind == "user_flagged"
        assert gap.message_id == assistant_id
    finally:
        db.close()


def test_admin_lists_answers_and_promotes_a_gap(client, super_admin, fresh_org):
    iso = fresh_org()
    org_id = iso["org_id"]
    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.organization_id == org_id).first().id
        db.add(MoshkoGap(
            organization_id=org_id, user_id=user_id, session_id="s9",
            question="תכין דוח שנתי", answer="לא הצלחתי",
            gap_kind="model_gave_up", status="open",
        ))
        db.commit()
    finally:
        db.close()

    listing = client.get(
        "/api/admin/moshko/gaps", params={"status": "open"},
        headers=super_admin["headers"],
    )
    assert listing.status_code == 200
    rows = listing.json()["gaps"]
    target = next(g for g in rows if g["organization_id"] == org_id)

    patch = client.patch(
        f"/api/admin/moshko/gaps/{target['id']}",
        json={
            "status": "answered",
            "resolution": "דוח שנתי מפיקים דרך prepare_vat_filing + get_pnl לתקופה.",
            "promote_to_memory": True,
        },
        headers=super_admin["headers"],
    )
    assert patch.status_code == 200, patch.text

    db = SessionLocal()
    try:
        gap = db.query(MoshkoGap).filter(MoshkoGap.organization_id == org_id).first()
        assert gap.status == "answered"
        assert gap.promoted_memory_id is not None
        memory = db.query(MoshkoMemory).filter(
            MoshkoMemory.id == gap.promoted_memory_id,
        ).first()
        assert memory is not None
        assert memory.approved_at is not None
        db.query(MoshkoMemory).filter(
            MoshkoMemory.id == gap.promoted_memory_id,
        ).delete()
        db.commit()
    finally:
        db.close()


def test_gap_routes_require_super_admin(client, fresh_org):
    iso = fresh_org()
    r = client.get("/api/admin/moshko/gaps", headers=iso["headers"])
    assert r.status_code in (401, 403)


def test_regression_duplicate_cleanup_is_scoped_to_org_and_user(
    monkeypatch, fresh_org,
):
    from cfo.services import moshko_regression

    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        user_a = db.query(User).filter(User.organization_id == org_a).first()
        user_b = db.query(User).filter(User.organization_id == org_b).first()
        other_a = User(
            organization_id=org_a,
            email=f"gap-other-{org_a}@example.com",
            password_hash="unused",
            full_name="Other",
            role=UserRole.USER,
            is_active=True,
        )
        db.add(other_a)
        db.flush()
        memory = MoshkoMemory(
            organization_id=org_a,
            user_id=None,
            content="תשובה מאושרת",
            category="correction",
            source="admin",
            approved_at=datetime.utcnow(),
        )
        db.add(memory)
        db.flush()
        original = MoshkoGap(
            organization_id=org_a,
            user_id=user_a.id,
            session_id="original",
            question="שאלה",
            answer="לא הצלחתי",
            gap_kind="model_gave_up",
            status="answered",
            promoted_memory_id=memory.id,
        )
        db.add(original)
        db.commit()
        db.refresh(original)
        regression_session = f"regression-{original.id}-deadbeef"
        colliders = [
            MoshkoGap(
                organization_id=org_b,
                user_id=user_b.id,
                session_id=regression_session,
                gap_kind="model_gave_up",
                status="open",
            ),
            MoshkoGap(
                organization_id=org_a,
                user_id=other_a.id,
                session_id=regression_session,
                gap_kind="model_gave_up",
                status="open",
            ),
        ]
        db.add_all(colliders)
        db.commit()
        collider_ids = [row.id for row in colliders]

        class _FixedUuid:
            hex = "deadbeef000000000000000000000000"

        monkeypatch.setattr(moshko_regression.uuid, "uuid4", lambda: _FixedUuid())

        async def fake_send(self, session_id, text, persona=None):
            db.add(MoshkoGap(
                organization_id=self.organization_id,
                user_id=self.user_id,
                session_id=session_id,
                gap_kind="model_gave_up",
                status="open",
            ))
            db.flush()
            return {"reply": "לא הצלחתי"}

        monkeypatch.setattr(moshko_regression.AIChatService, "send_message", fake_send)
        asyncio.run(moshko_regression._run_one_case(db, original))
        db.flush()

        assert db.query(MoshkoGap).filter(
            MoshkoGap.organization_id == org_a,
            MoshkoGap.user_id == user_a.id,
            MoshkoGap.session_id == regression_session,
        ).count() == 0
        assert db.query(MoshkoGap).filter(MoshkoGap.id.in_(collider_ids)).count() == 2
    finally:
        db.close()
