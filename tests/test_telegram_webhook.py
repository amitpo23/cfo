"""Package 3 (2026-07-26 conversational-channels plan), decision 7:
POST /api/telegram/webhook. No live network call is made anywhere in this
file — anthropic and httpx/telegram are always mocked."""
from types import SimpleNamespace

import pytest

import re

from cfo import config as config_module
from cfo.api.routes import telegram_webhook as tw_module
from cfo.database import SessionLocal
from cfo.models import ChatMessage, MoshkoFeedback, MoshkoGap, User
from cfo.services import channel_link_service as link_service_module
from cfo.services.ai_chat_service import AIChatService
from cfo.services.channel_link_service import issue_link_code, redeem_link_code
from cfo.services.channel_gateway import TelegramGateway

_CODE_RE = re.compile(r"\b(\d{6})\b")

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
    calls = {
        "send_text": [], "send_confirm_prompt": [], "answer_callback_query": [],
        "send_feedback_prompt": [],
    }

    async def _send_text(self, chat_id, text):
        calls["send_text"].append((chat_id, text))

    async def _send_confirm_prompt(self, chat_id, text, message_id):
        calls["send_confirm_prompt"].append((chat_id, text, message_id))

    async def _answer_callback_query(self, callback_query_id, text=None):
        calls["answer_callback_query"].append((callback_query_id, text))

    async def _send_feedback_prompt(self, chat_id, text, message_id):
        calls["send_feedback_prompt"].append((chat_id, text, message_id))

    monkeypatch.setattr(TelegramGateway, "send_text", _send_text)
    monkeypatch.setattr(TelegramGateway, "send_confirm_prompt", _send_confirm_prompt)
    monkeypatch.setattr(TelegramGateway, "answer_callback_query", _answer_callback_query)
    monkeypatch.setattr(TelegramGateway, "send_feedback_prompt", _send_feedback_prompt)
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
    # כל תשובת מושקו רגילה יוצאת עם מקלדת פידבק 👍/👎/❓, לא עם send_text
    # פשוט — כדי לפתוח את אותו מסלול הפידבק כמו בווב (W1.2).
    assert fake_gateway["send_feedback_prompt"][-1] == ("chat-linked-1", "התשובה שלי", 42)
    assert not fake_gateway["send_text"]


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
    chat_id, text, message_id = fake_gateway["send_confirm_prompt"][0]
    assert (chat_id, message_id) == ("chat-pending-1", 77)
    assert text.startswith("לאשר את הפעולה?")
    assert not fake_gateway["send_text"]


def test_confirm_prompt_discloses_the_actual_arguments(
    client, telegram_configured, fake_gateway, monkeypatch, fresh_org,
):
    """הכפתור בטלגרם חייב להראות *מה* מאושר, לא רק שאלה כללית.

    ב-UI המשתמש רואה את ה-input כ-JSON מתחת לכפתור; אם בטלגרם רואים רק את
    הטקסט החופשי של המודל, לחיצה על 'אשר' יכולה לשלוח דוח כספי לכתובת
    שהמשתמש מעולם לא קרא."""
    iso = fresh_org()
    _link(iso["org_id"], "chat-pending-2")

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

    r = _post(client, {
        "update_id": 501,
        "message": {"chat": {"id": "chat-pending-2"}, "text": "שלח לבנק רווח והפסד"},
    })
    assert r.status_code == 200
    _, text, _ = fake_gateway["send_confirm_prompt"][0]
    assert "bank@example.com" in text
    assert "profit_loss" in text
    assert "שליחת דוח במייל" in text


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

    r = _post(client, {
        "update_id": 700,
        "callback_query": {
            "id": "cbq-2",
            "data": "cancel:77",
            "message": {"chat": {"id": "chat-cancel-1"}},
        },
    })
    assert r.status_code == 200
    assert called == {"confirm": 0, "cancel": 1, "message_id": 77}
    assert any("בוטל" in text for _, text in fake_gateway["send_text"])


