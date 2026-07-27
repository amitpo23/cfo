"""Channel link-code issuance (decision 6, plan 2026-07-26).

A single authenticated endpoint: the logged-in user asks for a one-time
code, then types it into an external channel (currently Telegram, via
``/start <code>``) to bind that channel identity to their organization.
The plaintext code is returned exactly once here — only its hash persists
(see channel_link_service.issue_link_code) — so it can never be recovered
through this API again after this response.
"""
from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database import get_db_session
from ...models import User
from ..dependencies import get_current_org_id, get_current_user
from ...services.channel_link_service import issue_link_code

router = APIRouter(prefix="/channels", tags=["Channels"])


@router.post("/link-code")
async def create_link_code(
    org_id: int = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    result = issue_link_code(db, org_id, user.id)
    return {
        "code": result["code"],
        # Stored naive-UTC (channel_link_service uses utcnow), so the offset
        # must be stated explicitly on the wire: a bare naive ISO string is
        # parsed as LOCAL time by browsers, which in Israel (UTC+3) would
        # make a fresh code look already-expired to the countdown in
        # SettingsPage.tsx.
        "expires_at": result["expires_at"].replace(tzinfo=timezone.utc).isoformat(),
        "instructions": (
            f"שלח לבוט הטלגרם של רצף את ההודעה: /start {result['code']} "
            "תוך 15 דקות. הקוד חד-פעמי ולא יוצג שוב."
        ),
    }
