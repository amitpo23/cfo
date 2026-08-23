"""Offline TDD contract for Moshko observability and admin inspection."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from cfo.auth import create_access_token
from cfo.config import settings
from cfo.database import SessionLocal
from cfo.models import ChatMessage, LLMUsage, MoshkoToolCall, User, UserRole
from cfo.services import ai_chat_service, vision_extractor
from cfo.services.ai_chat_service import AIChatService
from cfo.services.ai_chat_tools import TOOLS, tool_target_system
from cfo.services.moshko_observability import redact_tool_arguments


def _text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _tool_block(name: str, arguments: dict):
    return SimpleNamespace(type="tool_use", id=f"call-{name}", name=name, input=arguments)


def _response(*blocks, stop_reason="end_turn", usage=None):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=list(blocks),
        usage=usage or SimpleNamespace(input_tokens=10, output_tokens=5),
    )


class _FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)

    async def create(self, **_kwargs):
        return self.responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


def _patch_client(monkeypatch, responses):
    client = _FakeClient(responses)
    monkeypatch.setattr(AIChatService, "_make_client", lambda _self: client)
    return client


@pytest.fixture
def moshko_super_admin(client, fresh_org):
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
    finally:
        db.close()
    return {"headers": {"Authorization": f"Bearer {token}"}, "user_id": user.id}


def test_every_llm_turn_records_usage_and_configured_cost(monkeypatch, fresh_org):
    iso = fresh_org()
    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.organization_id == iso["org_id"]).first().id
        monkeypatch.setattr(settings, "ai_chat_model", "priced-test-model")
        monkeypatch.setattr(
            settings,
            "llm_pricing_json",
            '{"priced-test-model":{"input_per_million_usd":"2",'
            '"output_per_million_usd":"8","cache_read_per_million_usd":"1",'
            '"cache_creation_per_million_usd":"3"}}',
        )
        usage = SimpleNamespace(
            input_tokens=100, output_tokens=20,
            cache_read_input_tokens=10, cache_creation_input_tokens=5,
        )
        _patch_client(monkeypatch, [
            _response(_tool_block("get_ar_aging", {}), stop_reason="tool_use", usage=usage),
            _response(_text_block("בוצע"), usage=usage),
        ])

        result = asyncio.run(AIChatService(db, iso["org_id"], user_id).send_message("wa-1", "מצב?"))
        assert result["reply"] == "בוצע"

        rows = db.query(LLMUsage).filter(LLMUsage.session_id == "wa-1").order_by(LLMUsage.id).all()
        assert len(rows) == 2
        assert all(row.provider == "anthropic" and row.purpose == "chat" for row in rows)
        assert rows[0].input_tokens == 100
        assert rows[0].cache_read_input_tokens == 10
        assert rows[0].cache_creation_input_tokens == 5
        assert rows[0].cost_usd == Decimal("0.00038500")
    finally:
        db.close()


def test_unknown_model_cost_is_honest_null(monkeypatch, fresh_org):
    iso = fresh_org()
    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.organization_id == iso["org_id"]).first().id
        monkeypatch.setattr(settings, "ai_chat_model", "unknown-model")
        monkeypatch.setattr(settings, "llm_pricing_json", "{}")
        _patch_client(monkeypatch, [_response(_text_block("שלום"))])
        asyncio.run(AIChatService(db, iso["org_id"], user_id).send_message("s-null", "שלום"))
        row = db.query(LLMUsage).filter(LLMUsage.session_id == "s-null").one()
        assert row.cost_usd is None
    finally:
        db.close()


def test_usage_logging_failure_never_breaks_conversation(monkeypatch, fresh_org):
    iso = fresh_org()
    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.organization_id == iso["org_id"]).first().id
        _patch_client(monkeypatch, [_response(_text_block("השיחה ממשיכה"))])
        monkeypatch.setattr(
            ai_chat_service,
            "record_llm_usage_best_effort",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("log unavailable")),
        )
        result = asyncio.run(AIChatService(db, iso["org_id"], user_id).send_message("s-best", "היי"))
        assert result["reply"] == "השיחה ממשיכה"
        assert db.query(ChatMessage).filter(ChatMessage.session_id == "s-best").count() == 2
    finally:
        db.close()


def test_read_tool_success_is_logged_with_redacted_arguments(monkeypatch, fresh_org):
    iso = fresh_org()
    db = SessionLocal()
    original = TOOLS["query_bank_transactions"]

    async def fake_tool(_db, _org, **_kwargs):
        return {"transactions": [1, 2, 3]}

    try:
        user_id = db.query(User).filter(User.organization_id == iso["org_id"]).first().id
        TOOLS["query_bank_transactions"] = replace(original, fn=fake_tool)
        secret = "sk-live-plain-secret"
        bank_account = "IL620108000000099999999"
        _patch_client(monkeypatch, [
            _response(
                _tool_block("query_bank_transactions", {
                    "api_key": secret,
                    "bank_account": bank_account,
                    "search": f"בדוק {bank_account}",
                }),
                stop_reason="tool_use",
            ),
            _response(_text_block("מצאתי")),
        ])
        asyncio.run(AIChatService(db, iso["org_id"], user_id).send_message("wa-tools", "בדוק"))

        row = db.query(MoshkoToolCall).filter(MoshkoToolCall.session_id == "wa-tools").one()
        assert row.tool_name == "query_bank_transactions"
        assert row.target_system == "rezef_db"
        assert row.succeeded is True
        assert row.duration_ms >= 0
        assert row.result_size_bytes > 0
        assert secret not in str(row.arguments)
        assert bank_account not in str(row.arguments)
        assert row.message_id is not None
    finally:
        TOOLS["query_bank_transactions"] = original
        db.close()


def test_tool_failure_is_logged_and_returned_to_model(monkeypatch, fresh_org):
    iso = fresh_org()
    db = SessionLocal()
    original = TOOLS["get_ar_aging"]

    async def failing_tool(_db, _org, **_kwargs):
        raise RuntimeError("provider exploded")

    try:
        user_id = db.query(User).filter(User.organization_id == iso["org_id"]).first().id
        TOOLS["get_ar_aging"] = replace(original, fn=failing_tool)
        _patch_client(monkeypatch, [
            _response(_tool_block("get_ar_aging", {}), stop_reason="tool_use"),
            _response(_text_block("לא הצלחתי לקרוא את הנתונים")),
        ])
        result = asyncio.run(AIChatService(db, iso["org_id"], user_id).send_message("s-fail", "מצב?"))
        assert "לא הצלחתי" in result["reply"]
        row = db.query(MoshkoToolCall).filter(MoshkoToolCall.session_id == "s-fail").one()
        assert row.succeeded is False
        assert "provider exploded" in row.error
    finally:
        TOOLS["get_ar_aging"] = original
        db.close()


def test_confirmed_write_tool_is_logged_against_implemented_target(monkeypatch, fresh_org):
    iso = fresh_org()
    db = SessionLocal()
    original = TOOLS["issue_document"]
    calls = []

    async def fake_write(_db, _org, **kwargs):
        calls.append(kwargs)
        return {"document_id": 7}

    try:
        user_id = db.query(User).filter(User.organization_id == iso["org_id"]).first().id
        TOOLS["issue_document"] = replace(original, fn=fake_write)
        args = {"document_type": "invoice", "customer_id": "1", "customer_name": "א", "items": []}
        _patch_client(monkeypatch, [_response(_tool_block("issue_document", args), stop_reason="tool_use")])
        pending = asyncio.run(AIChatService(db, iso["org_id"], user_id).send_message("s-write", "הפק"))
        assert db.query(MoshkoToolCall).filter(MoshkoToolCall.session_id == "s-write").count() == 0

        asyncio.run(AIChatService(db, iso["org_id"], user_id).confirm_action(pending["message_id"]))
        row = db.query(MoshkoToolCall).filter(MoshkoToolCall.session_id == "s-write").one()
        assert row.tool_name == "issue_document"
        assert row.target_system == "sumit"
        assert row.succeeded is True
        assert len(calls) == 1
    finally:
        TOOLS["issue_document"] = original
        db.close()


def test_tool_target_mapping_is_explicit_for_all_registered_tools():
    assert {tool_target_system(name) for name in TOOLS} <= {
        "sumit", "open_finance", "rezef_db", "local",
    }
    assert tool_target_system("connect_bank_account") == "open_finance"
    assert tool_target_system("query_bank_transactions") == "rezef_db"
    assert tool_target_system("rezef_help") == "local"


def test_redaction_masks_nested_secrets_and_bank_details():
    raw = {
        "password": "VisiblePass!",
        "nested": {"access_token": "abc123", "account_number": "123456789"},
        "note": "IBAN IL620108000000099999999 and card 4580458045804580",
        "safe": "keep me",
    }
    redacted = redact_tool_arguments(raw)
    rendered = str(redacted)
    for value in ("VisiblePass!", "abc123", "123456789", "IL620108000000099999999", "4580458045804580"):
        assert value not in rendered
    assert redacted["safe"] == "keep me"


def test_anthropic_vision_usage_is_recorded(monkeypatch, fresh_org):
    iso = fresh_org()
    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.organization_id == iso["org_id"]).first().id
        message = _response(
            _text_block('{"supplier_name":"א","amount_total":10,"confidence":1,"is_readable":true}'),
            usage=SimpleNamespace(input_tokens=30, output_tokens=12),
        )
        fake_module = SimpleNamespace(AsyncAnthropic=lambda **_kwargs: _FakeClient([message]))
        monkeypatch.setitem(sys.modules, "anthropic", fake_module)
        monkeypatch.setattr(settings, "anthropic_api_key", "offline-test-key")
        asyncio.run(vision_extractor.extract_receipt(
            b"image", "image/png", user_initiated=True,
            db=db, organization_id=iso["org_id"], user_id=user_id, session_id="wa-vision",
        ))
        row = db.query(LLMUsage).filter(LLMUsage.session_id == "wa-vision").one()
        assert row.provider == "anthropic"
        assert row.purpose == "vision"
        assert row.input_tokens == 30
    finally:
        db.close()


def _seed_admin_data(org_id: int, user_id: int, session_id: str):
    db = SessionLocal()
    try:
        db.add_all([
            ChatMessage(organization_id=org_id, user_id=user_id, session_id=session_id, role="user", content="שאלה"),
            ChatMessage(organization_id=org_id, user_id=user_id, session_id=session_id, role="assistant", content="תשובה"),
            LLMUsage(
                organization_id=org_id, user_id=user_id, session_id=session_id,
                provider="anthropic", model="test-model", input_tokens=10,
                output_tokens=5, cost_usd=Decimal("0.01000000"), purpose="chat",
            ),
            MoshkoToolCall(
                organization_id=org_id, user_id=user_id, session_id=session_id,
                tool_name="get_ar_aging", target_system="rezef_db", arguments={},
                succeeded=True, duration_ms=1, result_size_bytes=2,
            ),
        ])
        db.commit()
    finally:
        db.close()


@pytest.mark.parametrize("path", [
    "/api/admin/moshko/conversations",
    "/api/admin/moshko/tool-calls",
    "/api/admin/moshko/usage",
])
def test_observability_routes_require_super_admin(client, owner, path):
    response = client.get(path, headers=owner["headers"])
    assert response.status_code == 403


def test_admin_conversations_transcript_filters_and_org_isolation(
    client, moshko_super_admin, fresh_org,
):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        user_a = db.query(User).filter(User.organization_id == org_a).first().id
        user_b = db.query(User).filter(User.organization_id == org_b).first().id
    finally:
        db.close()
    _seed_admin_data(org_a, user_a, "wa-972500000001")
    _seed_admin_data(org_b, user_b, "tg-2002")

    response = client.get(
        f"/api/admin/moshko/conversations?organization_id={org_a}&channel=whatsapp",
        headers=moshko_super_admin["headers"],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["session_id"] == "wa-972500000001"
    assert body["items"][0]["channel"] == "whatsapp"
    assert all(item["organization_id"] == org_a for item in body["items"])

    transcript = client.get(
        "/api/admin/moshko/conversations/wa-972500000001",
        headers=moshko_super_admin["headers"],
    )
    assert transcript.status_code == 200, transcript.text
    assert [m["content"] for m in transcript.json()["messages"]] == ["שאלה", "תשובה"]


def test_admin_conversations_listing_excludes_regression_sessions_but_transcript_still_works(
    client, moshko_super_admin, fresh_org,
):
    """moshko_regression.py seeds ChatMessage rows under session ids
    `regression-{gap_id}-{hex}` — synthetic training traffic, not a real
    conversation. It must not pollute the human /moshko/conversations
    listing, but the session must stay queryable directly (transcript
    endpoint, tool-calls, usage) — the exclusion is scoped to the listing
    only."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.organization_id == org_id).first().id
    finally:
        db.close()
    _seed_admin_data(org_id, user_id, "wa-real-session")
    _seed_admin_data(org_id, user_id, "regression-42-a1b2c3d4")

    response = client.get(
        f"/api/admin/moshko/conversations?organization_id={org_id}",
        headers=moshko_super_admin["headers"],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    session_ids = [item["session_id"] for item in body["items"]]
    assert "wa-real-session" in session_ids
    assert "regression-42-a1b2c3d4" not in session_ids
    assert body["total"] == 1

    # ... but the regression session stays queryable directly.
    transcript = client.get(
        "/api/admin/moshko/conversations/regression-42-a1b2c3d4",
        headers=moshko_super_admin["headers"],
    )
    assert transcript.status_code == 200, transcript.text
    assert len(transcript.json()["messages"]) == 2

    tool_calls = client.get(
        f"/api/admin/moshko/tool-calls?organization_id={org_id}",
        headers=moshko_super_admin["headers"],
    )
    assert tool_calls.status_code == 200
    assert any(
        item["session_id"] == "regression-42-a1b2c3d4" for item in tool_calls.json()["items"]
    )


def test_admin_tool_calls_and_usage_are_filterable_and_paginated(
    client, moshko_super_admin, fresh_org,
):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.organization_id == org_id).first().id
    finally:
        db.close()
    _seed_admin_data(org_id, user_id, "wa-admin-filter")

    tools = client.get(
        f"/api/admin/moshko/tool-calls?organization_id={org_id}&target_system=rezef_db&succeeded=true&limit=1",
        headers=moshko_super_admin["headers"],
    )
    assert tools.status_code == 200, tools.text
    assert tools.json()["total"] == 1
    assert len(tools.json()["items"]) == 1

    usage = client.get(
        f"/api/admin/moshko/usage?organization_id={org_id}&group_by=model",
        headers=moshko_super_admin["headers"],
    )
    assert usage.status_code == 200, usage.text
    body = usage.json()
    assert body["summary"]["input_tokens"] == 10
    assert body["summary"]["output_tokens"] == 5
    assert body["summary"]["cost_usd"] == pytest.approx(0.01)
    assert body["groups"][0]["model"] == "test-model"


