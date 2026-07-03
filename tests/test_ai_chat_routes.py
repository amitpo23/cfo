"""Wave 2 Step 9.2 route-level tests for the AI chat endpoints."""
from types import SimpleNamespace

from cfo.services.ai_chat_service import AIChatService


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


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
    assert client.get("/api/ai/chat/s").status_code == 403


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
