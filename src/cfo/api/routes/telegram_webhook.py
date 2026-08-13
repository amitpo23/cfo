"""Telegram webhook receiver (decision 7, plan 2026-07-26).

POST /api/telegram/webhook carries no user JWT — it is authenticated solely
by the ``X-Telegram-Bot-Api-Secret-Token`` header, compared to
``settings.telegram_webhook_secret`` with ``secrets.compare_digest``. An
unconfigured secret is an honest 503 ("channel not configured"), never an
open endpoint — unlike sumit_webhooks.py's shared-secret check, where an
unset secret means "no check", here it means "channel doesn't exist yet".

Every update_id is deduped and the dedupe row COMMITTED before any LLM or
outbound-gateway work runs (see _mark_processed): Telegram retries an
update it didn't get a fast 200 for, and without committing the dedupe
record first (independent of whatever the rest of this request does), a
retry would silently double the Anthropic API cost — the exact risk
decision 7 exists to close off.

No LLM call ever happens for an unverified channel identity (steps 4-5 of
the plan): an unlinked chat gets a static "how to link" reply, never a
model turn — verification happens strictly before any tool/LLM access.
"""
from __future__ import annotations

import logging
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...config import settings
from ...database import get_db_session
from ...models import ChannelIdentity, ChannelProcessedUpdate
from ...services.ai_chat_personas import PERSONAS, resolve_persona
from ...services.ai_chat_service import AIChatService, ChatConfirmationError
from ...services.channel_gateway import TelegramGateway
from ...services.channel_link_service import (
    ChannelLinkError,
    complete_email_verification,
    redeem_link_code,
    resolve_identity,
    start_email_verification,
)

logger = logging.getLogger(__name__)
router = APIRouter()

TELEGRAM_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"

# Persona-switch commands. Hebrew aliases alongside the English/persona-key
# form so a user can type whichever comes to hand in a Telegram chat.
PERSONA_COMMANDS = {
    "/cfo": "cfo", "/כספים": "cfo",
    "/bookkeeper": "bookkeeper", "/הנהח": "bookkeeper",
    "/accountant": "accountant", "/רוח": "accountant",
}

_UNLINKED_INSTRUCTIONS = (
    "החשבון הזה עדיין לא מקושר לרצף. שתי דרכים לקשר:\n"
    "1) קוד מהאפליקציה: היכנס לאפליקציית רצף, הנפק קוד קישור "
    "(בהגדרות → ערוצים), ושלח לכאן /start <קוד> תוך 15 דקות.\n"
    "2) מייל רשום: שלח לכאן את כתובת המייל שרשומה שלך ברצף — נשלח אליה "
    "קוד בן 6 ספרות, ואז שלח את הקוד לכאן."
)

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SIX_DIGIT_CODE_PATTERN = re.compile(r"^\d{6}$")


def _looks_like_email(text: str) -> bool:
    return bool(_EMAIL_PATTERN.match(text))


def _looks_like_six_digit_code(text: str) -> bool:
    return bool(_SIX_DIGIT_CODE_PATTERN.match(text))


def _gateway() -> TelegramGateway:
    """Factory indirection so tests can monkeypatch a fake gateway (or the
    TelegramGateway methods directly) without ever making a live call to
    api.telegram.org."""
    return TelegramGateway()


def _persona_names() -> str:
    return ", ".join(f"{p.title_he} (/{key})" for key, p in PERSONAS.items())


async def _send_welcome(gateway: TelegramGateway, external_id: str, identity: ChannelIdentity) -> None:
    welcome_persona = resolve_persona(identity.default_persona).title_he
    await gateway.send_text(
        external_id,
        "הקישור הצליח! ברוך הבא לרצף.\n"
        f"פרסונות זמינות: {_persona_names()}\n"
        f"ברירת המחדל שלך כעת: {welcome_persona}.",
    )


def _mark_processed(db: Session, update_id: str) -> bool:
    """Insert-or-conflict dedupe on (provider="telegram", update_id).
    Commits immediately, independent of anything that happens afterward in
    this request — so a later rollback (e.g. from the top-level error
    handler below) can never undo this record and let a Telegram retry
    re-run the LLM turn. Returns True for a genuinely new update."""
    try:
        db.add(ChannelProcessedUpdate(provider="telegram", update_id=update_id))
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def _extract_chat_id(update: dict) -> str | None:
    message = update.get("message")
    if isinstance(message, dict):
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        return str(chat_id) if chat_id is not None else None
    callback_query = update.get("callback_query")
    if isinstance(callback_query, dict):
        chat = (callback_query.get("message") or {}).get("chat") or {}
        chat_id = chat.get("id")
        return str(chat_id) if chat_id is not None else None
    return None


