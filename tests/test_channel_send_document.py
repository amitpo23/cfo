"""שליחת קובץ (PDF) לשיחה — WhatsApp (Cloud API) ו-Telegram (sendDocument).

מושקו מחזיר דוח כקובץ לאותה שיחה שבה התבקש. הבדיקות כאן מזייפות את שכבת
httpx עצמה (לא את מתודות ה-gateway), כך שכל רגרסיה בבניית הבקשה או
בבדיקת התשובה נתפסת. אפס קריאות רשת: חומת הרשת ב-conftest חוסמת כל חיבור.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from cfo.services.channel_gateway import TelegramGateway, TelegramSendError
from cfo.services.whatsapp_gateway import (
    WhatsAppGateway,
    WhatsAppNotConfiguredError,
    WhatsAppSendError,
)

PDF = b"%PDF-1.4\n% fake report\n"


def _wa() -> WhatsAppGateway:
    return WhatsAppGateway(phone_number_id="pnid", access_token="tok", api_version="v21.0")


def _recording_post(responses: list[httpx.Response]):
    """מחזיר post מזויף שרושם כל קריאה ומחזיר את התשובות לפי הסדר."""
    calls: list[dict] = []

    async def _fake_post(self, url, json=None, headers=None, data=None, files=None, **kwargs):
        calls.append({"url": url, "json": json, "headers": headers, "data": data, "files": files})
        response = responses[len(calls) - 1]
        response.request = httpx.Request("POST", url)
        return response

    return _fake_post, calls


# --------------------------------------------------------------- WhatsApp


def test_whatsapp_send_document_uploads_media_then_sends_document_message(monkeypatch):
    fake, calls = _recording_post([
        httpx.Response(200, json={"id": "media-123"}),
        httpx.Response(200, json={"messages": [{"id": "wamid.1"}]}),
    ])
    monkeypatch.setattr(httpx.AsyncClient, "post", fake)

    asyncio.run(_wa().send_document(
        "972500000000", PDF, filename="cash-position.pdf", caption="דוח מצב מזומנים",
    ))

    assert len(calls) == 2
    upload, message = calls
    assert upload["url"] == "https://graph.facebook.com/v21.0/pnid/media"
    assert upload["headers"] == {"Authorization": "Bearer tok"}
    assert upload["data"] == {"messaging_product": "whatsapp", "type": "application/pdf"}
    name, content, mime = upload["files"]["file"]
    assert (name, content, mime) == ("cash-position.pdf", PDF, "application/pdf")

    assert message["url"] == "https://graph.facebook.com/v21.0/pnid/messages"
    assert message["json"] == {
        "messaging_product": "whatsapp",
        "to": "972500000000",
        "type": "document",
        "document": {
            "id": "media-123",
            "filename": "cash-position.pdf",
            "caption": "דוח מצב מזומנים",
        },
    }


def test_whatsapp_send_document_raises_when_upload_is_rejected(monkeypatch):
    fake, calls = _recording_post([
        httpx.Response(400, json={"error": {"message": "Invalid parameter"}}),
    ])
    monkeypatch.setattr(httpx.AsyncClient, "post", fake)

    with pytest.raises(WhatsAppSendError) as exc_info:
        asyncio.run(_wa().send_document("972500000000", PDF, filename="r.pdf"))
    assert "400" in str(exc_info.value)
    assert len(calls) == 1  # no document message after a failed upload


def test_whatsapp_send_document_raises_when_upload_returns_no_media_id(monkeypatch):
    fake, _calls = _recording_post([httpx.Response(200, json={})])
    monkeypatch.setattr(httpx.AsyncClient, "post", fake)

    with pytest.raises(WhatsAppSendError):
        asyncio.run(_wa().send_document("972500000000", PDF, filename="r.pdf"))


def test_whatsapp_send_document_raises_when_document_message_is_rejected(monkeypatch):
    fake, _calls = _recording_post([
        httpx.Response(200, json={"id": "media-123"}),
        httpx.Response(470, json={"error": {"message": "Re-engagement message"}}),
    ])
    monkeypatch.setattr(httpx.AsyncClient, "post", fake)

    with pytest.raises(WhatsAppSendError) as exc_info:
        asyncio.run(_wa().send_document("972500000000", PDF, filename="r.pdf"))
    assert "470" in str(exc_info.value)


def test_whatsapp_send_document_truncates_long_caption(monkeypatch):
    fake, calls = _recording_post([
        httpx.Response(200, json={"id": "m"}),
        httpx.Response(200, json={"messages": [{"id": "w"}]}),
    ])
    monkeypatch.setattr(httpx.AsyncClient, "post", fake)

    asyncio.run(_wa().send_document("1", PDF, filename="r.pdf", caption="א" * 5000))
    assert len(calls[1]["json"]["document"]["caption"]) <= 1024


def test_whatsapp_send_document_uses_an_ascii_upload_filename(monkeypatch):
    fake, calls = _recording_post([
        httpx.Response(200, json={"id": "m"}),
        httpx.Response(200, json={"messages": [{"id": "w"}]}),
    ])
    monkeypatch.setattr(httpx.AsyncClient, "post", fake)

    asyncio.run(_wa().send_document("1", PDF, filename="דוח.pdf"))
    upload_name = calls[0]["files"]["file"][0]
    assert upload_name.isascii() and upload_name.endswith(".pdf")


def test_whatsapp_send_document_refuses_without_configuration(monkeypatch):
    async def _never(*_args, **_kwargs):  # pragma: no cover - must not run
        raise AssertionError("no HTTP call without configuration")

    monkeypatch.setattr(httpx.AsyncClient, "post", _never)
    gateway = WhatsAppGateway(phone_number_id="", access_token="", api_version="v21.0")
    with pytest.raises(WhatsAppNotConfiguredError):
        asyncio.run(gateway.send_document("1", PDF, filename="r.pdf"))


def test_whatsapp_send_document_rejects_empty_content(monkeypatch):
    async def _never(*_args, **_kwargs):  # pragma: no cover - must not run
        raise AssertionError("no HTTP call for an empty file")

    monkeypatch.setattr(httpx.AsyncClient, "post", _never)
    with pytest.raises(WhatsAppSendError):
        asyncio.run(_wa().send_document("1", b"", filename="r.pdf"))


# --------------------------------------------------------------- Telegram


def test_telegram_send_document_posts_multipart_send_document(monkeypatch):
    fake, calls = _recording_post([httpx.Response(200, json={"ok": True, "result": {}})])
    monkeypatch.setattr(httpx.AsyncClient, "post", fake)

    asyncio.run(TelegramGateway(token="T0KEN").send_document(
        "555", PDF, filename="cash-position.pdf", caption="דוח מצב מזומנים",
    ))

    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == "https://api.telegram.org/botT0KEN/sendDocument"
    assert call["data"] == {"chat_id": "555", "caption": "דוח מצב מזומנים"}
    assert call["files"]["document"] == ("cash-position.pdf", PDF, "application/pdf")


def test_telegram_send_document_raises_on_api_error_without_leaking_token(monkeypatch):
    fake, _calls = _recording_post([
        httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"}),
    ])
    monkeypatch.setattr(httpx.AsyncClient, "post", fake)

    with pytest.raises(TelegramSendError) as exc_info:
        asyncio.run(TelegramGateway(token="SECRET-TOKEN").send_document("1", PDF, filename="r.pdf"))
    assert "chat not found" in str(exc_info.value)
    assert "SECRET-TOKEN" not in str(exc_info.value)


def test_telegram_send_document_raises_when_ok_is_false_on_200(monkeypatch):
    fake, _calls = _recording_post([httpx.Response(200, json={"ok": False, "description": "nope"})])
    monkeypatch.setattr(httpx.AsyncClient, "post", fake)

    with pytest.raises(TelegramSendError):
        asyncio.run(TelegramGateway(token="T").send_document("1", PDF, filename="r.pdf"))


def test_telegram_send_document_transport_error_does_not_leak_token(monkeypatch):
    async def _boom(self, url, **kwargs):
        raise httpx.ConnectError(f"cannot reach {url}")

    monkeypatch.setattr(httpx.AsyncClient, "post", _boom)
    with pytest.raises(TelegramSendError) as exc_info:
        asyncio.run(TelegramGateway(token="SECRET-TOKEN").send_document("1", PDF, filename="r.pdf"))
    assert "SECRET-TOKEN" not in str(exc_info.value)
    # The original httpx error carries the URL (and so the bot token); it must
    # not ride along as the exception's cause/context into a logged traceback.
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True


def test_telegram_send_document_refuses_without_token(monkeypatch):
    async def _never(*_args, **_kwargs):  # pragma: no cover - must not run
        raise AssertionError("no HTTP call without a token")

    monkeypatch.setattr(httpx.AsyncClient, "post", _never)
    with pytest.raises(TelegramSendError):
        asyncio.run(TelegramGateway(token="").send_document("1", PDF, filename="r.pdf"))
