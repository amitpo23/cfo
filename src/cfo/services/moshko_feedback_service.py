"""Shared feedback-recording logic (W1.2).

Both the web chat feedback route (``api/routes/ai_chat.py``,
``POST /ai/chat/{message_id}/feedback``) and the Telegram inline-keyboard
callback (``api/routes/telegram_webhook.py``) call :func:`record_feedback`
below — one table (``MoshkoFeedback``), one gap-queue trigger
(``MoshkoGap`` via ``moshko_observability.record_gap_best_effort``), never a
parallel per-channel path.

``MoshkoGap`` has no ``source``/``channel`` column of its own — channel
provenance is carried by ``session_id``'s prefix (``tg-`` for Telegram,
``wa-`` for WhatsApp, otherwise ``web``), exactly the same way
``MoshkoFeedback.channel`` is derived below. No schema change is needed or
made here.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AuditLog, ChatMessage, MoshkoFeedback
from .moshko_observability import record_gap_best_effort

FEEDBACK_CATEGORIES = {"helpful", "inaccurate", "unknown", "unsafe"}
_GAP_TRIGGER_CATEGORIES = {"unknown", "inaccurate"}


class FeedbackValidationError(ValueError):
    """Bad category, or the message exists but isn't an assistant answer —
    the caller should surface this as HTTP 400."""


class FeedbackNotFoundError(ValueError):
    """No assistant ChatMessage matches organization_id+user_id+message_id
    (including cross-org lookups) — the caller should surface this as
    HTTP 404."""


def record_feedback(
    db: Session,
    *,
    organization_id: int,
    user_id: int,
    message_id: int,
    category: str,
    comment: str | None = None,
) -> MoshkoFeedback:
    """Record or replace this user's verdict on one assistant answer.

    Idempotent: a repeat submission with the SAME category (e.g. a double
    tap of the same Telegram button, or a retried web POST) updates the
    existing MoshkoFeedback row in place — the unique
    ``(user_id, message_id)`` constraint already guarantees no duplicate
    feedback row — and does NOT open a second MoshkoGap row for the same
    verdict. A genuine verdict CHANGE (e.g. 👎 then later 👍) opens a new
    gap only when it newly crosses into a gap-triggering category; it never
    retracts a gap already opened by an earlier verdict.
    """
    if category not in FEEDBACK_CATEGORIES:
        raise FeedbackValidationError("Invalid feedback category")

    message = db.query(ChatMessage).filter(
        ChatMessage.id == message_id,
        ChatMessage.organization_id == organization_id,
        ChatMessage.user_id == user_id,
    ).first()
    if message is None:
        raise FeedbackNotFoundError("Assistant message not found")
    if message.role != "assistant":
        raise FeedbackValidationError(
            "Feedback can be submitted only for an assistant answer"
        )

    question = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.organization_id == organization_id,
            ChatMessage.user_id == user_id,
            ChatMessage.session_id == message.session_id,
            ChatMessage.role == "user",
            ChatMessage.id < message.id,
        )
        .order_by(ChatMessage.id.desc())
        .first()
    )

    existing = db.query(MoshkoFeedback).filter(
        MoshkoFeedback.user_id == user_id,
        MoshkoFeedback.message_id == message.id,
    ).first()
    previous_category = existing.category if existing is not None else None
    created = existing is None

    if existing is None:
        session_id = message.session_id
        channel = "whatsapp" if session_id.startswith("wa-") else (
            "telegram" if session_id.startswith("tg-") else "web"
        )
        row = MoshkoFeedback(
            organization_id=organization_id,
            user_id=user_id,
            message_id=message.id,
            session_id=session_id,
            channel=channel,
            question=question.content if question else None,
            answer=message.content,
            category=category,
            comment=comment,
            status="open",
        )
        db.add(row)
    else:
        row = existing
        row.category = category
        row.comment = comment
        row.status = "open"
        row.correction = None
        row.reviewed_by = None
        row.reviewed_at = None
    db.flush()

    # W1.1 — "מושקו לא ידע" / "לא מדויק" הם פערים: שורה בתור הניתוח.
    # created-or-verdict-changed guards against opening a duplicate gap on
    # a repeat submission of the SAME category (the idempotence requirement).
    if category in _GAP_TRIGGER_CATEGORIES and (created or previous_category != category):
        record_gap_best_effort(
            db,
            organization_id=organization_id,
            user_id=user_id,
            session_id=row.session_id,
            message_id=message.id,
            gap_kind="user_flagged",
            question=row.question,
            answer=row.answer,
        )

    db.add(AuditLog(
        user_id=user_id,
        organization_id=organization_id,
        action="MOSHKO_FEEDBACK_SUBMIT",
        entity_type="MoshkoFeedback",
        entity_id=row.id,
        details={"message_id": message.id, "category": category},
    ))
    db.commit()
    db.refresh(row)
    return row
