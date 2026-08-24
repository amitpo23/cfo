"""Wave 2 Step 9.2 route-level tests for the AI chat endpoints."""
from types import SimpleNamespace

import pytest

from cfo.database import SessionLocal
from cfo.models import ChatMessage, User, UserRole
from cfo.services.ai_chat_service import AIChatService


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _promote_to_super(email: str) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        user.role = UserRole.SUPER_ADMIN
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="module")
def chat_superadmin(client):
    """A registered user promoted to SUPER_ADMIN — mirrors the pattern in
    test_super_admin_org_override.py's `superadmin` fixture (module-scoped
    there too, so a duplicate here keeps this file independent)."""
    resp = client.post("/api/admin/auth/register", json={
        "email": "chat-super@example.com",
        "password": "secret123",
        "full_name": "Chat Super",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    _promote_to_super("chat-super@example.com")
    # מ-11/08/2026 כל סופר-אדמין חייב לבחור ארגון מפורשות — גם כשיש לו
    # ארגון בית. הכותרת מצורפת כאן כדי שהטסטים בקובץ יבדקו את מה שהם
    # מתארים (כלי משרד) ולא ייעצרו על בחירת ארגון.
    return {
        "headers": {
            "Authorization": f"Bearer {data['access_token']}",
            "X-Active-Org-Id": str(data["user"]["organization_id"]),
        }
    }


class FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)

    async def create(self, **_kwargs):
        return self._responses.pop(0)


class FakeAnthropicClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def test_routes_require_auth(client):
    assert client.post("/api/ai/chat", json={"session_id": "s", "message": "hi"}).status_code == 403
    assert client.post("/api/ai/chat/confirm", json={"message_id": 1}).status_code == 403
    assert client.post("/api/ai/chat/cancel", json={"message_id": 1}).status_code == 403
    assert client.get("/api/ai/chat/pending-approvals").status_code == 403
    assert client.get("/api/ai/chat/s").status_code == 403


def test_pending_approvals_route_uses_current_org_and_user(monkeypatch, client, fresh_org):
    iso = fresh_org()
    called = {}

    def fake_list(self):
        called["organization_id"] = self.organization_id
        called["user_id"] = self.user_id
        return [{
            "message_id": 42,
            "description": "הפקת מסמך",
            "input": {
                "customer_name": "לקוח בדיקה",
                "amount": 2500,
                "items": [{"description": "שירות", "quantity": 1}],
            },
        }]

    monkeypatch.setattr(AIChatService, "list_pending_approvals", fake_list, raising=False)

    response = client.get("/api/ai/chat/pending-approvals", headers=iso["headers"])

    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [{
            "message_id": 42,
            "description": "הפקת מסמך",
            "input": {
                "customer_name": "לקוח בדיקה",
                "amount": 2500,
                "items": [{"description": "שירות", "quantity": 1}],
            },
        }],
    }
    assert called["organization_id"] == iso["org_id"]
    assert isinstance(called["user_id"], int)


def test_history_marks_only_the_actual_current_approver(client, fresh_org):
    iso = fresh_org()
    db = SessionLocal()
    try:
        proposer = db.query(User).filter(User.organization_id == iso["org_id"]).one()
        db.add(ChatMessage(
            organization_id=iso["org_id"],
            user_id=proposer.id,
            session_id="wording-check",
            role="assistant",
            content="נדרש אישור",
            pending_action={
                "tool": "issue_document",
                "input": {},
                "description": "הפקת מסמך",
                "policy_action": "invoices.issue",
            },
            action_status="pending",
        ))
        db.add(ChatMessage(
            organization_id=iso["org_id"],
            user_id=proposer.id,
            session_id="wording-check",
            role="assistant",
            content="נדרש אישור רגיל",
            pending_action={
                "tool": "create_task",
                "input": {},
                "description": "יצירת משימה",
                "policy_action": "tasks.write",
            },
            action_status="pending",
        ))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/ai/chat/wording-check", headers=iso["headers"])

    assert response.status_code == 200, response.text
    messages = response.json()["messages"]
    assert messages[0]["can_current_user_approve"] is False
    assert messages[1]["can_current_user_approve"] is True


@pytest.mark.parametrize("session_id", ["bad/session", "x" * 65, "רווח לא חוקי"])
def test_chat_session_id_is_validated_before_storage(client, fresh_org, session_id):
    iso = fresh_org()

    sent = client.post(
        "/api/ai/chat",
        headers=iso["headers"],
        json={"session_id": session_id, "message": "היי"},
    )

    assert sent.status_code == 400
    assert "session_id" in sent.json()["detail"]


