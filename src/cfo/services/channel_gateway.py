"""Outbound conversational-channel gateway abstraction (decision 7, plan
2026-07-26).

``ChannelGateway`` is the minimal interface any channel adapter implements
(send_text, send_confirm_prompt) so callers (telegram_webhook.py today, a
future whatsapp_webhook.py tomorrow) never branch on provider. TelegramGateway
is the first concrete implementation, talking to the Telegram Bot HTTP API
directly over httpx — no SDK dependency.
"""
from __future__ import annotations

from typing import Optional, Protocol

import httpx

from ..config import settings

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
# Bot API limits for sendDocument: 50MB upload, 1024-char caption.
TELEGRAM_DOCUMENT_MAX_BYTES = 50 * 1024 * 1024
TELEGRAM_CAPTION_MAX = 1024


class TelegramSendError(Exception):
    """Raised by send_document when Telegram rejects the upload or cannot be
    reached. The message never carries the request URL: the bot token is
    part of every Bot API URL."""


class ChannelGateway(Protocol):
    """Interface a channel adapter must implement. WhatsApp (or any future
    channel) plugs in here without telegram_webhook.py-style callers needing
    to change."""

    async def send_text(self, chat_id: str, text: str) -> None: ...

    async def send_confirm_prompt(self, chat_id: str, text: str, message_id: int) -> None: ...


def _split_message(text: str, limit: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> list[str]:
    """Telegram rejects any sendMessage over 4096 characters outright — split
    long assistant replies into consecutive messages instead of truncating
    or erroring."""
    if not text:
        return [text]
    return [text[i:i + limit] for i in range(0, len(text), limit)]


class TelegramGateway:
    """Sends outbound messages via the Telegram Bot HTTP API
    (https://api.telegram.org/bot<token>/...). The token comes from
    settings.telegram_bot_token unless explicitly overridden (tests pass a
    dummy token and monkeypatch the HTTP-calling methods directly, so no
    live network call ever happens under pytest)."""

    def __init__(self, token: Optional[str] = None):
        self.token = token if token is not None else settings.telegram_bot_token

    def _base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"

    async def _post(self, method: str, payload: dict) -> None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(f"{self._base_url()}/{method}", json=payload)

    async def send_text(self, chat_id: str, text: str) -> None:
        for chunk in _split_message(text):
            await self._post("sendMessage", {"chat_id": chat_id, "text": chunk})

    async def send_confirm_prompt(self, chat_id: str, text: str, message_id: int) -> None:
        """Send text with an inline confirm/cancel keyboard whose
        callback_data carries ONLY the message_id — the actual tool name and
        input are re-read from ChatMessage.pending_action server-side on
        confirm, never trusted from the callback payload itself."""
        keyboard = {
            "inline_keyboard": [[
                {"text": "אשר ✅", "callback_data": f"confirm:{message_id}"},
                {"text": "בטל ❌", "callback_data": f"cancel:{message_id}"},
            ]]
        }
        await self._post(
            "sendMessage",
            {"chat_id": chat_id, "text": text, "reply_markup": keyboard},
        )

    async def send_feedback_prompt(self, chat_id: str, text: str, message_id: int) -> None:
        """Send an assistant reply with an inline 👍/👎/❓ keyboard (W1.2).

        callback_data carries ONLY the category and the ChatMessage id
        (``fb:<category>:<message_id>``) — the actual message row is
        re-read server-side on tap, same discipline as send_confirm_prompt.
        Not part of the shared ChannelGateway interface (Telegram-specific),
        same as answer_callback_query below."""
        keyboard = {
            "inline_keyboard": [[
                {"text": "👍", "callback_data": f"fb:helpful:{message_id}"},
                {"text": "👎", "callback_data": f"fb:inaccurate:{message_id}"},
                {"text": "❓", "callback_data": f"fb:unknown:{message_id}"},
            ]]
        }
        chunks = _split_message(text)
        for chunk in chunks[:-1]:
            await self._post("sendMessage", {"chat_id": chat_id, "text": chunk})
        await self._post(
            "sendMessage",
            {"chat_id": chat_id, "text": chunks[-1], "reply_markup": keyboard},
        )

    async def send_document(
        self, chat_id: str, content: bytes, *, filename: str,
        caption: Optional[str] = None, mime_type: str = "application/pdf",
    ) -> None:
        """Send a file to ``chat_id`` with sendDocument (multipart upload).

        Unlike ``_post`` (fire-and-forget text), this checks the reply: only
        HTTP 2xx with ``ok: true`` counts as delivered."""
        from .whatsapp_gateway import ascii_upload_filename

        if not self.token:
            raise TelegramSendError("טוקן טלגרם לא מוגדר — הקובץ לא נשלח")
        if not content:
            raise TelegramSendError("אין תוכן לקובץ — לא נשלח דבר")
        if len(content) > TELEGRAM_DOCUMENT_MAX_BYTES:
            raise TelegramSendError(
                f"הקובץ גדול מדי ({len(content)} בייטים) — המגבלה {TELEGRAM_DOCUMENT_MAX_BYTES} בייטים"
            )
        data = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = (
                caption if len(caption) <= TELEGRAM_CAPTION_MAX
                else caption[: TELEGRAM_CAPTION_MAX - 1] + "…"
            )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self._base_url()}/sendDocument",
                    data=data,
                    files={"document": (ascii_upload_filename(filename), content, mime_type)},
                )
        except httpx.HTTPError as exc:
            # `from None`: the httpx error text and its traceback carry the
            # URL, which contains the bot token.
            raise TelegramSendError(
                f"שליחת הקובץ לטלגרם נכשלה ({type(exc).__name__})"
            ) from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not (200 <= response.status_code < 300) or not (isinstance(body, dict) and body.get("ok")):
            description = body.get("description") if isinstance(body, dict) else None
            raise TelegramSendError(
                f"שליחת הקובץ לטלגרם נכשלה (סטטוס {response.status_code}): "
                f"{description or 'שגיאה לא ידועה'}"
            )

    async def answer_callback_query(
        self, callback_query_id: str, text: Optional[str] = None,
    ) -> None:
        """Close the Telegram client's loading spinner on the tapped button.
        Not part of the shared ChannelGateway interface — Telegram-specific,
        called directly by telegram_webhook.py."""
        payload: dict = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        await self._post("answerCallbackQuery", payload)