def _seed_telegram_assistant_message(org_id, user_id, external_id, answer="התשובה שלי"):
    """A real ChatMessage row (not mocked) — the feedback callback reads
    through record_feedback the SAME way the web /ai/chat/{id}/feedback
    route does, so it needs an actual row to find."""
    db = SessionLocal()
    try:
        session_id = f"tg-{external_id}"
        db.add(ChatMessage(
            organization_id=org_id, user_id=user_id, session_id=session_id,
            role="user", content="שאלה",
        ))
        db.flush()
        assistant = ChatMessage(
            organization_id=org_id, user_id=user_id, session_id=session_id,
            role="assistant", content=answer,
        )
        db.add(assistant)
        db.commit()
        db.refresh(assistant)
        return assistant.id
    finally:
        db.close()


def _feedback_callback_payload(update_id, chat_id, category, message_id, callback_id="cbq-fb"):
    return {
        "update_id": update_id,
        "callback_query": {
            "id": callback_id,
            "data": f"fb:{category}:{message_id}",
            "message": {"chat": {"id": chat_id}},
        },
    }


def test_callback_feedback_thumbs_down_creates_gap_and_acks(
    client, telegram_configured, fake_gateway, fresh_org,
):
    iso = fresh_org()
    org_id = iso["org_id"]
    external_id = "chat-fb-1"
    _link(org_id, external_id)
    user_id = _user_id_for_org(org_id)
    message_id = _seed_telegram_assistant_message(org_id, user_id, external_id)

    r = _post(client, _feedback_callback_payload(950, external_id, "inaccurate", message_id))
    assert r.status_code == 200
    assert any("נרשם" in text for _, text in fake_gateway["send_text"])
    assert fake_gateway["answer_callback_query"]

    db = SessionLocal()
    try:
        feedback = db.query(MoshkoFeedback).filter(
            MoshkoFeedback.organization_id == org_id,
            MoshkoFeedback.message_id == message_id,
        ).all()
        assert len(feedback) == 1
        assert feedback[0].category == "inaccurate"
        assert feedback[0].channel == "telegram"

        gaps = db.query(MoshkoGap).filter(MoshkoGap.organization_id == org_id).all()
        assert len(gaps) == 1
        assert gaps[0].gap_kind == "user_flagged"
        # MoshkoGap אין לו עמודת source — הערוץ נישא ע"י תחילית session_id
        # ("tg-"), בדיוק כמו ש-MoshkoFeedback.channel נגזר ממנה.
        assert gaps[0].session_id.startswith("tg-")
    finally:
        db.close()


def test_callback_feedback_thumbs_up_does_not_create_gap(
    client, telegram_configured, fake_gateway, fresh_org,
):
    iso = fresh_org()
    org_id = iso["org_id"]
    external_id = "chat-fb-2"
    _link(org_id, external_id)
    user_id = _user_id_for_org(org_id)
    message_id = _seed_telegram_assistant_message(org_id, user_id, external_id)

    r = _post(client, _feedback_callback_payload(951, external_id, "helpful", message_id))
    assert r.status_code == 200

    db = SessionLocal()
    try:
        assert db.query(MoshkoFeedback).filter(
            MoshkoFeedback.organization_id == org_id,
            MoshkoFeedback.message_id == message_id,
        ).count() == 1
        assert db.query(MoshkoGap).filter(MoshkoGap.organization_id == org_id).count() == 0
    finally:
        db.close()


def test_callback_feedback_double_tap_does_not_duplicate_rows(
    client, telegram_configured, fake_gateway, fresh_org,
):
    """לחיצה כפולה על אותו כפתור (שני callback_query נפרדים, לא retry של
    אותו update_id) לא יוצרת פידבק/gap כפולים."""
    iso = fresh_org()
    org_id = iso["org_id"]
    external_id = "chat-fb-3"
    _link(org_id, external_id)
    user_id = _user_id_for_org(org_id)
    message_id = _seed_telegram_assistant_message(org_id, user_id, external_id)

    r1 = _post(client, _feedback_callback_payload(
        952, external_id, "inaccurate", message_id, callback_id="cbq-a",
    ))
    r2 = _post(client, _feedback_callback_payload(
        953, external_id, "inaccurate", message_id, callback_id="cbq-b",
    ))
    assert r1.status_code == 200 and r2.status_code == 200

    db = SessionLocal()
    try:
        assert db.query(MoshkoFeedback).filter(
            MoshkoFeedback.organization_id == org_id,
            MoshkoFeedback.message_id == message_id,
        ).count() == 1
        assert db.query(MoshkoGap).filter(MoshkoGap.organization_id == org_id).count() == 1
    finally:
        db.close()


