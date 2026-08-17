"""Package F (2026-07-27b moshko-memory-and-whatsapp plan): WhatsApp webhook
(Meta Cloud API). No live network call is made anywhere in this file —
WhatsAppGateway's HTTP-calling methods are always monkeypatched."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re

import pytest

from cfo import config as config_module
from cfo.api.routes import whatsapp_webhook as ww_module
from cfo.database import SessionLocal
from cfo.models import ChannelIdentity, User
from cfo.services import channel_link_service as link_service_module
from cfo.services.ai_chat_service import AIChatService
from cfo.services.channel_link_service import issue_link_code, redeem_link_code
from cfo.services.whatsapp_gateway import WhatsAppGateway

_CODE_RE = re.compile(r"\b(\d{6})\b")

SIGNATURE_HEADER = "X-Hub-Signature-256"
TEST_VERIFY_TOKEN = "test-whatsapp-verify-token"
TEST_APP_SECRET = "test-whatsapp-app-secret"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def whatsapp_configured(monkeypatch):
    monkeypatch.setattr(config_module.settings, "whatsapp_verify_token", TEST_VERIFY_TOKEN)
    monkeypatch.setattr(config_module.settings, "whatsapp_app_secret", TEST_APP_SECRET)
    monkeypatch.setattr(config_module.settings, "whatsapp_phone_number_id", "dummy-pnid")
    monkeypatch.setattr(config_module.settings, "whatsapp_access_token", "dummy-token")


@pytest.fixture
def fake_gateway(monkeypatch):
    """Records every outbound call instead of hitting graph.facebook.com."""
    calls = {"send_text": [], "send_confirm_prompt": [], "download_media": []}

    async def _send_text(self, chat_id, text):
        calls["send_text"].append((chat_id, text))

    async def _send_confirm_prompt(self, chat_id, text, message_id):
        calls["send_confirm_prompt"].append((chat_id, text, message_id))

    async def _download_media(self, media_id):
        calls["download_media"].append(media_id)
        return b"fake-media-bytes", "image/jpeg"

    monkeypatch.setattr(WhatsAppGateway, "send_text", _send_text)
    monkeypatch.setattr(WhatsAppGateway, "send_confirm_prompt", _send_confirm_prompt)
    monkeypatch.setattr(WhatsAppGateway, "download_media", _download_media)
    return calls


@pytest.fixture
def fake_smtp(monkeypatch):
    calls = []

    async def _fake_send(to, subject, body, settings, *, attachments=None):
        calls.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr(link_service_module, "send_email_smtp", _fake_send)
    return calls


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

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
        redeem_link_code(db, result["code"], provider="whatsapp", external_id=external_id)
    finally:
        db.close()


def _email_for_org(org_id: int) -> str:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.organization_id == org_id).first().email
    finally:
        db.close()


def _extract_code(body: str) -> str:
    m = _CODE_RE.search(body)
    assert m, f"no 6-digit code found in email body: {body!r}"
    return m.group(1)


def _text_message(wamid: str, from_id: str, body: str, *, profile_name: str | None = None) -> dict:
    contacts = []
    if profile_name:
        contacts.append({"profile": {"name": profile_name}, "wa_id": from_id})
    return {
        "entry": [{
            "id": "WABA-1",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "contacts": contacts,
                    "messages": [{
                        "from": from_id, "id": wamid, "timestamp": "1700000000",
                        "type": "text", "text": {"body": body},
                    }],
                },
            }],
        }],
    }


def _image_message(wamid: str, from_id: str, *, media_id: str = "media-1", mime_type: str = "image/jpeg") -> dict:
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": from_id, "id": wamid, "timestamp": "1700000000",
                        "type": "image", "image": {"id": media_id, "mime_type": mime_type},
                    }],
                },
            }],
        }],
    }


def _document_message(wamid: str, from_id: str, *, media_id: str = "doc-1", mime_type: str = "application/pdf") -> dict:
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": from_id, "id": wamid, "timestamp": "1700000000",
                        "type": "document", "document": {"id": media_id, "mime_type": mime_type},
                    }],
                },
            }],
        }],
    }


def _button_reply_message(wamid: str, from_id: str, button_id: str) -> dict:
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": from_id, "id": wamid, "timestamp": "1700000000",
                        "type": "interactive",
                        "interactive": {
                            "type": "button_reply",
                            "button_reply": {"id": button_id, "title": "אשר"},
                        },
                    }],
                },
            }],
        }],
    }


def _status_payload(wamid: str = "wamid.status-1") -> dict:
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "statuses": [{"id": wamid, "status": "delivered", "timestamp": "1700000000"}],
                },
            }],
        }],
    }


def _signature_for(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _post(client, payload, *, secret=TEST_APP_SECRET, signature=None):
    body = json.dumps(payload).encode("utf-8")
    sig = signature if signature is not None else _signature_for(body, secret)
    headers = {"Content-Type": "application/json"}
    if sig is not None:
        headers[SIGNATURE_HEADER] = sig
    return client.post("/api/whatsapp/webhook", content=body, headers=headers)


# --------------------------------------------------------------------------- #
# GET verification handshake
# --------------------------------------------------------------------------- #

def test_get_verify_correct_token_returns_raw_challenge(client, whatsapp_configured):
    r = client.get("/api/whatsapp/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": TEST_VERIFY_TOKEN, "hub.challenge": "chal-123",
    })
    assert r.status_code == 200
    assert r.text == "chal-123"
    assert r.headers["content-type"].startswith("text/plain")


def test_get_verify_wrong_token_returns_403(client, whatsapp_configured):
    r = client.get("/api/whatsapp/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "wrong-token", "hub.challenge": "chal-123",
    })
    assert r.status_code == 403


def test_get_verify_not_configured_returns_503(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "whatsapp_verify_token", None)
    r = client.get("/api/whatsapp/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "anything", "hub.challenge": "chal-123",
    })
    assert r.status_code == 503


# --------------------------------------------------------------------------- #
# POST signature verification
# --------------------------------------------------------------------------- #

def test_post_missing_app_secret_returns_503(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "whatsapp_app_secret", None)
    body = json.dumps({"entry": []}).encode("utf-8")
    r = client.post(
        "/api/whatsapp/webhook", content=body,
        headers={"Content-Type": "application/json", SIGNATURE_HEADER: "sha256=whatever"},
    )
    assert r.status_code == 503


def test_post_wrong_signature_returns_403(client, whatsapp_configured):
    r = _post(client, {"entry": []}, signature="sha256=" + "0" * 64)
    assert r.status_code == 403


def test_post_correct_signature_returns_200(client, whatsapp_configured, fake_gateway):
    r = _post(client, {"entry": []})
    assert r.status_code == 200


# --------------------------------------------------------------------------- #
# Dedupe + statuses
# --------------------------------------------------------------------------- #

def test_duplicate_wamid_handled_once(client, whatsapp_configured, fake_gateway, monkeypatch, fresh_org):
    iso = fresh_org()
    _link(iso["org_id"], "972500000101")

    calls = {"n": 0}

    async def fake_send_message(self, session_id, text, persona=None):
        calls["n"] += 1
        return {"message_id": 1, "reply": "עונה", "pending_action": None}

    monkeypatch.setattr(AIChatService, "send_message", fake_send_message)

    payload = _text_message("wamid.dup-1", "972500000101", "מה שלום העסק?")
    r1 = _post(client, payload)
    r2 = _post(client, payload)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert calls["n"] == 1


def test_status_payload_returns_200_without_any_action(client, whatsapp_configured, fake_gateway):
    r = _post(client, _status_payload())
    assert r.status_code == 200
    assert not fake_gateway["send_text"]
    assert not fake_gateway["send_confirm_prompt"]
    assert not fake_gateway["download_media"]


# --------------------------------------------------------------------------- #
# Unlinked identity: no LLM, no download, until verified
# --------------------------------------------------------------------------- #

def test_message_from_unlinked_identity_never_reaches_llm(client, whatsapp_configured, fake_gateway, monkeypatch):
    called = {"n": 0}

    async def fake_send_message(self, *a, **kw):
        called["n"] += 1
        return {"message_id": 1, "reply": "x", "pending_action": None}

    monkeypatch.setattr(AIChatService, "send_message", fake_send_message)

    r = _post(client, _text_message("wamid.unlinked-1", "972500000201", "מה המצב הפיננסי?"))
    assert r.status_code == 200
    assert called["n"] == 0
    assert fake_gateway["send_text"]
    last_text = fake_gateway["send_text"][-1][1]
    assert "מקושר" in last_text or "לקשר" in last_text


def test_image_from_unlinked_identity_is_never_downloaded_or_processed(
    client, whatsapp_configured, fake_gateway, monkeypatch,
):
    intake_calls = {"n": 0}

    async def fake_intake(*a, **kw):
        intake_calls["n"] += 1
        return {"status": "created", "expense_id": 1, "message": "x"}

    monkeypatch.setattr("cfo.services.chat_expense_intake.intake_receipt_bytes", fake_intake)

    r = _post(client, _image_message("wamid.img-unlinked-1", "972500000202"))
    assert r.status_code == 200
    assert not fake_gateway["download_media"]
    assert intake_calls["n"] == 0
    assert fake_gateway["send_text"]


def test_email_from_unlinked_identity_starts_verification_without_llm(
    client, whatsapp_configured, fake_gateway, fake_smtp, monkeypatch, fresh_org,
):
    called = {"n": 0}

    async def fake_send_message(self, *a, **kw):
        called["n"] += 1
        return {"message_id": 1, "reply": "x", "pending_action": None}

    monkeypatch.setattr(AIChatService, "send_message", fake_send_message)

    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])

    r = _post(client, _text_message("wamid.email-1", "972500000301", known_email))
    assert r.status_code == 200
    assert called["n"] == 0
    assert len(fake_smtp) == 1
    assert "קוד" in fake_gateway["send_text"][-1][1]


def test_six_digit_code_completes_verification_and_welcomes(
    client, whatsapp_configured, fake_gateway, fake_smtp, fresh_org,
):
    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])

    r1 = _post(client, _text_message("wamid.emailv-1", "972500000401", known_email))
    assert r1.status_code == 200
    code = _extract_code(fake_smtp[-1]["body"])

    r2 = _post(client, _text_message(
        "wamid.emailv-2", "972500000401", code, profile_name="Yossi",
    ))
    assert r2.status_code == 200
    assert "הצליח" in fake_gateway["send_text"][-1][1]

    db = SessionLocal()
    try:
        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.provider == "whatsapp",
            ChannelIdentity.external_id == "972500000401",
        ).first()
        assert identity is not None
        assert identity.verified_at is not None
        assert identity.display_name == "Yossi"
    finally:
        db.close()


def test_wrong_six_digit_code_returns_error_message_not_llm(
    client, whatsapp_configured, fake_gateway, fake_smtp, monkeypatch, fresh_org,
):
    called = {"n": 0}

    async def fake_send_message(self, *a, **kw):
        called["n"] += 1
        return {"message_id": 1, "reply": "x", "pending_action": None}

    monkeypatch.setattr(AIChatService, "send_message", fake_send_message)

    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])
    _post(client, _text_message("wamid.emailw-1", "972500000501", known_email))

    r = _post(client, _text_message("wamid.emailw-2", "972500000501", "000000"))
    assert r.status_code == 200
    assert called["n"] == 0
    assert "שגוי" in fake_gateway["send_text"][-1][1]


# --------------------------------------------------------------------------- #
# Linked identity: chat + receipt intake
# --------------------------------------------------------------------------- #

def test_linked_message_invokes_send_message_with_persona_and_replies(
    client, whatsapp_configured, fake_gateway, monkeypatch, fresh_org,
):
    iso = fresh_org()
    _link(iso["org_id"], "972500000601")

    captured = {}

    async def fake_send_message(self, session_id, text, persona=None):
        captured["session_id"] = session_id
        captured["text"] = text
        captured["persona"] = persona
        return {"message_id": 42, "reply": "התשובה שלי", "pending_action": None}

    monkeypatch.setattr(AIChatService, "send_message", fake_send_message)

    r = _post(client, _text_message("wamid.linked-1", "972500000601", "מה מצב הגבייה?"))
    assert r.status_code == 200
    assert captured["persona"] == "cfo"
    assert captured["session_id"] == "wa-972500000601"
    assert fake_gateway["send_text"][-1] == ("972500000601", "התשובה שלי")


def test_image_from_linked_identity_downloads_and_replies_with_summary(
    client, whatsapp_configured, fake_gateway, monkeypatch, fresh_org,
):
    iso = fresh_org()
    _link(iso["org_id"], "972500000701")

    intake_calls = {}

    async def fake_intake(db, organization_id, content, *, media_type=None, source="whatsapp",
                           uploaded_by_user_id=None, session_id=None):
        intake_calls["organization_id"] = organization_id
        intake_calls["content"] = content
        intake_calls["media_type"] = media_type
        intake_calls["source"] = source
        intake_calls["uploaded_by_user_id"] = uploaded_by_user_id
        return {
            "status": "created", "expense_id": 55,
            "message": "קלטתי קבלה מ-שופרסל. סכום: 118.00 ₪.",
        }

    monkeypatch.setattr("cfo.services.chat_expense_intake.intake_receipt_bytes", fake_intake)

    r = _post(client, _image_message("wamid.img-linked-1", "972500000701", media_id="media-99"))
    assert r.status_code == 200
    assert fake_gateway["download_media"] == ["media-99"]
    assert intake_calls["organization_id"] == iso["org_id"]
    assert intake_calls["source"] == "whatsapp"
    assert intake_calls["content"] == b"fake-media-bytes"

    last_text = fake_gateway["send_text"][-1][1]
    assert "שופרסל" in last_text
    assert "תייק" in last_text
    assert "55" in last_text


def test_pdf_document_from_linked_identity_is_recognized_as_a_receipt(
    client, whatsapp_configured, fake_gateway, monkeypatch, fresh_org,
):
    """The message envelope declares application/pdf; fake_gateway's
    download_media reports a *different* mime type (image/jpeg, its
    default) to prove the envelope-declared type wins — vision_extractor
    branches its PDF-vs-image path on this exact value, so silently
    downgrading a PDF to image/jpeg would break extraction."""
    iso = fresh_org()
    _link(iso["org_id"], "972500000801")

    intake_calls = {}

    async def fake_intake(db, organization_id, content, *, media_type=None, source="whatsapp",
                           uploaded_by_user_id=None, session_id=None):
        intake_calls["media_type"] = media_type
        return {"status": "unreadable", "message": "לא הצלחתי לקרוא את הקבלה."}

    monkeypatch.setattr("cfo.services.chat_expense_intake.intake_receipt_bytes", fake_intake)

    r = _post(client, _document_message("wamid.doc-linked-1", "972500000801", mime_type="application/pdf"))
    assert r.status_code == 200
    assert intake_calls["media_type"] == "application/pdf"  # envelope-declared type, not the gateway's image/jpeg
    assert "לא הצלחתי" in fake_gateway["send_text"][-1][1]


def test_non_pdf_non_image_document_is_ignored(client, whatsapp_configured, fake_gateway, fresh_org):
    iso = fresh_org()
    _link(iso["org_id"], "972500000901")

    r = _post(client, _document_message(
        "wamid.doc-other-1", "972500000901", media_id="doc-2", mime_type="application/zip",
    ))
    assert r.status_code == 200
    assert not fake_gateway["send_text"]


def test_persona_switch_command_persists(client, whatsapp_configured, fake_gateway, fresh_org):
    iso = fresh_org()
    _link(iso["org_id"], "972500001001")

    r = _post(client, _text_message("wamid.persona-1", "972500001001", "/bookkeeper"))
    assert r.status_code == 200

    db = SessionLocal()
    try:
        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.provider == "whatsapp",
            ChannelIdentity.external_id == "972500001001",
        ).first()
        assert identity.default_persona == "bookkeeper"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Pending-action confirm flow
# --------------------------------------------------------------------------- #

def test_pending_action_sends_confirm_prompt_with_actual_arguments(
    client, whatsapp_configured, fake_gateway, monkeypatch, fresh_org,
):
    iso = fresh_org()
    _link(iso["org_id"], "972500001101")

    async def fake_send_message(self, session_id, text, persona=None):
        return {
            "message_id": 88, "reply": "לשלוח?",
            "pending_action": {
                "tool": "email_report",
                "input": {"report_type": "profit_loss", "recipient_email": "bank@example.com"},
                "description": "שליחת דוח במייל",
            },
        }

    monkeypatch.setattr(AIChatService, "send_message", fake_send_message)

    r = _post(client, _text_message("wamid.pending-1", "972500001101", "שלח לבנק רווח והפסד"))
    assert r.status_code == 200
    chat_id, text, message_id = fake_gateway["send_confirm_prompt"][0]
    assert (chat_id, message_id) == ("972500001101", 88)
    assert "bank@example.com" in text
    assert "profit_loss" in text
    assert "שליחת דוח במייל" in text
    assert not fake_gateway["send_text"]


def test_button_reply_confirm_invokes_confirm_action(
    client, whatsapp_configured, fake_gateway, monkeypatch, fresh_org,
):
    iso = fresh_org()
    _link(iso["org_id"], "972500001201")

    called = {}

    async def fake_confirm_action(self, message_id):
        called["message_id"] = message_id
        return {"result": {"ok": True}, "message_id": message_id}

    monkeypatch.setattr(AIChatService, "confirm_action", fake_confirm_action)

    r = _post(client, _button_reply_message("wamid.confirm-1", "972500001201", "confirm:88"))
    assert r.status_code == 200
    assert called["message_id"] == 88
    assert any("בוצע" in text for _, text in fake_gateway["send_text"])


def test_button_reply_cancel_does_not_execute_anything(
    client, whatsapp_configured, fake_gateway, monkeypatch, fresh_org,
):
    iso = fresh_org()
    _link(iso["org_id"], "972500001301")

    called = {"confirm": 0, "cancel": 0, "message_id": None}

    async def fake_confirm_action(self, message_id):
        called["confirm"] += 1
        return {"result": {}, "message_id": message_id}

    def fake_cancel_action(self, message_id):
        called["cancel"] += 1
        called["message_id"] = message_id
        return {"message_id": message_id, "status": "cancelled"}

    monkeypatch.setattr(AIChatService, "confirm_action", fake_confirm_action)
    monkeypatch.setattr(AIChatService, "cancel_action", fake_cancel_action, raising=False)

    r = _post(client, _button_reply_message("wamid.cancel-1", "972500001301", "cancel:88"))
    assert r.status_code == 200
    assert called == {"confirm": 0, "cancel": 1, "message_id": 88}
    assert any("בוטל" in text for _, text in fake_gateway["send_text"])


# --------------------------------------------------------------------------- #
# WhatsAppGateway unit behavior — message splitting
# --------------------------------------------------------------------------- #

def test_send_text_splits_messages_over_4096_chars(monkeypatch):
    gateway = WhatsAppGateway(phone_number_id="pnid", access_token="tok")
    sent_payloads = []

    async def fake_post_messages(self, payload):
        sent_payloads.append(payload)

    monkeypatch.setattr(WhatsAppGateway, "_post_messages", fake_post_messages)

    asyncio.run(gateway.send_text("972500001401", "א" * 5000))
    assert len(sent_payloads) == 2
    assert all(p["type"] == "text" for p in sent_payloads)


def test_send_text_within_limit_sends_one_message(monkeypatch):
    gateway = WhatsAppGateway(phone_number_id="pnid", access_token="tok")
    sent_payloads = []

    async def fake_post_messages(self, payload):
        sent_payloads.append(payload)

    monkeypatch.setattr(WhatsAppGateway, "_post_messages", fake_post_messages)

    asyncio.run(gateway.send_text("972500001402", "שלום"))
    assert len(sent_payloads) == 1


def test_send_confirm_prompt_truncates_body_and_sets_reply_buttons(monkeypatch):
    """_render_pending_action can emit a reply + description + one line per
    tool argument — easily over WhatsApp's 1024-char interactive body cap
    for a multi-argument tool. Meta rejects the whole message if the body
    exceeds the cap, so this must never be sent unclipped."""
    gateway = WhatsAppGateway(phone_number_id="pnid", access_token="tok")
    sent_payloads = []

    async def fake_post_messages(self, payload):
        sent_payloads.append(payload)

    monkeypatch.setattr(WhatsAppGateway, "_post_messages", fake_post_messages)

    long_text = "א" * 2000
    asyncio.run(gateway.send_confirm_prompt("972500001501", long_text, 99))

    assert len(sent_payloads) == 1
    payload = sent_payloads[0]
    assert payload["type"] == "interactive"
    body_text = payload["interactive"]["body"]["text"]
    assert len(body_text) <= 1024

    buttons = payload["interactive"]["action"]["buttons"]
    assert [b["reply"]["id"] for b in buttons] == ["confirm:99", "cancel:99"]
    assert all(len(b["reply"]["title"]) <= 20 for b in buttons)


def test_send_template_builds_expected_payload(monkeypatch):
    gateway = WhatsAppGateway(phone_number_id="pnid", access_token="tok")
    sent_payloads = []

    async def fake_post_messages(self, payload):
        sent_payloads.append(payload)

    monkeypatch.setattr(WhatsAppGateway, "_post_messages", fake_post_messages)

    asyncio.run(gateway.send_template(
        "972500001601", "daily_alert", "he", ["1,234.50", "יתרת בנק"],
    ))

    assert len(sent_payloads) == 1
    payload = sent_payloads[0]
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "daily_alert"
    assert payload["template"]["language"]["code"] == "he"
    params = payload["template"]["components"][0]["parameters"]
    assert [p["text"] for p in params] == ["1,234.50", "יתרת בנק"]