def test_send_message_route_and_history(monkeypatch, client, fresh_org):
    iso = fresh_org()
    monkeypatch.setattr(
        AIChatService, "_make_client",
        lambda self: FakeAnthropicClient([
            SimpleNamespace(stop_reason="end_turn", content=[_text_block("שלום, איך אפשר לעזור?")]),
        ]),
    )

    r = client.post("/api/ai/chat", headers=iso["headers"],
                     json={"session_id": "sess-1", "message": "היי"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pending_action"] is None
    assert "שלום" in body["reply"]

    hist = client.get("/api/ai/chat/sess-1", headers=iso["headers"])
    assert hist.status_code == 200
    messages = hist.json()["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


def test_confirm_route_rejects_unknown_message(client, fresh_org):
    iso = fresh_org()
    r = client.post("/api/ai/chat/confirm", headers=iso["headers"], json={"message_id": 999999})
    assert r.status_code == 400


def test_cancel_route_invokes_scoped_service(monkeypatch, client, fresh_org):
    iso = fresh_org()
    called = {}

    def fake_cancel(self, message_id):
        called["org_id"] = self.organization_id
        called["user_id"] = self.user_id
        called["message_id"] = message_id
        return {"message_id": message_id, "status": "cancelled"}

    monkeypatch.setattr(AIChatService, "cancel_action", fake_cancel, raising=False)
    r = client.post(
        "/api/ai/chat/cancel",
        headers=iso["headers"],
        json={"message_id": 123},
    )

    assert r.status_code == 200, r.text
    assert called["message_id"] == 123
    assert called["org_id"] == iso["org_id"]


def test_chat_history_is_org_isolated(monkeypatch, client, fresh_org):
    iso_a = fresh_org()
    iso_b = fresh_org()
    monkeypatch.setattr(
        AIChatService, "_make_client",
        lambda self: FakeAnthropicClient([
            SimpleNamespace(stop_reason="end_turn", content=[_text_block("תשובה")]),
        ]),
    )
    client.post("/api/ai/chat", headers=iso_a["headers"], json={"session_id": "shared", "message": "hi"})

    hist_b = client.get("/api/ai/chat/shared", headers=iso_b["headers"])
    assert hist_b.json()["messages"] == []


def test_missing_anthropic_key_returns_clean_400_not_500(monkeypatch, client, fresh_org):
    """Found via live manual testing: without ANTHROPIC_API_KEY configured,
    the raw anthropic SDK raises TypeError deep inside _build_headers,
    which was leaking as an unhandled 500."""
    from cfo import config as config_module
    monkeypatch.setattr(config_module.settings, "anthropic_api_key", None)

    iso = fresh_org()
    r = client.post("/api/ai/chat", headers=iso["headers"],
                     json={"session_id": "s1", "message": "היי"})
    assert r.status_code == 400
    assert "לא הוגדר" in r.json()["detail"] or "not configured" in r.json()["detail"].lower()


def test_anthropic_upstream_error_returns_clean_503_not_500(monkeypatch, client, fresh_org):
    """Found via the first live 9.5 test against a real ANTHROPIC_API_KEY:
    a valid, correctly-configured key but an Anthropic account with no
    credit balance raises anthropic.BadRequestError deep inside
    messages.create -- which leaked as a raw unhandled 500 instead of a
    clean, honest upstream-failure response."""
    import httpx
    import anthropic

    class FailingMessages:
        async def create(self, **_kwargs):
            response = httpx.Response(
                400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
            )
            raise anthropic.BadRequestError(
                "Your credit balance is too low to access the Anthropic API.",
                response=response,
                body={"type": "error", "error": {"type": "invalid_request_error",
                                                  "message": "Your credit balance is too low"}},
            )

    class FailingClient:
        def __init__(self):
            self.messages = FailingMessages()

    monkeypatch.setattr(AIChatService, "_make_client", lambda self: FailingClient())

    iso = fresh_org()
    r = client.post("/api/ai/chat", headers=iso["headers"],
                     json={"session_id": "s1", "message": "היי"})
    assert r.status_code == 503, r.text
    assert "anthropic" in r.json()["detail"].lower() or "עוזר" in r.json()["detail"]


class FakeMessagesCapture:
    """Like FakeMessages, but records every create() call's kwargs so the
    route test can inspect exactly what tool schema/system prompt the route
    wired the service up with for this user's role."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeAnthropicClientCapture:
    def __init__(self, responses):
        self.messages = FakeMessagesCapture(responses)


def test_super_admin_sees_office_tools_via_route(monkeypatch, client, chat_superadmin):
    fake = FakeAnthropicClientCapture([
        SimpleNamespace(stop_reason="end_turn", content=[_text_block("שלום")]),
    ])
    monkeypatch.setattr(AIChatService, "_make_client", lambda self: fake)

    r = client.post("/api/ai/chat", headers=chat_superadmin["headers"],
                     json={"session_id": "office-s1", "message": "מה שלום המשרד?"})
    assert r.status_code == 200, r.text

    tool_names = {t["name"] for t in fake.messages.calls[0]["tools"]}
    assert "list_office_clients" in tool_names
    assert "register_office_client" in tool_names


def test_regular_user_does_not_see_office_tools_via_route(monkeypatch, client, fresh_org):
    iso = fresh_org()
    fake = FakeAnthropicClientCapture([
        SimpleNamespace(stop_reason="end_turn", content=[_text_block("שלום")]),
    ])
    monkeypatch.setattr(AIChatService, "_make_client", lambda self: fake)

    r = client.post("/api/ai/chat", headers=iso["headers"],
                     json={"session_id": "s-regular", "message": "מה מצב הגבייה?"})
    assert r.status_code == 200, r.text

    tool_names = {t["name"] for t in fake.messages.calls[0]["tools"]}
    assert "list_office_clients" not in tool_names
    assert "register_office_client" not in tool_names


def test_send_message_route_accepts_persona_and_wires_the_prompt(monkeypatch, client, fresh_org):
    """Package 1 (2026-07-26 personas plan): `persona` is an optional body
    field that flows session_id/text/persona -> AIChatService.send_message.
    A regular user picking a persona must still never see office tools —
    persona is a prompt/tone axis, never a permission gate."""
    iso = fresh_org()
    fake = FakeAnthropicClientCapture([
        SimpleNamespace(stop_reason="end_turn", content=[_text_block("שלום")]),
    ])
    monkeypatch.setattr(AIChatService, "_make_client", lambda self: fake)

    r = client.post("/api/ai/chat", headers=iso["headers"], json={
        "session_id": "persona-s1", "message": "מה חסר לי לתייק?",
        "persona": "bookkeeper",
    })
    assert r.status_code == 200, r.text

    system_prompt = fake.messages.calls[0]["system"]
    assert "מנהלת חשבונות" in system_prompt
    tool_names = {t["name"] for t in fake.messages.calls[0]["tools"]}
    assert "list_office_clients" not in tool_names
