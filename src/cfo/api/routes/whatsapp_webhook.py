"""WhatsApp webhook receiver, Meta Cloud API (package F, plan 2026-07-27b).

Mirrors telegram_webhook.py's structure and safety invariants — see that
file's module docstring for the full reasoning — but with two differences
forced by Meta's protocol instead of Telegram's:

- **GET /api/whatsapp/webhook** is Meta's one-time subscription handshake:
  it echoes back ``hub.challenge`` as *raw text* (not JSON) when
  ``hub.mode=subscribe`` and ``hub.verify_token`` matches
  ``settings.whatsapp_verify_token``.
- **POST /api/whatsapp/webhook** is authenticated per-request via
  ``X-Hub-Signature-256``, an HMAC-SHA256 of the raw request body keyed by
  ``settings.whatsapp_app_secret`` — not a static shared-secret header like
  Telegram's. The signature MUST be computed over the exact raw bytes
  (``await request.body()``) before any JSON parsing, or a byte-identical
  payload re-serialized by FastAPI would produce a different signature.

Every inbound message's ``id`` (wamid) is deduped and the dedupe row
COMMITTED before any LLM or outbound-gateway work runs — identical
reasoning to telegram_webhook._mark_processed: Meta retries aggressively
when it doesn't get a fast 200, and without committing the dedupe record
independently of the rest of the request, a retry would silently double the
Anthropic API cost.

No LLM call and no media download ever happens for an unverified channel
identity — verification happens strictly before any tool/LLM/download
access, same iron rule as the Telegram path.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...config import settings
from ...database import get_db_session
from ...models import ChannelIdentity, ChannelProcessedUpdate
from ...services.ai_chat_personas import PERSONAS, resolve_persona
from ...services.ai_chat_service import AIChatService, ChatConfirmationError
from ...services.whatsapp_gateway import (
    WhatsAppGateway,
    WhatsAppMediaError,
    WhatsAppNotConfiguredError,
)
from ...services.channel_link_service import (
    ChannelLinkError,
    complete_email_verification,
    resolve_identity,
    start_email_verification,
)

logger = logging.getLogger(__name__)
router = APIRouter()

SIGNATURE_HEADER = "X-Hub-Signature-256"

# Persona-switch commands. Duplicated (not imported) from telegram_webhook's
# PERSONA_COMMANDS deliberately — that module belongs to a different
# in-flight package on this branch and this file is built to stand alone
# alongside it, never depending on its internals.
PERSONA_COMMANDS = {
    "/cfo": "cfo", "/כספים": "cfo",
    "/bookkeeper": "bookkeeper", "/הנהח": "bookkeeper",
    "/accountant": "accountant", "/רוח": "accountant",
}

_UNLINKED_INSTRUCTIONS = (
    "המספר הזה עדיין לא מקושר לרצף. שלח לכאן את כתובת המייל שרשומה שלך "
    "ברצף — נשלח אליה קוד בן 6 ספרות, ואז שלח את הקוד לכאן."
)

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SIX_DIGIT_CODE_PATTERN = re.compile(r"^\d{6}$")


def _looks_like_email(text: str) -> bool:
    return bool(_EMAIL_PATTERN.match(text))


def _looks_like_six_digit_code(text: str) -> bool:
    return bool(_SIX_DIGIT_CODE_PATTERN.match(text))


def _gateway() -> WhatsAppGateway:
    """Factory indirection so tests can monkeypatch a fake gateway (or the
    WhatsAppGateway methods directly) without ever making a live call to
    graph.facebook.com."""
    return WhatsAppGateway()


def _persona_names() -> str:
    return ", ".join(f"{p.title_he} (/{key})" for key, p in PERSONAS.items())


async def _send_welcome(gateway: WhatsAppGateway, external_id: str, identity: ChannelIdentity) -> None:
    welcome_persona = resolve_persona(identity.default_persona).title_he
    await gateway.send_text(
        external_id,
        "הקישור הצליח! ברוך הבא לרצף.\n"
        f"פרסונות זמינות: {_persona_names()}\n"
        f"ברירת המחדל שלך כעת: {welcome_persona}.",
    )


def _mark_processed(db: Session, wamid: str) -> bool:
    """Insert-or-conflict dedupe on (provider="whatsapp", update_id=wamid).
    Commits immediately, independent of anything that happens afterward in
    this request — same contract as telegram_webhook._mark_processed.
    Returns True for a genuinely new message id."""
    try:
        db.add(ChannelProcessedUpdate(provider="whatsapp", update_id=wamid))
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def _render_pending_action(reply: str, pending: dict) -> str:
    """Spell out WHAT is about to be executed, next to the confirm button —
    copied from telegram_webhook._render_pending_action (not imported: that
    module belongs to a different in-flight package on this branch). See
    its docstring there for the full rationale: a bare "אשר ✅" tap must
    never approve arguments the user never actually read."""
    lines = [reply, "", f"פעולה: {pending.get('description', pending.get('tool', ''))}"]
    for key, value in (pending.get("input") or {}).items():
        lines.append(f"• {key}: {value}")
    return "\n".join(lines)


def _parse_message_id(button_id: str) -> int | None:
    try:
        return int(button_id.split(":", 1)[1])
    except (IndexError, ValueError):
        return None


def _extract_receipt_media(message: dict) -> tuple[str, str] | None:
    """Returns (media_id, mime_type) for an image or image/PDF document
    attachment, or None for any other message type (text, interactive,
    audio, location, ...)."""
    msg_type = message.get("type")
    if msg_type == "image":
        image = message.get("image") or {}
        media_id = image.get("id")
        if media_id:
            return media_id, str(image.get("mime_type") or "image/jpeg")
        return None
    if msg_type == "document":
        document = message.get("document") or {}
        mime = str(document.get("mime_type") or "")
        media_id = document.get("id")
        if media_id and (mime.startswith("image/") or mime == "application/pdf"):
            return media_id, mime
        return None
    return None


def _extract_messages(payload: dict) -> list[dict]:
    """Walk entry[].changes[].value.{messages,contacts}[] and return the
    flat list of inbound messages, each annotated with the sender's profile
    name (if Meta included one in value.contacts) under "_profile_name".
    Anything under value other than "messages" — most notably "statuses"
    (delivery/read receipts) — is silently ignored here, never surfaced."""
    messages: list[dict] = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            contacts = value.get("contacts") or []
            name_by_wa_id = {
                c.get("wa_id"): (c.get("profile") or {}).get("name")
                for c in contacts if isinstance(c, dict) and c.get("wa_id")
            }
            for message in value.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                profile_name = name_by_wa_id.get(message.get("from"))
                if profile_name:
                    message = {**message, "_profile_name": profile_name}
                messages.append(message)
    return messages


def _expected_signature(raw_body: bytes) -> str:
    digest = hmac.new(
        settings.whatsapp_app_secret.encode("utf-8"), raw_body, hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


@router.get("/webhook")
async def whatsapp_verify(request: Request):
    if not settings.whatsapp_verify_token:
        raise HTTPException(503, "ערוץ WhatsApp לא מוגדר")

    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token") or ""
    challenge = request.query_params.get("hub.challenge") or ""

    if mode == "subscribe" and hmac.compare_digest(token, settings.whatsapp_verify_token):
        return PlainTextResponse(challenge)
    raise HTTPException(403, "אימות ערוץ נכשל")


@router.post("/webhook")
async def whatsapp_webhook(
    request: Request,
    db: Session = Depends(get_db_session),
):
    if not settings.whatsapp_app_secret:
        raise HTTPException(503, "ערוץ WhatsApp לא מוגדר")

    raw_body = await request.body()
    header_signature = request.headers.get(SIGNATURE_HEADER) or ""
    if not hmac.compare_digest(header_signature, _expected_signature(raw_body)):
        raise HTTPException(403, "אימות ערוץ נכשל")

    try:
        payload = json.loads(raw_body or b"{}")
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "invalid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(400, "invalid JSON")

    for message in _extract_messages(payload):
        wamid = str(message.get("id") or "").strip()
        if not wamid or not _mark_processed(db, wamid):
            # Missing id (malformed) or already-processed: skip silently,
            # idempotently — same behavior as an already-seen Telegram
            # update_id.
            continue

        try:
            if message.get("type") == "interactive":
                await _handle_interactive(db, message)
            else:
                await _handle_message(db, message)
        except Exception:  # noqa: BLE001
            logger.exception("whatsapp webhook processing failed for wamid=%s", wamid)
            db.rollback()
            try:
                external_id = str(message.get("from") or "").strip()
                if external_id:
                    await _gateway().send_text(external_id, "אירעה שגיאה, נסה שוב.")
            except Exception:  # noqa: BLE001
                logger.exception("whatsapp webhook: failed to notify user of internal error")

    return {"ok": True}


async def _handle_message(db: Session, message: dict) -> None:
    external_id = str(message.get("from") or "").strip()
    if not external_id:
        return

    msg_type = message.get("type")
    text = ""
    if msg_type == "text":
        text = ((message.get("text") or {}).get("body") or "").strip()
    receipt_media = _extract_receipt_media(message)

    gateway = _gateway()
    identity = resolve_identity(db, "whatsapp", external_id)

    # Every verified inbound message opens/refreshes Meta's 24-hour service
    # window, including types Rezef does not process (audio/location). Record
    # that fact before the content-routing early return.
    if identity is not None:
        identity.last_inbound_at = datetime.now(timezone.utc)
        db.commit()

    if not text and receipt_media is None:
        return  # unsupported content is ignored after refreshing the window

    if identity is None:
        if _looks_like_email(text):
            # Same enumeration-safe response as the Telegram path — the
            # reply is identical whether or not this email is registered.
            result = await start_email_verification(
                db, provider="whatsapp", external_id=external_id, email=text,
            )
            await gateway.send_text(external_id, result["message"])
            return
        if _looks_like_six_digit_code(text):
            try:
                new_identity = complete_email_verification(
                    db, provider="whatsapp", external_id=external_id, code=text,
                )
            except ChannelLinkError as exc:
                await gateway.send_text(external_id, str(exc))
                return
            new_identity.display_name = message.get("_profile_name")
            new_identity.last_inbound_at = datetime.now(timezone.utc)
            db.commit()
            await _send_welcome(gateway, external_id, new_identity)
            return
        # Not a verified identity and not a recognized verification step —
        # never reaches the LLM, and a receipt image/document from here is
        # never downloaded either: verification happens strictly before any
        # tool/LLM/download access.
        await gateway.send_text(external_id, _UNLINKED_INSTRUCTIONS)
        return

    if receipt_media is not None:
        await _handle_receipt_message(db, gateway, identity, external_id, receipt_media)
        return

    persona_key = PERSONA_COMMANDS.get(text)
    if persona_key is not None:
        identity.default_persona = persona_key
        db.commit()
        await gateway.send_text(
            external_id, f"הפרסונה עודכנה ל{PERSONAS[persona_key].title_he}.",
        )
        return

    service = AIChatService(
        db, identity.organization_id, identity.user_id,
        # Same deliberate hardcode as telegram_webhook — office-tool
        # visibility must never depend on which channel a message arrived
        # through. A super_admin who wants office tools uses the
        # authenticated web app.
        is_super_admin=False,
    )
    result = await service.send_message(
        session_id=f"wa-{external_id}", text=text, persona=identity.default_persona,
    )
    pending = result.get("pending_action")
    if pending:
        await gateway.send_confirm_prompt(
            external_id,
            _render_pending_action(result["reply"], pending),
            result["message_id"],
        )
    else:
        await gateway.send_text(external_id, result["reply"])


_INTAKE_STATUS_FALLBACK_MESSAGE = {
    "disabled": "קליטת קבלות דרך הצ'אט כבויה כרגע.",
    "limit_reached": "הגעת למכסה היומית של קליטת קבלות בצ'אט — נסה שוב מחר.",
    "error": "לא הצלחתי לעבד את הקבלה.",
    "unreadable": "לא הצלחתי לקרוא את הקבלה בביטחון מספיק.",
    "duplicate": "נראה שהקבלה הזו כבר קיימת במערכת — לא נוצרה הוצאה כפולה.",
}


async def _handle_receipt_message(
    db: Session, gateway: WhatsAppGateway, identity: ChannelIdentity, external_id: str,
    receipt_media: tuple[str, str],
) -> None:
    """Image/document attachment from a VERIFIED identity only (the caller
    already gated on identity is not None) — never downloaded or sent for
    LLM extraction for an unlinked number. Filing to SUMIT remains a
    separate write tool reached through the normal chat/confirm flow, never
    triggered automatically here."""
    from ...services.chat_expense_intake import intake_receipt_bytes
    import inspect

    media_id, message_mime_type = receipt_media
    try:
        content, downloaded_mime_type = await gateway.download_media(media_id)
    except (WhatsAppMediaError, WhatsAppNotConfiguredError) as exc:
        await gateway.send_text(external_id, f"לא הצלחתי להוריד את הקובץ: {exc}")
        return

    # message_mime_type comes from the inbound message envelope and was
    # already validated by _extract_receipt_media to be image/* or
    # application/pdf — vision_extractor.extract_receipt branches on this
    # exact value (PDF vs image path), so it must win. downloaded_mime_type
    # (Meta's own /media resolve response) is only a fallback for the
    # defensive case where the envelope somehow carried no mime_type at
    # all — WhatsAppGateway.download_media never returns a falsy one
    # itself (it defaults to "application/octet-stream"), so this branch
    # is effectively unreachable in practice, not the common path.
    kwargs = {
        "media_type": message_mime_type or downloaded_mime_type,
        "source": "whatsapp",
        "uploaded_by_user_id": identity.user_id,
    }
    parameters = inspect.signature(intake_receipt_bytes).parameters.values()
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters) or (
        "session_id" in inspect.signature(intake_receipt_bytes).parameters
    ):
        kwargs["session_id"] = f"wa-{external_id}"
    result = await intake_receipt_bytes(db, identity.organization_id, content, **kwargs)

    status = result.get("status")
    text = result.get("message") or _INTAKE_STATUS_FALLBACK_MESSAGE.get(
        status, "לא הצלחתי לעבד את הקבלה."
    )
    if status == "created":
        text += f"\n\nלתייק לספרים? כתוב 'תייק' (מזהה הוצאה: {result.get('expense_id')})."
    await gateway.send_text(external_id, text)


async def _handle_interactive(db: Session, message: dict) -> None:
    external_id = str(message.get("from") or "").strip()
    if not external_id:
        return

    gateway = _gateway()
    identity = resolve_identity(db, "whatsapp", external_id)
    if identity is None:
        # An interactive tap from an unlinked number can't legitimately
        # happen (we never send buttons to an unverified identity), but
        # answer with the same static instructions rather than silently
        # dropping it, in case of a stale/replayed button.
        await gateway.send_text(external_id, _UNLINKED_INSTRUCTIONS)
        return

    identity.last_inbound_at = datetime.now(timezone.utc)
    db.commit()

    interactive = message.get("interactive") or {}
    button_reply = interactive.get("button_reply") or {}
    button_id = str(button_reply.get("id") or "")

    if button_id.startswith("confirm:"):
        message_id = _parse_message_id(button_id)
        if message_id is not None:
            service = AIChatService(
                db, identity.organization_id, identity.user_id, is_super_admin=False,
            )
            try:
                await service.confirm_action(message_id)
                await gateway.send_text(external_id, "בוצע.")
            except ChatConfirmationError as exc:
                await gateway.send_text(external_id, str(exc))
    elif button_id.startswith("cancel:"):
        # No cancellation mechanism exists on ChatMessage/pending_action
        # (same as telegram_webhook) — acknowledge without executing
        # anything, rather than inventing new DB state.
        await gateway.send_text(external_id, "בוטל.")
