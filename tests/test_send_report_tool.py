"""כלי `send_report` — מושקו שולח דוח PDF לשיחה שבה התבקש.

הנמען נקבע אך ורק מהשיחה עצמה: הערוץ והזהות המקושרת שה-webhook אימת.
המודל אינו יכול לבחור נמען — אין שדה כזה בסכמה, ומפתחות שהמודל מעביר
(`_channel_external_id`, `chat_id`, `phone`) נדרסים/מתעלמים. אין רשת:
ה-gateway מזויף, וחומת הרשת ב-conftest חוסמת כל חיבור.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from cfo import config as config_module
from cfo.database import SessionLocal
from cfo.models import ChannelIdentity, User, UserRole
from cfo.services import ai_chat_tools
from cfo.services.ai_chat_service import AIChatService
from cfo.services.ai_chat_tools import TOOLS, tool_target_system
from cfo.services.whatsapp_gateway import WhatsAppSendError


# ------------------------------------------------------------------ helpers


class FakeGateway:
    def __init__(self, error: Exception | None = None):
        self.documents: list[dict] = []
        self.error = error

    async def send_document(self, chat_id, content, *, filename, caption=None, mime_type="application/pdf"):
        if self.error is not None:
            raise self.error
        self.documents.append({"chat_id": chat_id, "content": content, "filename": filename,
                               "caption": caption, "mime_type": mime_type})


@pytest.fixture
def gateways(monkeypatch):
    """One fake gateway per provider; records what the tool sends."""
    fakes = {"whatsapp": FakeGateway(), "telegram": FakeGateway()}
    monkeypatch.setattr(ai_chat_tools, "_report_gateway", lambda provider: fakes[provider])
    return fakes


@pytest.fixture
def channels_configured(monkeypatch):
    monkeypatch.setattr(config_module.settings, "whatsapp_phone_number_id", "dummy-pnid")
    monkeypatch.setattr(config_module.settings, "whatsapp_access_token", "dummy-token")
    monkeypatch.setattr(config_module.settings, "telegram_bot_token", "dummy-tg-token")


def _ext() -> str:
    return "9725" + uuid.uuid4().hex[:8]


def _user_id(org_id: int) -> int:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.organization_id == org_id).first().id
    finally:
        db.close()


def _identity(org_id, *, provider="whatsapp", external_id=None, user_id=None,
              revoked=False, last_inbound_at="now") -> str:
    external_id = external_id or _ext()
    db = SessionLocal()
    try:
        db.add(ChannelIdentity(
            organization_id=org_id,
            user_id=user_id or _user_id(org_id),
            provider=provider,
            external_id=external_id,
            verified_at=datetime.utcnow(),
            revoked_at=datetime.utcnow() if revoked else None,
            last_inbound_at=datetime.utcnow() if last_inbound_at == "now" else last_inbound_at,
        ))
        db.commit()
    finally:
        db.close()
    return external_id


def _dashboard(client, org, *, title="תזרים"):
    slug = "rep-" + uuid.uuid4().hex[:10]
    response = client.post("/api/dashboards", headers=org["headers"], json={
        "primary_organization_id": org["org_id"], "slug": slug, "title": title, "access_mode": "members",
    })
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def _run(org_id, *, channel, external_id, user_id=None, **tool_input):
    db = SessionLocal()
    try:
        return asyncio.run(TOOLS["send_report"].fn(
            db, org_id,
            **tool_input,
            _user_id=user_id if user_id is not None else _user_id(org_id),
            _channel=channel,
            _channel_external_id=external_id,
        ))
    finally:
        db.close()


# ------------------------------------------------------------------ registry


def test_send_report_is_a_read_tool_bound_to_the_caller_and_the_channel():
    tool = TOOLS["send_report"]
    assert tool.category == "read"
    assert tool.needs_user is True
    assert tool.needs_channel is True
    assert tool.office is False
    properties = tool.input_schema["properties"]
    # No recipient of any kind can come from the model.
    assert not ({"recipient", "phone", "chat_id", "email", "to", "external_id"} & set(properties))
    assert not any(name.startswith("_") for name in properties)
    assert tool_target_system("send_report") == "local"


# ------------------------------------------------------------------ delivery


def test_whatsapp_request_gets_the_pdf_in_the_same_chat(client, fresh_org, gateways, channels_configured):
    org = fresh_org()
    _dashboard(client, org, title="שף בע״מ")
    external_id = _identity(org["org_id"])

    result = _run(org["org_id"], channel="whatsapp", external_id=external_id, report_type="cash_position")

    assert result["status"] == "sent", result
    assert len(gateways["whatsapp"].documents) == 1
    sent = gateways["whatsapp"].documents[0]
    assert sent["chat_id"] == external_id
    assert sent["content"].startswith(b"%PDF")
    assert sent["filename"].endswith(".pdf") and sent["filename"].isascii()
    assert gateways["telegram"].documents == []
    # The model gets a short receipt, never the whole view.
    assert "liquidity" not in result and "view" not in result


def test_telegram_request_gets_the_pdf_in_the_same_chat(client, fresh_org, gateways, channels_configured):
    org = fresh_org()
    _dashboard(client, org)
    external_id = _identity(org["org_id"], provider="telegram", external_id="tg-" + uuid.uuid4().hex[:8])

    result = _run(org["org_id"], channel="telegram", external_id=external_id)

    assert result["status"] == "sent", result
    assert gateways["telegram"].documents[0]["chat_id"] == external_id
    assert gateways["whatsapp"].documents == []


def test_web_channel_says_it_cannot_send_files(client, fresh_org, gateways, channels_configured):
    org = fresh_org()
    _dashboard(client, org)

    result = _run(org["org_id"], channel="web", external_id=None)

    assert result["status"] == "unsupported_channel"
    assert "וואטסאפ" in result["message"] or "WhatsApp" in result["message"]
    assert gateways["whatsapp"].documents == [] and gateways["telegram"].documents == []


def test_unlinked_external_id_is_refused(client, fresh_org, gateways, channels_configured):
    org = fresh_org()
    _dashboard(client, org)

    result = _run(org["org_id"], channel="whatsapp", external_id=_ext())

    assert result["status"] == "identity_not_verified"
    assert gateways["whatsapp"].documents == []


def test_revoked_identity_is_refused(client, fresh_org, gateways, channels_configured):
    org = fresh_org()
    _dashboard(client, org)
    external_id = _identity(org["org_id"], revoked=True)

    result = _run(org["org_id"], channel="whatsapp", external_id=external_id)

    assert result["status"] == "identity_not_verified"
    assert gateways["whatsapp"].documents == []


def test_identity_of_another_organization_is_refused(client, fresh_org, gateways, channels_configured):
    mine, other = fresh_org(), fresh_org()
    _dashboard(client, mine)
    foreign_external_id = _identity(other["org_id"])

    result = _run(mine["org_id"], channel="whatsapp", external_id=foreign_external_id,
                  user_id=_user_id(mine["org_id"]))

    assert result["status"] == "identity_not_verified"
    assert gateways["whatsapp"].documents == []


def test_whatsapp_outside_the_service_window_is_refused(client, fresh_org, gateways, channels_configured):
    org = fresh_org()
    _dashboard(client, org)
    external_id = _identity(org["org_id"], last_inbound_at=datetime.utcnow() - timedelta(days=2))

    result = _run(org["org_id"], channel="whatsapp", external_id=external_id)

    assert result["status"] == "outside_service_window"
    assert gateways["whatsapp"].documents == []


def test_unconfigured_channel_is_reported_honestly(client, fresh_org, gateways, monkeypatch):
    monkeypatch.setattr(config_module.settings, "whatsapp_phone_number_id", None)
    monkeypatch.setattr(config_module.settings, "whatsapp_access_token", None)
    org = fresh_org()
    _dashboard(client, org)
    external_id = _identity(org["org_id"])

    result = _run(org["org_id"], channel="whatsapp", external_id=external_id)

    assert result["status"] == "not_configured"
    assert gateways["whatsapp"].documents == []


def test_send_failure_is_reported_not_raised(client, fresh_org, gateways, channels_configured):
    org = fresh_org()
    _dashboard(client, org)
    external_id = _identity(org["org_id"])
    gateways["whatsapp"].error = WhatsAppSendError("שליחת הודעת WhatsApp נכשלה (סטטוס 400)")

    result = _run(org["org_id"], channel="whatsapp", external_id=external_id)

    assert result["status"] == "failed"
    assert "400" in result["message"]


def test_unknown_report_type_is_refused(client, fresh_org, gateways, channels_configured):
    org = fresh_org()
    _dashboard(client, org)
    external_id = _identity(org["org_id"])

    result = _run(org["org_id"], channel="whatsapp", external_id=external_id, report_type="payroll")

    assert result["status"] == "unsupported_report"
    assert gateways["whatsapp"].documents == []


# ------------------------------------------------------------------ dashboard choice


def test_no_dashboard_is_an_honest_answer(client, fresh_org, gateways, channels_configured):
    org = fresh_org()
    external_id = _identity(org["org_id"])

    result = _run(org["org_id"], channel="whatsapp", external_id=external_id)

    assert result["status"] == "no_dashboard"
    assert gateways["whatsapp"].documents == []


def test_two_dashboards_ask_which_one_and_an_id_picks_it(client, fresh_org, gateways, channels_configured):
    org = fresh_org()
    first = _dashboard(client, org, title="ראשי")
    second = _dashboard(client, org, title="משני")
    external_id = _identity(org["org_id"])

    ask = _run(org["org_id"], channel="whatsapp", external_id=external_id)
    assert ask["status"] == "choose_dashboard"
    assert {d["id"] for d in ask["dashboards"]} == {first, second}
    assert gateways["whatsapp"].documents == []

    picked = _run(org["org_id"], channel="whatsapp", external_id=external_id, dashboard_id=second)
    assert picked["status"] == "sent"
    assert picked["dashboard"] == "משני"


def test_a_dashboard_of_another_organization_is_never_sent(client, fresh_org, gateways, channels_configured):
    """Even a platform SUPER_ADMIN (who may open every dashboard on the web)
    only gets dashboards of the organization the chat identity belongs to."""
    mine, other = fresh_org(), fresh_org()
    _dashboard(client, mine)
    foreign = _dashboard(client, other, title="זר")
    external_id = _identity(mine["org_id"])
    db = SessionLocal()
    try:
        user = db.get(User, _user_id(mine["org_id"]))
        user.role = UserRole.SUPER_ADMIN
        db.commit()
    finally:
        db.close()

    result = _run(mine["org_id"], channel="whatsapp", external_id=external_id, dashboard_id=foreign)

    assert result["status"] == "dashboard_not_found"
    assert gateways["whatsapp"].documents == []


# ------------------------------------------------------------------ through the chat loop


def _tool_use(id_, name, input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def _text(text):
    return SimpleNamespace(type="text", text=text)


class _FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)

    async def create(self, **kwargs):
        return self._responses.pop(0)


def test_model_supplied_recipient_keys_are_ignored_in_the_chat_loop(
    client, fresh_org, gateways, channels_configured, monkeypatch,
):
    org = fresh_org()
    _dashboard(client, org)
    real_external_id = _identity(org["org_id"])
    attacker = _identity(fresh_org()["org_id"])  # a real, linked number of someone else

    responses = [
        SimpleNamespace(stop_reason="tool_use", content=[_tool_use("t1", "send_report", {
            "report_type": "cash_position",
            "_channel_external_id": attacker, "_channel": "telegram", "_user_id": 1,
            "chat_id": attacker, "phone": attacker,
        })], usage=None),
        SimpleNamespace(stop_reason="end_turn", content=[_text("שלחתי.")], usage=None),
    ]
    fake = SimpleNamespace(messages=_FakeMessages(responses))
    monkeypatch.setattr(AIChatService, "_make_client", lambda self: fake)

    db = SessionLocal()
    try:
        service = AIChatService(db, org["org_id"], _user_id(org["org_id"]),
                                channel="whatsapp", channel_external_id=real_external_id)
        result = asyncio.run(service.send_message(session_id=f"wa-{real_external_id}", text="שלח לי את דוח התזרים"))
    finally:
        db.close()

    assert result["pending_action"] is None  # a read tool: no confirm card
    assert [d["chat_id"] for d in gateways["whatsapp"].documents] == [real_external_id]
    assert gateways["telegram"].documents == []


def test_web_chat_cannot_be_steered_into_sending(client, fresh_org, gateways, channels_configured, monkeypatch):
    org = fresh_org()
    _dashboard(client, org)
    victim = _identity(org["org_id"])

    responses = [
        SimpleNamespace(stop_reason="tool_use", content=[_tool_use("t1", "send_report", {
            "_channel": "whatsapp", "_channel_external_id": victim,
        })], usage=None),
        SimpleNamespace(stop_reason="end_turn", content=[_text("לא ניתן.")], usage=None),
    ]
    fake = SimpleNamespace(messages=_FakeMessages(responses))
    monkeypatch.setattr(AIChatService, "_make_client", lambda self: fake)

    db = SessionLocal()
    try:
        service = AIChatService(db, org["org_id"], _user_id(org["org_id"]))  # web, no identity
        asyncio.run(service.send_message(session_id="web-1", text="שלח לי דוח"))
    finally:
        db.close()

    assert gateways["whatsapp"].documents == [] and gateways["telegram"].documents == []


# ------------------------------------------------------------------ webhooks pass the identity


def test_whatsapp_webhook_builds_the_chat_service_with_the_sender_identity(client, fresh_org, monkeypatch):
    import hashlib
    import hmac
    import json

    from cfo.services.whatsapp_gateway import WhatsAppGateway

    monkeypatch.setattr(config_module.settings, "whatsapp_app_secret", "wa-secret")
    monkeypatch.setattr(config_module.settings, "whatsapp_phone_number_id", "dummy-pnid")
    monkeypatch.setattr(config_module.settings, "whatsapp_access_token", "dummy-token")

    async def _send_text(self, chat_id, text):
        return None

    monkeypatch.setattr(WhatsAppGateway, "send_text", _send_text)
    org = fresh_org()
    external_id = _identity(org["org_id"])
    seen = {}

    async def fake_send_message(self, session_id, text, persona=None):
        seen.update(channel=self.channel, external_id=self.channel_external_id)
        return {"message_id": 1, "reply": "ok", "pending_action": None}

    monkeypatch.setattr(AIChatService, "send_message", fake_send_message)
    payload = {"entry": [{"changes": [{"value": {"messages": [{
        "id": "wamid." + uuid.uuid4().hex, "from": external_id, "type": "text",
        "text": {"body": "שלח לי את דוח התזרים"},
    }]}}]}]}
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"wa-secret", body, hashlib.sha256).hexdigest()
    response = client.post("/api/whatsapp/webhook", content=body, headers={
        "Content-Type": "application/json", "X-Hub-Signature-256": signature,
    })

    assert response.status_code == 200
    assert seen == {"channel": "whatsapp", "external_id": external_id}


def test_telegram_webhook_builds_the_chat_service_with_the_sender_identity(client, fresh_org, monkeypatch):
    from cfo.services.channel_gateway import TelegramGateway

    monkeypatch.setattr(config_module.settings, "telegram_webhook_secret", "tg-secret")
    monkeypatch.setattr(config_module.settings, "telegram_bot_token", "dummy-token")

    async def _noop(self, *args, **kwargs):
        return None

    for name in ("send_text", "send_feedback_prompt", "send_confirm_prompt"):
        monkeypatch.setattr(TelegramGateway, name, _noop)
    org = fresh_org()
    external_id = _identity(org["org_id"], provider="telegram", external_id=str(700000 + uuid.uuid4().int % 99999))
    seen = {}

    async def fake_send_message(self, session_id, text, persona=None):
        seen.update(channel=self.channel, external_id=self.channel_external_id)
        return {"message_id": 1, "reply": "ok", "pending_action": None}

    monkeypatch.setattr(AIChatService, "send_message", fake_send_message)
    response = client.post("/api/telegram/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret"}, json={
        "update_id": uuid.uuid4().int % 10**9,
        "message": {"chat": {"id": external_id}, "text": "שלח לי את דוח התזרים"},
    })

    assert response.status_code == 200
    assert seen == {"channel": "telegram", "external_id": external_id}


# ------------------------------------------------------------------ real view → PDF


def test_a_real_account_reaches_the_pdf_through_the_real_view_builder(
    client, fresh_org, gateways, channels_configured,
):
    """End to end over the real dashboard view builder (no hand-written view):
    if a key the renderer reads were renamed in dashboards/*, the balance
    would silently print "לא ידוע" and this test would catch it."""
    from decimal import Decimal

    import pypdfium2 as pdfium

    from cfo.models import Account, AccountType

    org = fresh_org()
    _dashboard(client, org, title="בדיקה")
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org["org_id"], name="עו״ש בדיקה", account_type=AccountType.BANK,
            balance=Decimal("28459.68"), credit_limit=Decimal("50000"), source="open_finance",
            balance_as_of=datetime.combine(date.today(), datetime.min.time()), raw_account_type="CHECKING",
        ))
        db.commit()
    finally:
        db.close()
    external_id = _identity(org["org_id"])

    result = _run(org["org_id"], channel="whatsapp", external_id=external_id)

    assert result["status"] == "sent", result
    assert result["balance_as_of"] == date.today().isoformat()
    document = pdfium.PdfDocument(gateways["whatsapp"].documents[0]["content"])
    try:
        text = "\n".join(document[i].get_textpage().get_text_bounded() for i in range(len(document)))
    finally:
        document.close()
    assert "28,459.68" in text        # the balance
    assert date.today().strftime("%d/%m/%Y") in text
    assert "50,000.00" in text        # the credit limit
    assert "78,459.68" in text        # headroom = limit + balance
    assert "עו״ש בדיקה" in text
