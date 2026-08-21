"""AI chat assistant routes (Wave 2 Step 9.2). Every write the assistant
proposes is a pending_action requiring a separate, explicit confirmation —
see ai_chat_service.py for why this is enforced server-side, not by prompt."""
import re

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...database import get_db_session
from ...models import ChatMessage, MoshkoFeedback, User, UserRole
from ..dependencies import get_current_org_id, get_current_user
from ...services.ai_chat_service import AIChatService, ChatConfirmationError
from ...services.moshko_feedback_service import (
    FEEDBACK_CATEGORIES as _FEEDBACK_CATEGORIES,
    FeedbackNotFoundError,
    FeedbackValidationError,
    record_feedback,
)

router = APIRouter(prefix="/ai", tags=["AI Chat"])
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _validate_session_id(value: object) -> str:
    session_id = value if isinstance(value, str) else ""
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(
            400,
            "session_id חייב להכיל 1–64 תווי אותיות לטיניות, ספרות, - או _",
        )
    return session_id


def _service_for(db: Session, org_id: int, user: User) -> AIChatService:
    # Role is read from the DB-backed `user` (get_current_user), never a
    # client-supplied claim — same source of truth the rest of the app uses
    # for SUPER_ADMIN checks (see api/dependencies.py get_super_admin).
    return AIChatService(db, org_id, user.id, is_super_admin=user.role == UserRole.SUPER_ADMIN)


def _feedback_payload(row: MoshkoFeedback) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "message_id": row.message_id,
        "category": row.category,
        "comment": row.comment,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.post("/chat")
async def send_chat_message(
    body: dict = Body(...),
    org_id: int = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    session_id = _validate_session_id(body.get("session_id"))
    text = body.get("message", "")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(400, "message נדרש")
    persona = body.get("persona")

    service = _service_for(db, org_id, user)
    return await service.send_message(session_id, text, persona=persona)


@router.post("/chat/confirm")
async def confirm_chat_action(
    body: dict = Body(...),
    org_id: int = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    message_id = body.get("message_id")
    if not isinstance(message_id, int):
        raise HTTPException(400, "message_id נדרש")

    service = _service_for(db, org_id, user)
    try:
        return await service.confirm_action(message_id)
    except ChatConfirmationError as exc:
        raise HTTPException(400, str(exc))


@router.post("/chat/cancel")
async def cancel_chat_action(
    body: dict = Body(...),
    org_id: int = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    message_id = body.get("message_id")
    if not isinstance(message_id, int):
        raise HTTPException(400, "message_id נדרש")

    service = _service_for(db, org_id, user)
    try:
        return service.cancel_action(message_id)
    except ChatConfirmationError as exc:
        raise HTTPException(400, str(exc))


@router.get("/chat/{session_id}")
async def get_chat_history(
    session_id: str,
    org_id: int = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    session_id = _validate_session_id(session_id)
    # user_id scoped too — a chat session is a private conversation, not
    # shared team data; session_id alone (client-generated) isn't a secret.
    rows = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.organization_id == org_id,
            ChatMessage.user_id == user.id,
            ChatMessage.session_id == session_id,
        )
        .order_by(ChatMessage.id.asc())
        .all()
    )
    feedback_by_message = {
        row.message_id: row
        for row in db.query(MoshkoFeedback).filter(
            MoshkoFeedback.organization_id == org_id,
            MoshkoFeedback.user_id == user.id,
            MoshkoFeedback.message_id.in_([row.id for row in rows] or [-1]),
        ).all()
    }
    return {"messages": [
        {
            "id": m.id, "role": m.role, "content": m.content,
            "pending_action": m.pending_action, "executed": m.executed,
            "action_status": m.action_status or (
                "executed" if m.executed else ("pending" if m.pending_action else None)
            ),
            "feedback": (
                {
                    "category": feedback_by_message[m.id].category,
                    "comment": feedback_by_message[m.id].comment,
                    "status": feedback_by_message[m.id].status,
                }
                if m.id in feedback_by_message else None
            ),
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]}


@router.post("/chat/{message_id}/feedback", status_code=status.HTTP_201_CREATED)
async def submit_chat_feedback(
    message_id: int,
    body: dict = Body(...),
    org_id: int = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    """Record or replace the current user's verdict on one assistant answer.

    Thin HTTP wrapper: all the actual logic (idempotent upsert, gap-queue
    trigger, audit log) lives in moshko_feedback_service.record_feedback,
    shared verbatim with the Telegram inline-keyboard callback — one
    mechanism, not a parallel path per channel."""
    category = body.get("category")
    if category not in _FEEDBACK_CATEGORIES:
        raise HTTPException(400, "Invalid feedback category")
    comment_value = body.get("comment")
    if comment_value is not None and not isinstance(comment_value, str):
        raise HTTPException(400, "comment must be text")
    comment = comment_value.strip()[:2000] if comment_value else None

    try:
        row = record_feedback(
            db,
            organization_id=org_id,
            user_id=user.id,
            message_id=message_id,
            category=category,
            comment=comment,
        )
    except FeedbackNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except FeedbackValidationError as exc:
        raise HTTPException(400, str(exc))
    return _feedback_payload(row)
