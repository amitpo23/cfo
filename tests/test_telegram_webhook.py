"""Package 3 (2026-07-26 conversational-channels plan), decision 7:
POST /api/telegram/webhook. No live network call is made anywhere in this
file — anthropic and httpx/telegram are always mocked."""
from types import SimpleNamespace

import pytest

from cfo import config as config_module
from cfo.api.routes import telegram_webhook as tw_module
from cfo.database import SessionLocal
from cfo.models import User
from cfo.services.ai_chat_service import AIChatService
from cfo.services.channel_link_service import issue_link_code, redeem_link_code
from cfo.services.channel_gateway import TelegramGateway

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
TEST_SECRET = "test-telegram-secret"


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


@pytest.fixture
def telegram_configured(monkeypatch):
    monkeypatch.setattr(config_module.settings, "telegram_webhook_secret", TEST_SECRET)
    monkeypatch.setattr(config_module.settings, "telegram_bot_token", "dummy-token")


@pytest.fixture
def fake_gateway(monkeypatch):
    """Records every outbound call instead of hitting api.telegram.org."""
    calls = {"send_text": [], "send_confirm_prompt": [], "answer_callback_query": []}

    async def _send_text(self, chat_id, text):
        calls["send_text"].append((chat_id, text))

    async def _send_confirm_prompt(self, chat_id, text, message_id):
        calls["send_confirm_prompt"].append((chat_id, text, message_id))

    async def _answer_callback_query(self, callback_query_id, text=None):
        calls["answer_callback_query"].append((callback_query_id, text))

    monkeypatch.setattr(TelegramGateway, "send_text", _send_text)
    monkeypatch.setattr(TelegramGateway, "send_confirm_prompt", _send_confirm_prompt)
    monkeypatch.setattr(TelegramGateway, "answer_callback_query", _answer_callback_query)
    return calls


def _user_id_for_org(org_id: int) -> int:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.organization_id == org_id).first().id
    finally:
        db.close()


def _link(org_id: int, external_id: str) -> None:
    db = SessionLocal()
    try:
        user_id = _user_id_for_org(org_id)
        result = issue_link_code(db, org_id, user_id)
        redeem_link_code(db, result["code"], provider="telegram", external_id=external_id)
    finally:
        db.close()


def _post(client, payload, secret=TEST_SECRET):
    headers = {}
    if secret is not None:
        headers[SECRET_HEADER] = secret
    return client.post("/api/telegram/webhook", json=payload, headers=headers)


def test_missing_secret_in_env_returns_503(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "telegram_webhook_secret", None)
    r = _post(client, {"update_id": 1, "message": {"chat": {"id": 1}, "text": "hi"}})
    assert r.status_code == 503


def test_wrong_secret_returns_403(client, telegram_configured):
    r = _post(client, {"update_id": 2, "message": {"chat": {"id": 1}, "text": "hi"}}, secret="wrong")
    assert r.status_code == 403


def test_duplicate_update_id_handled_once(client, telegram_configured, fake_gateway, monkeypatch, fresh_org):
    iso = fresh_org()
    _link(iso["org_id"], "chat-dup-1")

    calls = {"n": 0}

    async def fake_send_message(self, session_id, text, persona=None):
        calls["n"] += 1
        return {"message_id": 1, "reply": "עונה", "pending_action": None}

    monkeypatch.setattr(AIChatService, "send_message", fake_send_message)

    payload = {"update_id": 100, "message": {"chat": {"id": "chat-dup-1"}, "text": "מה שלום העסק?"}}
    r1 = _post(client, payload)
    r2 = _post(client, payload)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert calls["n"] == 1


