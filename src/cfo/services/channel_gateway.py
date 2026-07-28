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