def _render_pending_action(reply: str, pending: dict) -> str:
    """Spell out WHAT is about to be executed, next to the confirm button.

    The web UI renders `pending_action.input` as JSON under the confirm
    button (ChatAssistant.tsx), so a user there always sees the concrete
    arguments — who the email goes to, which expense gets filed — before
    approving. Telegram only ever showed the model's free-text reply, which
    is not guaranteed to name them: a tap on "אשר ✅" could therefore send a
    financial report to an address the user never actually read. Rendering
    the inputs here closes that gap, so both channels disclose the same
    thing before an irreversible-ish write runs.
    """
    lines = [reply, "", f"פעולה: {pending.get('description', pending.get('tool', ''))}"]
    for key, value in (pending.get("input") or {}).items():
        lines.append(f"• {key}: {value}")
    return "\n".join(lines)


def _parse_message_id(callback_data: str) -> int | None:
    try:
        return int(callback_data.split(":", 1)[1])
    except (IndexError, ValueError):
        return None


def _largest_photo_file_id(photos: list) -> str | None:
    """Telegram sends one entry per resolution, usually ascending — pick the
    largest explicitly by file_size rather than trusting order, falling
    back to the last entry when file_size is missing."""
    sized = [p for p in photos if isinstance(p, dict) and p.get("file_id")]
    if not sized:
        return None
    with_size = [p for p in sized if p.get("file_size") is not None]
    if with_size:
        return max(with_size, key=lambda p: p["file_size"])["file_id"]
    return sized[-1]["file_id"]


def _extract_receipt_file(message: dict) -> tuple[str, str] | None:
    """Returns (file_id, media_type) for a photo or image/PDF document
    attached to the message, or None if this message carries no such
    attachment (text-only, sticker, voice, ...)."""
    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        file_id = _largest_photo_file_id(photos)
        if file_id:
            return file_id, "image/jpeg"
    document = message.get("document")
    if isinstance(document, dict):
        mime = str(document.get("mime_type") or "")
        if mime.startswith("image/") or mime == "application/pdf":
            file_id = document.get("file_id")
            if file_id:
                return file_id, mime
    return None


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    db: Session = Depends(get_db_session),
):
    if not settings.telegram_webhook_secret:
        raise HTTPException(503, "ערוץ טלגרם לא מוגדר")

    header_secret = request.headers.get(TELEGRAM_SECRET_HEADER) or ""
    if not secrets.compare_digest(header_secret, settings.telegram_webhook_secret):
        raise HTTPException(403, "אימות ערוץ נכשל")

    try:
        update = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "invalid JSON")

    if not isinstance(update, dict):
        raise HTTPException(400, "invalid JSON")

    update_id = str(update.get("update_id", "")).strip()
    if not update_id or not _mark_processed(db, update_id):
        # Missing update_id (malformed) or already-processed: acknowledge
        # without doing any further work, idempotently.
        return {"ok": True}

    try:
        if isinstance(update.get("message"), dict):
            await _handle_message(db, update["message"])
        elif isinstance(update.get("callback_query"), dict):
            await _handle_callback(db, update["callback_query"])
        # Anything else (edited_message, group/channel posts, stickers with
        # no text, ...) is silently ignored — 200, no side effect.
    except Exception:  # noqa: BLE001
        logger.exception("telegram webhook processing failed for update_id=%s", update_id)
        db.rollback()
        try:
            chat_id = _extract_chat_id(update)
            if chat_id:
                await _gateway().send_text(chat_id, "אירעה שגיאה, נסה שוב.")
        except Exception:  # noqa: BLE001
            logger.exception("telegram webhook: failed to notify user of internal error")

    return {"ok": True}