def test_duplicate_after_processing_error_still_handled_once(
    client, telegram_configured, fake_gateway, monkeypatch, fresh_org,
):
    """Risk 4 in the plan: if send_message raises and the top-level handler
    rolls back the session to answer the user gracefully, the dedupe row
    committed in _mark_processed (its own, already-committed transaction)
    must survive that rollback — otherwise a Telegram retry of the SAME
    update_id would re-run the LLM turn and double the API cost."""
    iso = fresh_org()
    _link(iso["org_id"], "chat-dup-err-1")

    calls = {"n": 0}

    async def failing_send_message(self, session_id, text, persona=None):
        calls["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(AIChatService, "send_message", failing_send_message)

    payload = {"update_id": 150, "message": {"chat": {"id": "chat-dup-err-1"}, "text": "שאלה כלשהי"}}
    r1 = _post(client, payload)
    assert r1.status_code == 200
    assert calls["n"] == 1
    assert any("שגיאה" in text for _, text in fake_gateway["send_text"])

    r2 = _post(client, payload)
    assert r2.status_code == 200
    assert calls["n"] == 1  # NOT re-invoked — the dedupe row from r1 survived the rollback


def test_group_chat_message_is_silently_ignored(client, telegram_configured, fake_gateway, monkeypatch):
    called = {"n": 0}

    async def fake_send_message(self, *a, **kw):
        called["n"] += 1
        return {"message_id": 1, "reply": "x", "pending_action": None}

    monkeypatch.setattr(AIChatService, "send_message", fake_send_message)

    r = _post(client, {
        "update_id": 175,
        "message": {"chat": {"id": -100123, "type": "group"}, "text": "/start abc"},
    })
    assert r.status_code == 200
    assert called["n"] == 0
    assert not fake_gateway["send_text"]  # no reply sent into the group at all


def test_integer_chat_id_resolves_identity(client, telegram_configured, fake_gateway, monkeypatch, fresh_org):
    """Real Telegram sends integer chat/user ids, not strings — the str()
    coercion path must behave the same as the string-id tests above."""
    iso = fresh_org()
    _link(iso["org_id"], "123456789")

    captured = {}

    async def fake_send_message(self, session_id, text, persona=None):
        captured["session_id"] = session_id
        return {"message_id": 1, "reply": "תשובה", "pending_action": None}

    monkeypatch.setattr(AIChatService, "send_message", fake_send_message)

    r = _post(client, {
        "update_id": 190,
        "message": {"chat": {"id": 123456789, "type": "private"}, "text": "מה המצב?"},
    })
    assert r.status_code == 200
    assert captured["session_id"] == "tg-123456789"


def test_message_from_unlinked_identity_never_reaches_llm(client, telegram_configured, fake_gateway, monkeypatch):
    called = {"n": 0}

    async def fake_send_message(self, *a, **kw):
        called["n"] += 1
        return {"message_id": 1, "reply": "x", "pending_action": None}

    monkeypatch.setattr(AIChatService, "send_message", fake_send_message)

    r = _post(client, {"update_id": 200, "message": {"chat": {"id": "chat-unlinked"}, "text": "מה המצב הפיננסי?"}})
    assert r.status_code == 200
    assert called["n"] == 0
    assert fake_gateway["send_text"]
    assert "מקושר" in fake_gateway["send_text"][-1][1] or "לקשר" in fake_gateway["send_text"][-1][1]


def test_start_with_code_links_identity(client, telegram_configured, fake_gateway, fresh_org):
    iso = fresh_org()
    db = SessionLocal()
    try:
        user_id = _user_id_for_org(iso["org_id"])
        result = issue_link_code(db, iso["org_id"], user_id)
        code = result["code"]
    finally:
        db.close()

    r = _post(client, {
        "update_id": 300,
        "message": {"chat": {"id": "chat-start-1"}, "text": f"/start {code}",
                    "from": {"first_name": "Dana"}},
    })
    assert r.status_code == 200
    assert fake_gateway["send_text"]
    assert "הצליח" in fake_gateway["send_text"][-1][1]


def test_linked_message_invokes_send_message_with_persona_and_replies(
    client, telegram_configured, fake_gateway, monkeypatch, fresh_org,
):
    iso = fresh_org()
    _link(iso["org_id"], "chat-linked-1")

    captured = {}

    async def fake_send_message(self, session_id, text, persona=None):
        captured["session_id"] = session_id
        captured["text"] = text
        captured["persona"] = persona
        return {"message_id": 42, "reply": "התשובה שלי", "pending_action": None}

    monkeypatch.setattr(AIChatService, "send_message", fake_send_message)

    r = _post(client, {
        "update_id": 400,
        "message": {"chat": {"id": "chat-linked-1"}, "text": "מה מצב הגבייה?"},
    })
    assert r.status_code == 200
    assert captured["persona"] == "cfo"  # default persona
    assert captured["session_id"] == "tg-chat-linked-1"
    assert fake_gateway["send_text"][-1] == ("chat-linked-1", "התשובה שלי")


def test_pending_action_sends_confirm_prompt(client, telegram_configured, fake_gateway, monkeypatch, fresh_org):
    iso = fresh_org()
    _link(iso["org_id"], "chat-pending-1")

    async def fake_send_message(self, session_id, text, persona=None):
        return {
            "message_id": 77, "reply": "לאשר את הפעולה?",
            "pending_action": {"tool": "issue_document", "input": {}, "description": "..."},
        }

    monkeypatch.setattr(AIChatService, "send_message", fake_send_message)

    r = _post(client, {
        "update_id": 500,
        "message": {"chat": {"id": "chat-pending-1"}, "text": "תוציא חשבונית ללקוח X"},
    })
    assert r.status_code == 200
    assert fake_gateway["send_confirm_prompt"] == [("chat-pending-1", "לאשר את הפעולה?", 77)]
    assert not fake_gateway["send_text"]


def test_callback_confirm_invokes_confirm_action(client, telegram_configured, fake_gateway, monkeypatch, fresh_org):
    iso = fresh_org()
    _link(iso["org_id"], "chat-confirm-1")

    called = {}

    async def fake_confirm_action(self, message_id):
        called["message_id"] = message_id
        return {"result": {"ok": True}, "message_id": message_id}

    monkeypatch.setattr(AIChatService, "confirm_action", fake_confirm_action)

    r = _post(client, {
        "update_id": 600,
        "callback_query": {
            "id": "cbq-1",
            "data": "confirm:77",
            "message": {"chat": {"id": "chat-confirm-1"}},
        },
    })
    assert r.status_code == 200
    assert called["message_id"] == 77
    assert fake_gateway["answer_callback_query"]


def test_callback_cancel_does_not_execute_anything(client, telegram_configured, fake_gateway, monkeypatch, fresh_org):
    iso = fresh_org()
    _link(iso["org_id"], "chat-cancel-1")

    called = {"n": 0}

    async def fake_confirm_action(self, message_id):
        called["n"] += 1
        return {"result": {}, "message_id": message_id}

    monkeypatch.setattr(AIChatService, "confirm_action", fake_confirm_action)

    r = _post(client, {
        "update_id": 700,
        "callback_query": {
            "id": "cbq-2",
            "data": "cancel:77",
            "message": {"chat": {"id": "chat-cancel-1"}},
        },
    })
    assert r.status_code == 200
    assert called["n"] == 0
    assert any("בוטל" in text for _, text in fake_gateway["send_text"])


def test_persona_switch_command_persists(client, telegram_configured, fake_gateway, fresh_org):
    iso = fresh_org()
    _link(iso["org_id"], "chat-persona-1")

    r = _post(client, {
        "update_id": 800,
        "message": {"chat": {"id": "chat-persona-1"}, "text": "/bookkeeper"},
    })
    assert r.status_code == 200

    from cfo.models import ChannelIdentity
    db = SessionLocal()
    try:
        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.provider == "telegram",
            ChannelIdentity.external_id == "chat-persona-1",
        ).first()
        assert identity.default_persona == "bookkeeper"
    finally:
        db.close()