def test_callback_feedback_switch_from_down_to_up_keeps_existing_gap(
    client, telegram_configured, fake_gateway, fresh_org,
):
    """שינוי דעת המשתמש (👎 ואז 👍) מעדכן את שורת הפידבק, אבל לא מוחק
    gap שכבר נפתח — הוא לא בגדר "לחיצה כפולה" אלא ורדיקט חדש."""
    iso = fresh_org()
    org_id = iso["org_id"]
    external_id = "chat-fb-4"
    _link(org_id, external_id)
    user_id = _user_id_for_org(org_id)
    message_id = _seed_telegram_assistant_message(org_id, user_id, external_id)

    _post(client, _feedback_callback_payload(
        954, external_id, "inaccurate", message_id, callback_id="cbq-c",
    ))
    _post(client, _feedback_callback_payload(
        955, external_id, "helpful", message_id, callback_id="cbq-d",
    ))

    db = SessionLocal()
    try:
        feedback = db.query(MoshkoFeedback).filter(
            MoshkoFeedback.organization_id == org_id,
            MoshkoFeedback.message_id == message_id,
        ).one()
        assert feedback.category == "helpful"
        assert db.query(MoshkoGap).filter(MoshkoGap.organization_id == org_id).count() == 1
    finally:
        db.close()


def test_callback_feedback_from_unlinked_identity_is_rejected(
    client, telegram_configured, fake_gateway,
):
    r = _post(client, _feedback_callback_payload(956, "chat-fb-unlinked", "helpful", 999))
    assert r.status_code == 200
    assert fake_gateway["answer_callback_query"][-1] == ("cbq-fb", "החשבון לא מקושר")


def test_sticker_message_is_still_silently_ignored(client, telegram_configured, fake_gateway, fresh_org):
    """No text, no photo, no document — unchanged regression check for the
    non-text non-receipt case (voice/sticker/etc)."""
    iso = fresh_org()
    _link(iso["org_id"], "chat-sticker-1")

    r = _post(client, {
        "update_id": 750,
        "message": {"chat": {"id": "chat-sticker-1"}, "sticker": {"file_id": "abc"}},
    })
    assert r.status_code == 200
    assert not fake_gateway["send_text"]


def test_photo_from_unlinked_identity_is_never_downloaded_or_processed(
    client, telegram_configured, fake_gateway, monkeypatch,
):
    """Package A (moshko-full-bot plan): an unlinked identity sending a
    receipt photo gets the same static link-instructions reply as any other
    unlinked message — never downloaded, never sent to the LLM."""
    download_calls = {"n": 0}
    intake_calls = {"n": 0}

    async def fake_download(file_id, **kw):
        download_calls["n"] += 1
        return b"should never be called"

    async def fake_intake(*a, **kw):
        intake_calls["n"] += 1
        return {"status": "created", "expense_id": 1, "message": "x"}

    monkeypatch.setattr(
        "cfo.services.telegram_files.download_telegram_file", fake_download,
    )
    monkeypatch.setattr(
        "cfo.services.chat_expense_intake.intake_receipt_bytes", fake_intake,
    )

    r = _post(client, {
        "update_id": 760,
        "message": {
            "chat": {"id": "chat-unlinked-photo"},
            "photo": [{"file_id": "small", "file_size": 100}, {"file_id": "big", "file_size": 5000}],
        },
    })
    assert r.status_code == 200
    assert download_calls["n"] == 0
    assert intake_calls["n"] == 0
    assert fake_gateway["send_text"]
    last_text = fake_gateway["send_text"][-1][1]
    assert "מקושר" in last_text or "לקשר" in last_text


