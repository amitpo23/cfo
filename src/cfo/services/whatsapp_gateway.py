"""Outbound WhatsApp adapter (Meta Cloud API) implementing the shared
``ChannelGateway`` protocol (package F, plan 2026-07-27b).

Lives in its own module rather than being added alongside ``TelegramGateway``
inside channel_gateway.py, because WhatsApp's HTTP surface is materially
wider than Telegram's flat sendMessage-for-everything API: outbound text and
confirm-prompts hit one endpoint shape, template messages (for proactive
alerts outside the 24h customer-service window — Telegram has no analogue)
hit another, and inbound media is a two-step resolve-then-fetch dance
instead of Telegram's single getFile call. Keeping that surface here keeps
channel_gateway.py — the thin, provider-agnostic Protocol + TelegramGateway
module — from growing a second, unrelated HTTP client shape.
``WhatsAppGateway`` still structurally satisfies ``ChannelGateway`` (same
``send_text``/``send_confirm_prompt`` signatures); it just doesn't need to
import the Protocol itself to do so.
"""
from __future__ import annotations

from typing import Optional

import httpx

from ..config import settings
from .channel_gateway import _split_message

WHATSAPP_MAX_MESSAGE_LENGTH = 4096
# Meta hard limits on interactive reply-button payloads.
WHATSAPP_BUTTON_TITLE_MAX = 20
WHATSAPP_BODY_MAX = 1024
# Same rationale/limit as telegram_files.TELEGRAM_FILE_MAX_BYTES — a
# receipt photo/PDF has no business being anywhere near this size; this is
# a guard against an unbounded download, not a real expected ceiling.
WHATSAPP_MEDIA_MAX_BYTES = 20 * 1024 * 1024  # 20MB
_TIMEOUT = httpx.Timeout(20.0)

_GRAPH_BASE = "https://graph.facebook.com"


class WhatsAppNotConfiguredError(RuntimeError):
    """Raised by any send/download method when phone_number_id or
    access_token is unset. Never send (or attempt to send) with a partial
    configuration — an honest failure here, not a silent no-op."""


class WhatsAppMediaError(Exception):
    """Raised when resolving or downloading inbound media fails (missing
    url, oversized file, or an HTTP error at either step)."""


class WhatsAppSendError(Exception):
    """Raised when Meta's Graph API rejects an outbound send (expired
    token, blocked/opted-out recipient, unapproved template, or any other
    4xx/5xx). Before this existed, `_post_messages` awaited the POST and
    threw the response away unread — every rejected send looked exactly
    like success to send_text/send_confirm_prompt/send_template and to
    every caller above them (channel_notifier counted it as `sent`, the
    webhook reply path reported nothing was wrong). Callers that must stay
    best-effort (webhook per-message handling, channel_notifier's
    per-recipient loop) already catch broadly around these sends — this
    exception makes the failure visible to them instead of invisible."""


def _truncate(text: str, limit: int) -> str:
    """Cut text down to `limit` characters, safely — used for the button
    title (20 chars) and confirm-prompt body (1024 chars) hard caps Meta
    enforces; anything over the limit is rejected outright by the API."""
    if text is None:
        return ""
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


