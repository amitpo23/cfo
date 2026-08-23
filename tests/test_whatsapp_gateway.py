"""Task 2 (2026-08-23 moshko-usability plan): WhatsApp send failures must
stop being swallowed. Before this file, `_post_messages` awaited
`client.post(...)` and threw the response away unread — every Meta error
(expired token, blocked number, unapproved template, any 4xx/5xx) looked
exactly like success to every caller. These tests mock the httpx layer
itself (not WhatsAppGateway's own methods) so a regression that reintroduces
the silent-swallow bug is actually caught."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from cfo.services.whatsapp_gateway import WhatsAppGateway, WhatsAppSendError


def _gateway() -> WhatsAppGateway:
    return WhatsAppGateway(phone_number_id="pnid", access_token="tok", api_version="v21.0")


def _mock_post(status_code: int, *, json_body: dict | None = None, text: str | None = None):
    async def _fake_post(self, url, json=None, headers=None, **kwargs):
        request = httpx.Request("POST", url)
        if json_body is not None:
            return httpx.Response(status_code, request=request, json=json_body)
        return httpx.Response(status_code, request=request, text=text or "")
    return _fake_post


def test_post_messages_raises_on_4xx_response(monkeypatch):
    """Meta's classic 'expired access token' shape — must surface as a clear
    exception, not silently return as if the message was sent."""
    monkeypatch.setattr(
        httpx.AsyncClient, "post",
        _mock_post(401, json_body={"error": {"message": "Error validating access token"}}),
    )
    gateway = _gateway()
    with pytest.raises(WhatsAppSendError) as exc_info:
        asyncio.run(gateway._post_messages({"messaging_product": "whatsapp"}))
    assert "401" in str(exc_info.value)
    assert "access token" in str(exc_info.value)


def test_post_messages_raises_on_5xx_response(monkeypatch):
    monkeypatch.setattr(httpx.AsyncClient, "post", _mock_post(500, text="Internal Server Error"))
    gateway = _gateway()
    with pytest.raises(WhatsAppSendError) as exc_info:
        asyncio.run(gateway._post_messages({"messaging_product": "whatsapp"}))
    assert "500" in str(exc_info.value)


def test_post_messages_succeeds_silently_on_2xx_response(monkeypatch):
    monkeypatch.setattr(
        httpx.AsyncClient, "post",
        _mock_post(200, json_body={"messages": [{"id": "wamid.abc"}]}),
    )
    gateway = _gateway()
    # Must not raise.
    asyncio.run(gateway._post_messages({"messaging_product": "whatsapp"}))


def test_send_text_propagates_send_error_on_rejected_message(monkeypatch):
    """A caller awaiting send_text must actually learn a send failed —
    previously this returned normally no matter what Meta responded."""
    monkeypatch.setattr(
        httpx.AsyncClient, "post",
        _mock_post(403, json_body={"error": {"message": "Recipient blocked"}}),
    )
    gateway = _gateway()
    with pytest.raises(WhatsAppSendError):
        asyncio.run(gateway.send_text("972500009999", "שלום"))


def test_send_confirm_prompt_propagates_send_error_on_unapproved_template(monkeypatch):
    monkeypatch.setattr(
        httpx.AsyncClient, "post",
        _mock_post(400, json_body={"error": {"message": "Template not approved"}}),
    )
    gateway = _gateway()
    with pytest.raises(WhatsAppSendError):
        asyncio.run(gateway.send_confirm_prompt("972500009999", "טקסט", 1))