def test_photo_from_linked_identity_downloads_and_replies_with_summary(
    client, telegram_configured, fake_gateway, monkeypatch, fresh_org,
):
    iso = fresh_org()
    _link(iso["org_id"], "chat-photo-linked-1")

    download_calls = {}
    intake_calls = {}

    async def fake_download(file_id, **kw):
        download_calls["file_id"] = file_id
        return b"fake-jpeg-bytes"

    async def fake_intake(db, organization_id, content, *, media_type=None, source="telegram",
                           uploaded_by_user_id=None):
        intake_calls["organization_id"] = organization_id
        intake_calls["content"] = content
        intake_calls["media_type"] = media_type
        intake_calls["source"] = source
        intake_calls["uploaded_by_user_id"] = uploaded_by_user_id
        return {
            "status": "created", "expense_id": 55,
            "message": "קלטתי קבלה מ-שופרסל. סכום: 118.00 ₪.",
        }

    monkeypatch.setattr(
        "cfo.services.telegram_files.download_telegram_file", fake_download,
    )
    monkeypatch.setattr(
        "cfo.services.chat_expense_intake.intake_receipt_bytes", fake_intake,
    )

    r = _post(client, {
        "update_id": 770,
        "message": {
            "chat": {"id": "chat-photo-linked-1"},
            "photo": [{"file_id": "small", "file_size": 100}, {"file_id": "big", "file_size": 5000}],
        },
    })
    assert r.status_code == 200
    assert download_calls["file_id"] == "big"  # largest resolution picked
    assert intake_calls["organization_id"] == iso["org_id"]
    assert intake_calls["source"] == "telegram"
    assert intake_calls["content"] == b"fake-jpeg-bytes"

    last_text = fake_gateway["send_text"][-1][1]
    assert "שופרסל" in last_text
    assert "תייק" in last_text  # offers filing, but does not auto-file
    assert "55" in last_text


def test_pdf_document_from_linked_identity_is_recognized_as_a_receipt(
    client, telegram_configured, fake_gateway, monkeypatch, fresh_org,
):
    iso = fresh_org()
    _link(iso["org_id"], "chat-pdf-linked-1")

    intake_calls = {}

    async def fake_download(file_id, **kw):
        return b"%PDF-1.4 fake"

    async def fake_intake(db, organization_id, content, *, media_type=None, source="telegram",
                           uploaded_by_user_id=None):
        intake_calls["media_type"] = media_type
        return {"status": "unreadable", "message": "לא הצלחתי לקרוא את הקבלה."}

    monkeypatch.setattr(
        "cfo.services.telegram_files.download_telegram_file", fake_download,
    )
    monkeypatch.setattr(
        "cfo.services.chat_expense_intake.intake_receipt_bytes", fake_intake,
    )

    r = _post(client, {
        "update_id": 780,
        "message": {
            "chat": {"id": "chat-pdf-linked-1"},
            "document": {"file_id": "doc-1", "mime_type": "application/pdf"},
        },
    })
    assert r.status_code == 200
    assert intake_calls["media_type"] == "application/pdf"
    assert "לא הצלחתי" in fake_gateway["send_text"][-1][1]


def test_non_pdf_non_image_document_is_ignored(client, telegram_configured, fake_gateway, fresh_org):
    iso = fresh_org()
    _link(iso["org_id"], "chat-doc-other-1")

    r = _post(client, {
        "update_id": 790,
        "message": {
            "chat": {"id": "chat-doc-other-1"},
            "document": {"file_id": "doc-2", "mime_type": "application/zip"},
        },
    })
    assert r.status_code == 200
    assert not fake_gateway["send_text"]


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


# --- package G (2026-07-27b plan): email-based verification via webhook --- #

@pytest.fixture
def fake_smtp(monkeypatch):
    """Records every send_email_smtp call instead of hitting real SMTP —
    monkeypatched on channel_link_service, the module that imports it."""
    calls = []

    async def _fake_send(to, subject, body, settings, *, attachments=None):
        calls.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr(link_service_module, "send_email_smtp", _fake_send)
    return calls


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


