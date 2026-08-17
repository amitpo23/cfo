"""Offline TDD contracts for Moshko knowledge, memory and task management."""
from __future__ import annotations

import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from cfo.auth import create_access_token
from cfo.database import SessionLocal
from cfo.models import (
    Alert,
    AlertSeverity,
    AuditLog,
    MoshkoMemory,
    MoshkoToolCall,
    Organization,
    Task,
    TaskStatus,
    User,
    UserRole,
)
from cfo.services.ai_chat_service import AIChatService
from cfo.services.ai_chat_tools import TOOLS, tool_target_system


ISRAEL = ZoneInfo("Asia/Jerusalem")


def _headers(user_id: int) -> dict[str, str]:
    token = create_access_token({"sub": str(user_id)})
    return {"Authorization": f"Bearer {token}"}


def _user_for_org(org_id: int) -> User:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.organization_id == org_id).first()
    finally:
        db.close()


def _add_user(org_id: int, *, role: UserRole, suffix: str) -> tuple[int, dict[str, str]]:
    db = SessionLocal()
    try:
        row = User(
            organization_id=org_id,
            email=f"moshko-stage3-{suffix}@example.com",
            password_hash="not-used",
            full_name=f"Stage 3 {suffix}",
            role=role,
            is_active=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id, _headers(row.id)
    finally:
        db.close()


@pytest.fixture
def stage3_super_admin(client, fresh_org):
    actor = fresh_org()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.organization_id == actor["org_id"]).first()
        user.role = UserRole.SUPER_ADMIN
        db.commit()
        return {"id": user.id, "headers": _headers(user.id)}
    finally:
        db.close()


def _seed_memories(org_id: int, own_user_id: int, other_user_id: int) -> dict[str, int]:
    db = SessionLocal()
    try:
        rows = {
            "org": MoshkoMemory(
                organization_id=org_id,
                user_id=None,
                content="העסק מעדיף חשבוניות דיגיטליות",
                category="preference",
                source="conversation",
            ),
            "own": MoshkoMemory(
                organization_id=org_id,
                user_id=own_user_id,
                content="המשתמש מעדיף תשובות קצרות",
                category="preference",
                source="inferred",
            ),
            "other": MoshkoMemory(
                organization_id=org_id,
                user_id=other_user_id,
                content="זיכרון אישי חסוי של משתמש אחר",
                category="business_fact",
                source="conversation",
            ),
        }
        db.add_all(rows.values())
        db.commit()
        return {key: row.id for key, row in rows.items()}
    finally:
        db.close()


def test_memory_model_has_human_approval_fields():
    assert hasattr(MoshkoMemory, "approved_at")
    assert hasattr(MoshkoMemory, "approved_by")


def test_memory_routes_reject_non_admin(client, fresh_org):
    org = fresh_org()
    _, headers = _add_user(org["org_id"], role=UserRole.USER, suffix="plain-user")
    assert client.get("/api/admin/moshko/memory", headers=headers).status_code == 403
    assert client.post(
        "/api/admin/moshko/memory",
        headers=headers,
        json={"organization_id": org["org_id"], "content": "אסור"},
    ).status_code == 403


def test_org_admin_sees_shared_and_own_memory_but_not_another_users(
    client, fresh_org,
):
    org = fresh_org()
    admin = _user_for_org(org["org_id"])
    other_id, _ = _add_user(org["org_id"], role=UserRole.USER, suffix="private-peer")
    ids = _seed_memories(org["org_id"], admin.id, other_id)

    response = client.get("/api/admin/moshko/memory", headers=org["headers"])

    assert response.status_code == 200, response.text
    visible = {row["id"] for row in response.json()["items"]}
    assert visible == {ids["org"], ids["own"]}
    assert "זיכרון אישי חסוי" not in response.text

    forbidden_filter = client.get(
        f"/api/admin/moshko/memory?user_id={other_id}", headers=org["headers"],
    )
    assert forbidden_filter.status_code == 403