async def _handle_message(db: Session, message: dict) -> None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    # Groups/supergroups/channels are silently ignored (plan step 3) — the
    # link flow and persona/chat semantics only make sense in a 1:1 chat.
    if (chat.get("type") or "private") != "private":
        return
    external_id = str(chat_id)
    text = (message.get("text") or "").strip()
    receipt_file = _extract_receipt_file(message)
    if not text and receipt_file is None:
        return  # non-text, non-receipt message (sticker, voice, ...) — silently ignored

    gateway = _gateway()
    identity = resolve_identity(db, "telegram", external_id)

    if identity is None:
        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            code = parts[1].strip() if len(parts) > 1 else ""
            if not code:
                await gateway.send_text(external_id, _UNLINKED_INSTRUCTIONS)
                return
            try:
                new_identity = redeem_link_code(
                    db, code, provider="telegram", external_id=external_id,
                    display_name=(message.get("from") or {}).get("first_name"),
                )
            except ChannelLinkError as exc:
                await gateway.send_text(external_id, str(exc))
                return
            await _send_welcome(gateway, external_id, new_identity)
            return
        if _looks_like_email(text):
            # Package G: no LLM call, no lookup result disclosed either way
            # (see channel_link_service._ENUMERATION_SAFE_RESPONSE) — the
            # same reply goes out whether or not this email is registered.
            result = await start_email_verification(
                db, provider="telegram", external_id=external_id, email=text,
            )
            await gateway.send_text(external_id, result["message"])
            return
        if _looks_like_six_digit_code(text):
            try:
                new_identity = complete_email_verification(
                    db, provider="telegram", external_id=external_id, code=text,
                )
            except ChannelLinkError as exc:
                await gateway.send_text(external_id, str(exc))
                return
            # complete_email_verification doesn't persist display_name (no
            # schema slot spanning the two-step flow — see its docstring);
            # the webhook sets it here from Telegram's own message metadata,
            # same source redeem_link_code uses for the app-code path.
            new_identity.display_name = (message.get("from") or {}).get("first_name")
            db.commit()
            await _send_welcome(gateway, external_id, new_identity)
            return
        # Not a verified identity and not a recognized link attempt — never
        # reaches the LLM (decision 6/7), and a receipt photo/document from
        # here is never downloaded either: verification happens strictly
        # before any tool/LLM/download access. Same static reply as any
        # other unlinked message.
        await gateway.send_text(external_id, _UNLINKED_INSTRUCTIONS)
        return

    if receipt_file is not None:
        await _handle_receipt_message(db, gateway, identity, external_id, message, receipt_file)
        return

    persona_key = PERSONA_COMMANDS.get(text)
    if persona_key is not None:
        identity.default_persona = persona_key
        db.commit()
        await gateway.send_text(
            chat_id, f"הפרסונה עודכנה ל{PERSONAS[persona_key].title_he}.",
        )
        return

    service = AIChatService(
        db, identity.organization_id, identity.user_id,
        # Deliberately hardcoded False, not derived from the linked user's DB
        # role: Telegram is a weaker auth factor than a fresh JWT (a channel
        # identity persists indefinitely once linked), and persona is a
        # prompt/tone axis only per decision 1 — office-tool visibility must
        # never depend on which channel a message arrived through. A
        # super_admin who wants office tools uses the authenticated web app.
        is_super_admin=False,
        channel="telegram",
    )
    result = await service.send_message(
        session_id=f"tg-{external_id}", text=text, persona=identity.default_persona,
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
    db: Session, gateway, identity, external_id: str, message: dict,
    receipt_file: tuple[str, str],
) -> None:
    """Photo/document attachment from a VERIFIED identity only (the caller
    already gated on identity is not None) — never downloaded or sent for
    LLM extraction for an unlinked chat. Filing to SUMIT is a separate write
    tool (file_expense) reached through the normal chat/confirm flow, never
    triggered automatically here."""
    from ...services.telegram_files import TelegramFileError, download_telegram_file
    from ...services.chat_expense_intake import intake_receipt_bytes
    import inspect

    file_id, media_type = receipt_file
    try:
        content = await download_telegram_file(file_id)
    except TelegramFileError as exc:
        await gateway.send_text(external_id, f"לא הצלחתי להוריד את הקובץ: {exc}")
        return

    kwargs = {
        "media_type": media_type,
        "source": "telegram",
        "uploaded_by_user_id": identity.user_id,
    }
    parameters = inspect.signature(intake_receipt_bytes).parameters.values()
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters) or (
        "session_id" in inspect.signature(intake_receipt_bytes).parameters
    ):
        kwargs["session_id"] = f"tg-{external_id}"
    result = await intake_receipt_bytes(db, identity.organization_id, content, **kwargs)

    status = result.get("status")
    text = result.get("message") or _INTAKE_STATUS_FALLBACK_MESSAGE.get(
        status, "לא הצלחתי לעבד את הקבלה."
    )
    if status == "created":
        text += f"\n\nלתייק לספרים? כתוב 'תייק' (מזהה הוצאה: {result.get('expense_id')})."
    await gateway.send_text(external_id, text)


async def _handle_callback(db: Session, callback_query: dict) -> None:
    data = callback_query.get("data") or ""
    callback_id = callback_query.get("id")
    chat = (callback_query.get("message") or {}).get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    external_id = str(chat_id)
    gateway = _gateway()

    identity = resolve_identity(db, "telegram", external_id)
    if identity is None:
        if callback_id:
            await gateway.answer_callback_query(callback_id, "החשבון לא מקושר")
        return

    if data.startswith("confirm:"):
        message_id = _parse_message_id(data)
        if message_id is not None:
            service = AIChatService(
                db, identity.organization_id, identity.user_id,
                is_super_admin=False, channel="telegram",
            )
            try:
                await service.confirm_action(message_id)
                await gateway.send_text(external_id, "בוצע.")
            except ChatConfirmationError as exc:
                await gateway.send_text(external_id, str(exc))
        if callback_id:
            await gateway.answer_callback_query(callback_id)
    elif data.startswith("cancel:"):
        message_id = _parse_message_id(data)
        if message_id is not None:
            service = AIChatService(
                db, identity.organization_id, identity.user_id,
                is_super_admin=False, channel="telegram",
            )
            try:
                service.cancel_action(message_id)
                await gateway.send_text(external_id, "בוטל.")
            except ChatConfirmationError as exc:
                await gateway.send_text(external_id, str(exc))
        if callback_id:
            await gateway.answer_callback_query(callback_id)
    else:
        if callback_id:
            await gateway.answer_callback_query(callback_id)