def test_email_from_unlinked_identity_starts_verification_without_llm(
    client, telegram_configured, fake_gateway, fake_smtp, monkeypatch, fresh_org,
):
    called = {"n": 0}

    async def fake_send_message(self, *a, **kw):
        called["n"] += 1
        return {"message_id": 1, "reply": "x", "pending_action": None}

    monkeypatch.setattr(AIChatService, "send_message", fake_send_message)

    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])

    r = _post(client, {
        "update_id": 900,
        "message": {"chat": {"id": "chat-email-1"}, "text": known_email},
    })
    assert r.status_code == 200
    assert called["n"] == 0
    assert len(fake_smtp) == 1
    assert "קוד" in fake_gateway["send_text"][-1][1]


def test_email_from_unlinked_identity_gives_identical_reply_for_unknown_email(
    client, telegram_configured, fake_gateway, fake_smtp,
):
    """Anti-enumeration must hold at the webhook layer too: a made-up email
    typed into the chat gets the exact same reply as a registered one."""
    r_unknown = _post(client, {
        "update_id": 901,
        "message": {"chat": {"id": "chat-email-unknown"}, "text": "nobody-at-all@example.com"},
    })
    assert r_unknown.status_code == 200
    unknown_reply = fake_gateway["send_text"][-1][1]
    assert len(fake_smtp) == 0  # no email actually sent for the unknown address

    r_known = _post(client, {
        "update_id": 902,
        "message": {"chat": {"id": "chat-email-known-cmp"}, "text": "owner@example.com"},
    })
    assert r_known.status_code == 200
    known_reply = fake_gateway["send_text"][-1][1]

    assert unknown_reply == known_reply


def test_six_digit_code_completes_verification_and_welcomes(
    client, telegram_configured, fake_gateway, fake_smtp, fresh_org,
):
    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])

    r1 = _post(client, {
        "update_id": 910,
        "message": {"chat": {"id": "chat-email-complete"}, "text": known_email},
    })
    assert r1.status_code == 200
    code = _extract_code(fake_smtp[-1]["body"])

    r2 = _post(client, {
        "update_id": 911,
        "message": {"chat": {"id": "chat-email-complete"}, "text": code,
                    "from": {"first_name": "Yossi"}},
    })
    assert r2.status_code == 200
    assert "הצליח" in fake_gateway["send_text"][-1][1]

    from cfo.models import ChannelIdentity
    db = SessionLocal()
    try:
        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.provider == "telegram",
            ChannelIdentity.external_id == "chat-email-complete",
        ).first()
        assert identity is not None
        assert identity.verified_at is not None
        assert identity.display_name == "Yossi"
    finally:
        db.close()


def test_wrong_six_digit_code_returns_error_message_not_llm(
    client, telegram_configured, fake_gateway, fake_smtp, monkeypatch, fresh_org,
):
    called = {"n": 0}

    async def fake_send_message(self, *a, **kw):
        called["n"] += 1
        return {"message_id": 1, "reply": "x", "pending_action": None}

    monkeypatch.setattr(AIChatService, "send_message", fake_send_message)

    iso = fresh_org()
    known_email = _email_for_org(iso["org_id"])
    _post(client, {
        "update_id": 920,
        "message": {"chat": {"id": "chat-email-wrong"}, "text": known_email},
    })

    r = _post(client, {
        "update_id": 921,
        "message": {"chat": {"id": "chat-email-wrong"}, "text": "000000"},
    })
    assert r.status_code == 200
    assert called["n"] == 0
    assert "שגוי" in fake_gateway["send_text"][-1][1]


def test_super_admin_email_cannot_be_linked_via_webhook(
    client, telegram_configured, fake_gateway, fake_smtp,
):
    admin_email = "super-admin-webhook-pkg-g@example.com"
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == admin_email).first() is None:
            db.add(User(
                email=admin_email, password_hash="x", full_name="Super Admin",
                organization_id=None, is_active=True,
            ))
            db.commit()
    finally:
        db.close()

    r = _post(client, {
        "update_id": 930,
        "message": {"chat": {"id": "chat-superadmin-webhook"}, "text": admin_email},
    })
    assert r.status_code == 200
    assert len(fake_smtp) == 0  # no email sent — never linkable
    assert "קוד" in fake_gateway["send_text"][-1][1]  # same reply as any other email