class WhatsAppGateway:
    """Sends outbound messages via the Meta Cloud API
    (https://graph.facebook.com/{version}/{phone_number_id}/messages). Token
    and phone_number_id come from settings unless explicitly overridden
    (tests pass dummy values and monkeypatch the HTTP-calling methods
    directly, so no live network call ever happens under pytest)."""

    def __init__(
        self,
        phone_number_id: Optional[str] = None,
        access_token: Optional[str] = None,
        api_version: Optional[str] = None,
    ):
        self.phone_number_id = (
            phone_number_id if phone_number_id is not None else settings.whatsapp_phone_number_id
        )
        self.access_token = (
            access_token if access_token is not None else settings.whatsapp_access_token
        )
        self.api_version = (
            api_version if api_version is not None else settings.whatsapp_api_version
        )

    def _require_configured(self) -> None:
        if not self.phone_number_id or not self.access_token:
            raise WhatsAppNotConfiguredError(
                "ערוץ WhatsApp לא מוגדר (חסר phone_number_id ו/או access_token)"
            )

    def _messages_url(self) -> str:
        return f"{_GRAPH_BASE}/{self.api_version}/{self.phone_number_id}/messages"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def _post_messages(self, payload: dict) -> None:
        self._require_configured()
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                self._messages_url(), json=payload, headers=self._headers(),
            )
        if response.status_code >= 400:
            # Explicit status+body check (not a bare raise_for_status()) so
            # the exception carries Meta's own error detail — the whole
            # reason this existed to catch is a 4xx that quietly meant
            # "unapproved template" or "recipient blocked", not just "some
            # request failed".
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            raise WhatsAppSendError(
                f"שליחת הודעת WhatsApp נכשלה (סטטוס {response.status_code}): {detail}"
            )

    async def send_text(self, chat_id: str, text: str) -> None:
        for chunk in _split_message(text, WHATSAPP_MAX_MESSAGE_LENGTH):
            await self._post_messages({
                "messaging_product": "whatsapp",
                "to": chat_id,
                "type": "text",
                "text": {"body": chunk},
            })

    async def send_confirm_prompt(self, chat_id: str, text: str, message_id: int) -> None:
        """Interactive reply-button prompt with exactly two buttons —
        callback ids carry ONLY the message_id, mirroring
        TelegramGateway.send_confirm_prompt: the real tool name/input is
        re-read server-side from ChatMessage.pending_action on confirm,
        never trusted from the tapped button's payload."""
        payload = {
            "messaging_product": "whatsapp",
            "to": chat_id,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": _truncate(text, WHATSAPP_BODY_MAX)},
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": f"confirm:{message_id}",
                                "title": _truncate("אשר", WHATSAPP_BUTTON_TITLE_MAX),
                            },
                        },
                        {
                            "type": "reply",
                            "reply": {
                                "id": f"cancel:{message_id}",
                                "title": _truncate("בטל", WHATSAPP_BUTTON_TITLE_MAX),
                            },
                        },
                    ]
                },
            },
        }
        await self._post_messages(payload)

    async def send_template(
        self, chat_id: str, template_name: str, language_code: str, variables: list[str],
    ) -> None:
        """Approved-template send for proactive alerts outside the 24h
        customer-service window — free-form text (send_text) is rejected by
        Meta once that window has closed."""
        components = []
        if variables:
            components.append({
                "type": "body",
                "parameters": [{"type": "text", "text": str(v)} for v in variables],
            })
        payload = {
            "messaging_product": "whatsapp",
            "to": chat_id,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": components,
            },
        }
        await self._post_messages(payload)

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Two-step Meta Media API resolve-then-fetch: GET /{media_id} for a
        short-lived {url, mime_type, file_size}, then GET that url (still
        Bearer-authenticated). Returns (content_bytes, mime_type)."""
        self._require_configured()
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                resolve_resp = await client.get(
                    f"{_GRAPH_BASE}/{self.api_version}/{media_id}", headers=self._headers(),
                )
                resolve_resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise WhatsAppMediaError(f"פתרון קובץ המדיה נכשל: {exc}") from exc

            data = resolve_resp.json()
            url = data.get("url")
            mime_type = str(data.get("mime_type") or "application/octet-stream")
            if not url:
                raise WhatsAppMediaError("Meta לא החזירה כתובת הורדה למדיה")

            file_size = data.get("file_size")
            if file_size is not None and file_size > WHATSAPP_MEDIA_MAX_BYTES:
                raise WhatsAppMediaError(
                    f"הקובץ גדול מדי ({file_size} בייטים) — המגבלה {WHATSAPP_MEDIA_MAX_BYTES} בייטים"
                )

            try:
                download_resp = await client.get(url, headers=self._headers())
                download_resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise WhatsAppMediaError(f"הורדת קובץ המדיה נכשלה: {exc}") from exc

            content = download_resp.content
            if len(content) > WHATSAPP_MEDIA_MAX_BYTES:
                raise WhatsAppMediaError(
                    f"הקובץ שהתקבל גדול מדי ({len(content)} בייטים) — "
                    f"המגבלה {WHATSAPP_MEDIA_MAX_BYTES} בייטים"
                )
            return content, mime_type