def _seed_feedback_message(org_id: int, user_id: int, session_id: str) -> int:
    db = SessionLocal()
    try:
        db.add(ChatMessage(
            organization_id=org_id,
            user_id=user_id,
            session_id=session_id,
            role="user",
            content="מה היתרה בבנק?",
        ))
        answer = ChatMessage(
            organization_id=org_id,
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content="אין לי מידע מספיק.",
        )
        db.add(answer)
        db.commit()
        db.refresh(answer)
        return answer.id
    finally:
        db.close()


def test_user_can_flag_only_their_own_org_scoped_assistant_answer(client, fresh_org):
    org_a = fresh_org()
    org_b = fresh_org()
    db = SessionLocal()
    try:
        user_a = db.query(User).filter(User.organization_id == org_a["org_id"]).first().id
        user_b = db.query(User).filter(User.organization_id == org_b["org_id"]).first().id
    finally:
        db.close()
    message_a = _seed_feedback_message(org_a["org_id"], user_a, "feedback-a")
    message_b = _seed_feedback_message(org_b["org_id"], user_b, "feedback-b")

    created = client.post(
        f"/api/ai/chat/{message_a}/feedback",
        headers=org_a["headers"],
        json={"category": "unknown", "comment": "המידע כן קיים בחיבור הבנק"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["organization_id"] == org_a["org_id"]
    assert created.json()["status"] == "open"

    cross_org = client.post(
        f"/api/ai/chat/{message_b}/feedback",
        headers=org_a["headers"],
        json={"category": "inaccurate"},
    )
    assert cross_org.status_code == 404


def test_feedback_rejects_user_messages_and_unknown_categories(client, fresh_org):
    org = fresh_org()
    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.organization_id == org["org_id"]).first().id
        question = ChatMessage(
            organization_id=org["org_id"], user_id=user_id,
            session_id="feedback-invalid", role="user", content="שאלה",
        )
        db.add(question)
        db.commit()
        db.refresh(question)
        question_id = question.id
    finally:
        db.close()

    assert client.post(
        f"/api/ai/chat/{question_id}/feedback",
        headers=org["headers"], json={"category": "unknown"},
    ).status_code == 400
    assert client.post(
        f"/api/ai/chat/{question_id}/feedback",
        headers=org["headers"], json={"category": "invented"},
    ).status_code == 400


def test_super_admin_quality_queue_is_filterable_and_regular_admin_is_blocked(
    client, moshko_super_admin, fresh_org,
):
    org = fresh_org()
    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.organization_id == org["org_id"]).first().id
    finally:
        db.close()
    message_id = _seed_feedback_message(org["org_id"], user_id, "feedback-queue")
    assert client.post(
        f"/api/ai/chat/{message_id}/feedback", headers=org["headers"],
        json={"category": "inaccurate", "comment": "הסכום שגוי"},
    ).status_code == 201

    assert client.get(
        "/api/admin/moshko/feedback", headers=org["headers"],
    ).status_code == 403
    response = client.get(
        f"/api/admin/moshko/feedback?organization_id={org['org_id']}&status=open",
        headers=moshko_super_admin["headers"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    item = response.json()["items"][0]
    assert item["question"] == "מה היתרה בבנק?"
    assert item["answer"] == "אין לי מידע מספיק."


def test_super_admin_correction_promotes_only_org_scoped_approved_memory_and_audits(
    client, moshko_super_admin, fresh_org,
):
    from cfo.models import AuditLog, MoshkoFeedback, MoshkoMemory

    org = fresh_org()
    other = fresh_org()
    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.organization_id == org["org_id"]).first().id
    finally:
        db.close()
    message_id = _seed_feedback_message(org["org_id"], user_id, "feedback-promote")
    feedback = client.post(
        f"/api/ai/chat/{message_id}/feedback", headers=org["headers"],
        json={"category": "unknown"},
    ).json()

    corrected = client.patch(
        f"/api/admin/moshko/feedback/{feedback['id']}",
        headers=moshko_super_admin["headers"],
        json={
            "correction": "יתרת הבנק נקראת רק מחשבונות Open Finance של הארגון הפעיל.",
            "status": "resolved",
            "promote_to_memory": True,
        },
    )
    assert corrected.status_code == 200, corrected.text

    db = SessionLocal()
    try:
        row = db.query(MoshkoFeedback).filter(MoshkoFeedback.id == feedback["id"]).one()
        memory = db.query(MoshkoMemory).filter(MoshkoMemory.id == row.promoted_memory_id).one()
        assert memory.organization_id == org["org_id"]
        assert memory.organization_id != other["org_id"]
        assert memory.user_id is None
        assert memory.category == "correction"
        assert memory.approved_at is not None
        assert db.query(AuditLog).filter(
            AuditLog.action == "MOSHKO_FEEDBACK_REVIEW",
            AuditLog.organization_id == org["org_id"],
            AuditLog.entity_id == row.id,
        ).count() == 1
    finally:
        db.close()