def test_org_admin_cannot_read_or_mutate_another_organization_memory(
    client, fresh_org,
):
    org_a = fresh_org()
    org_b = fresh_org()
    user_b = _user_for_org(org_b["org_id"])
    ids = _seed_memories(org_b["org_id"], user_b.id, user_b.id)

    listing = client.get(
        f"/api/admin/moshko/memory?organization_id={org_b['org_id']}",
        headers=org_a["headers"],
    )
    assert listing.status_code == 403
    assert client.patch(
        f"/api/admin/moshko/memory/{ids['org']}",
        headers=org_a["headers"],
        json={"content": "דליפה"},
    ).status_code == 404
    assert client.delete(
        f"/api/admin/moshko/memory/{ids['org']}", headers=org_a["headers"],
    ).status_code == 404


def test_super_admin_can_filter_all_memory_without_personal_data_leak(
    client, stage3_super_admin, fresh_org,
):
    org = fresh_org()
    owner = _user_for_org(org["org_id"])
    other_id, _ = _add_user(org["org_id"], role=UserRole.USER, suffix="super-visible")
    ids = _seed_memories(org["org_id"], owner.id, other_id)

    # סופר-אדמין חייב לבחור ארגון מפורשות מ-11/08/2026.
    response = client.get(
        f"/api/admin/moshko/memory?organization_id={org['org_id']}&user_id={other_id}",
        headers={**stage3_super_admin["headers"],
                 "X-Active-Org-Id": str(org["org_id"])},
    )

    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()["items"]] == [ids["other"]]


