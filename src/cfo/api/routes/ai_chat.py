"""AI chat assistant routes (Wave 2 Step 9.2). Every write the assistant
proposes is a pending_action requiring a separate, explicit confirmation —
see ai_chat_service.py for why this is enforced server-side, not by prompt."""
import re

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ...database import get_db_session
from ...models import ChatMessage, User, UserRole
from ..dependencies import get_current_org_id, get_current_user
from ...services.ai_chat_service import AIChatService, ChatConfirmationError

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
    return {"messages": [
        {
            "id": m.id, "role": m.role, "content": m.content,
            "pending_action": m.pending_action, "executed": m.executed,
            "action_status": m.action_status or (
                "executed" if m.executed else ("pending" if m.pending_action else None)
            ),
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]}
