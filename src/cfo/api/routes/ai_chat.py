"""AI chat assistant routes (Wave 2 Step 9.2). Every write the assistant
proposes is a pending_action requiring a separate, explicit confirmation —
see ai_chat_service.py for why this is enforced server-side, not by prompt."""
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ...database import get_db_session
from ...models import ChatMessage, User, UserRole
from ..dependencies import get_current_org_id, get_current_user
from ...services.ai_chat_service import AIChatService, ChatConfirmationError

router = APIRouter(prefix="/ai", tags=["AI Chat"])


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
    session_id = body.get("session_id") or ""
    text = body.get("message", "")
    if not session_id or not text.strip():
        raise HTTPException(400, "session_id ו-message נדרשים")

    service = _service_for(db, org_id, user)
    return await service.send_message(session_id, text)


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


@router.get("/chat/{session_id}")
async def get_chat_history(
    session_id: str,
    org_id: int = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
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
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]}