def test_manual_memory_crud_is_approved_and_audited(client, fresh_org):
    org = fresh_org()
    admin = _user_for_org(org["org_id"])

    created = client.post(
        "/api/admin/moshko/memory",
        headers=org["headers"],
        json={
            "organization_id": org["org_id"],
            "content": "  שולחים דוחות ביום ראשון  ",
            "category": "convention",
            "user_id": admin.id,
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["source"] == "admin"
    assert row["content"] == "שולחים דוחות ביום ראשון"
    assert row["approved_at"] is not None
    assert row["approved_by"] == admin.id

    filtered = client.get(
        "/api/admin/moshko/memory?category=convention&source=admin",
        headers=org["headers"],
    )
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()["items"]] == [row["id"]]

    updated = client.patch(
        f"/api/admin/moshko/memory/{row['id']}",
        headers=org["headers"],
        json={"content": "שולחים דוחות ביום שני", "category": "correction", "approved": False},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["approved_at"] is None

    db = SessionLocal()
    try:
        audit = db.query(AuditLog).filter(
            AuditLog.action == "MOSHKO_MEMORY_UPDATE",
            AuditLog.entity_id == row["id"],
        ).one()
        assert audit.organization_id == org["org_id"]
        assert audit.details["old"]["content"] == "שולחים דוחות ביום ראשון"
        assert audit.details["new"]["content"] == "שולחים דוחות ביום שני"
    finally:
        db.close()

    deleted = client.delete(
        f"/api/admin/moshko/memory/{row['id']}", headers=org["headers"],
    )
    assert deleted.status_code == 200, deleted.text
    db = SessionLocal()
    try:
        assert db.query(MoshkoMemory).filter(MoshkoMemory.id == row["id"]).first() is None
        audit = db.query(AuditLog).filter(
            AuditLog.action == "MOSHKO_MEMORY_DELETE",
            AuditLog.entity_id == row["id"],
        ).one()
        assert audit.details["old"]["content"] == "שולחים דוחות ביום שני"
        assert audit.details["new"] is None
    finally:
        db.close()


def test_memory_create_rejects_cross_org_personal_owner(client, fresh_org):
    org_a = fresh_org()
    org_b = fresh_org()
    foreign_user = _user_for_org(org_b["org_id"])
    response = client.post(
        "/api/admin/moshko/memory",
        headers=org_a["headers"],
        json={
            "organization_id": org_a["org_id"],
            "user_id": foreign_user.id,
            "content": "אסור לשייך למשתמש זר",
            "category": "business_fact",
        },
    )
    assert response.status_code == 403


def _text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _tool_block(name: str, arguments: dict):
    return SimpleNamespace(type="tool_use", id=f"stage3-{name}", name=name, input=arguments)


def _response(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=list(blocks),
        usage=SimpleNamespace(input_tokens=3, output_tokens=2),
    )


class _Messages:
    def __init__(self, responses):
        self.responses = list(responses)

    async def create(self, **_kwargs):
        return self.responses.pop(0)


class _Client:
    def __init__(self, responses):
        self.messages = _Messages(responses)


def _patch_ai(monkeypatch, responses):
    fake = _Client(responses)
    monkeypatch.setattr(AIChatService, "_make_client", lambda _self: fake)


def test_task_tools_are_registered_with_confirmation_and_rezef_db_target():
    assert TOOLS["create_task"].category == "write"
    assert TOOLS["list_tasks"].category == "read"
    assert TOOLS["update_task"].category == "write"
    assert tool_target_system("create_task") == "rezef_db"
    assert tool_target_system("list_tasks") == "rezef_db"
    assert tool_target_system("update_task") == "rezef_db"


def test_create_task_waits_for_confirmation_parses_hebrew_date_and_links_alert(
    monkeypatch, fresh_org,
):
    org = fresh_org()
    user = _user_for_org(org["org_id"])
    db = SessionLocal()
    try:
        alert = Alert(
            organization_id=org["org_id"],
            alert_type="supplier_payment",
            severity=AlertSeverity.WARNING,
            title="תשלום לספק",
            entity_type="bill",
            entity_id=777,
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)

        from cfo.services import moshko_tasks
        monkeypatch.setattr(
            moshko_tasks,
            "israel_now",
            lambda: datetime(2026, 8, 1, 10, 0, tzinfo=ISRAEL),
        )
        args = {
            "title": "לשלם לספק",
            "description": "לפי בקשת הלקוח",
            "due_date": "מחר",
            "alert_id": alert.id,
        }
        _patch_ai(monkeypatch, [
            _response(_tool_block("create_task", args), stop_reason="tool_use"),
        ])
        pending = asyncio.run(
            AIChatService(db, org["org_id"], user.id).send_message("wa-task", "תזכיר לי מחר")
        )
        assert pending["pending_action"]["tool"] == "create_task"
        assert db.query(Task).filter(Task.organization_id == org["org_id"]).count() == 0

        confirmed = asyncio.run(
            AIChatService(db, org["org_id"], user.id).confirm_action(pending["message_id"])
        )
        task = db.query(Task).filter(Task.organization_id == org["org_id"]).one()
        assert task.due_date == date(2026, 8, 2)
        assert task.alert_id == alert.id
        assert task.entity_type == "bill"
        assert task.entity_id == 777
        assert confirmed["result"]["status"] == "open"
        log = db.query(MoshkoToolCall).filter(MoshkoToolCall.session_id == "wa-task").one()
        assert log.tool_name == "create_task"
        assert log.target_system == "rezef_db"
    finally:
        db.close()


def test_task_date_parser_handles_bare_day_and_invalid_dates(monkeypatch):
    from cfo.services import moshko_tasks

    monkeypatch.setattr(
        moshko_tasks,
        "israel_now",
        lambda: datetime(2026, 8, 20, 10, 0, tzinfo=ISRAEL),
    )
    assert moshko_tasks.parse_due_date("ב-15") == date(2026, 9, 15)
    assert moshko_tasks.parse_due_date("2026-09-03") == date(2026, 9, 3)
    with pytest.raises(ValueError, match="תאריך יעד"):
        moshko_tasks.parse_due_date("כשיהיה זמן")


def test_list_and_update_task_are_org_scoped_and_update_requires_confirmation(
    monkeypatch, fresh_org,
):
    org_a = fresh_org()
    org_b = fresh_org()
    user_a = _user_for_org(org_a["org_id"])
    db = SessionLocal()
    try:
        own = Task(
            organization_id=org_a["org_id"], title="משימה פתוחה",
            status=TaskStatus.OPEN, due_date=date(2026, 8, 15),
        )
        foreign = Task(
            organization_id=org_b["org_id"], title="משימה זרה",
            status=TaskStatus.OPEN, due_date=date(2026, 8, 15),
        )
        db.add_all([own, foreign])
        db.commit()
        db.refresh(own)

        _patch_ai(monkeypatch, [
            _response(_tool_block("list_tasks", {"status": "open"}), stop_reason="tool_use"),
            _response(_text_block("מצאתי משימה אחת")),
        ])
        result = asyncio.run(
            AIChatService(db, org_a["org_id"], user_a.id).send_message("tg-task-list", "מה פתוח?")
        )
        assert result["reply"] == "מצאתי משימה אחת"
        read_log = db.query(MoshkoToolCall).filter(
            MoshkoToolCall.session_id == "tg-task-list",
        ).one()
        assert read_log.target_system == "rezef_db"

        direct = asyncio.run(TOOLS["list_tasks"].fn(db, org_a["org_id"], status="open"))
        assert [row["title"] for row in direct["tasks"]] == ["משימה פתוחה"]
        outside_range = asyncio.run(TOOLS["list_tasks"].fn(
            db,
            org_a["org_id"],
            due_from="2026-08-16",
            due_to="2026-08-31",
        ))
        assert outside_range["tasks"] == []

        update_args = {"task_id": own.id, "status": "done", "due_date": "2026-08-20"}
        _patch_ai(monkeypatch, [
            _response(_tool_block("update_task", update_args), stop_reason="tool_use"),
        ])
        pending = asyncio.run(
            AIChatService(db, org_a["org_id"], user_a.id).send_message("wa-task-update", "סמן שבוצע")
        )
        db.refresh(own)
        assert own.status == TaskStatus.OPEN
        asyncio.run(AIChatService(db, org_a["org_id"], user_a.id).confirm_action(pending["message_id"]))
        db.refresh(own)
        assert own.status == TaskStatus.DONE
        assert own.due_date == date(2026, 8, 20)

        with pytest.raises(ValueError, match="לא נמצאה"):
            asyncio.run(TOOLS["update_task"].fn(
                db, org_a["org_id"], task_id=foreign.id, status="done",
            ))
    finally:
        db.close()


def test_task_alert_link_rejects_alert_from_another_org(fresh_org):
    org_a = fresh_org()
    org_b = fresh_org()
    db = SessionLocal()
    try:
        alert = Alert(
            organization_id=org_b["org_id"], alert_type="foreign",
            severity=AlertSeverity.WARNING, title="זר",
        )
        db.add(alert)
        db.commit()
        with pytest.raises(ValueError, match="התראה"):
            asyncio.run(TOOLS["create_task"].fn(
                db, org_a["org_id"], title="אסור", alert_id=alert.id,
            ))
        assert db.query(Task).filter(Task.organization_id == org_a["org_id"]).count() == 0
    finally:
        db.close()


def test_knowledge_routes_are_admin_read_only_and_return_markdown(
    client, fresh_org,
):
    org = fresh_org()
    index = client.get("/api/admin/moshko/knowledge", headers=org["headers"])
    assert index.status_code == 200, index.text
    assert index.json()["available"] is True
    topic_ids = {topic["id"] for topic in index.json()["topics"]}
    assert "rezef:overview" in topic_ids
    assert "bookkeeper_kb:README.md" in topic_ids

    topic = client.get(
        "/api/admin/moshko/knowledge/bookkeeper_kb:README.md",
        headers=org["headers"],
    )
    assert topic.status_code == 200, topic.text
    assert topic.json()["available"] is True
    assert topic.json()["format"] == "markdown"
    assert "מרכז הידע" in topic.json()["content"]

    user_id, user_headers = _add_user(
        org["org_id"], role=UserRole.USER, suffix="knowledge-non-admin",
    )
    assert user_id
    assert client.get("/api/admin/moshko/knowledge", headers=user_headers).status_code == 403
    assert client.post(
        "/api/admin/moshko/knowledge", headers=org["headers"], json={},
    ).status_code == 405


def test_knowledge_route_reports_missing_packaged_docs_honestly(
    client, fresh_org, monkeypatch, tmp_path,
):
    from cfo.services import kb_loader

    org = fresh_org()
    monkeypatch.setattr(kb_loader, "DOCS_ROOT", tmp_path / "missing-docs")
    kb_loader._index_for.cache_clear()
    kb_loader._read_file.cache_clear()
    try:
        response = client.get("/api/admin/moshko/knowledge", headers=org["headers"])
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["document_knowledge"]["available"] is False
        assert body["document_knowledge"]["reason"]
        assert body["document_knowledge"].get("topics") is None

        topic = client.get(
            "/api/admin/moshko/knowledge/bookkeeper_kb:README.md",
            headers=org["headers"],
        )
        assert topic.status_code == 200, topic.text
        assert topic.json()["available"] is False
        assert topic.json()["content"] is None
        assert topic.json()["reason"]
    finally:
        kb_loader._index_for.cache_clear()
        kb_loader._read_file.cache_clear()
