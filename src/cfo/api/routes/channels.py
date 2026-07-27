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
from ...models import ChannelIdentity, User
from ..dependencies import get_current_org_id, get_current_user
from ...services.channel_link_service import issue_link_code

router = APIRouter(prefix="/channels", tags=["Channels"])


def _mask_external_id(external_id: str) -> str:
    """Partial mask so the endpoint doesn't hand back a usable phone
    number/chat id in the clear — keeps first 2 and last 2 characters,
    same spirit as masking a card number."""
    if len(external_id) <= 4:
        return "*" * len(external_id)
    return f"{external_id[:2]}{'*' * (len(external_id) - 4)}{external_id[-2:]}"


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


@router.get("/identities")
async def list_channel_identities(
    org_id: int = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    """Currently-linked channel identities for the caller's organization —
    verified and not revoked. external_id is partially masked; deletion is
    intentionally out of scope for this endpoint (plan package G, step 4)."""
    rows = (
        db.query(ChannelIdentity)
        .filter(
            ChannelIdentity.organization_id == org_id,
            ChannelIdentity.verified_at.isnot(None),
            ChannelIdentity.revoked_at.is_(None),
        )
        .order_by(ChannelIdentity.created_at.desc())
        .all()
    )
    return {
        "identities": [
            {
                "provider": row.provider,
                "external_id_masked": _mask_external_id(row.external_id),
                "display_name": row.display_name,
                "verified_at": row.verified_at.replace(tzinfo=timezone.utc).isoformat()
                if row.verified_at else None,
                "push_enabled": row.push_enabled is not False,
            }
            for row in rows
        ]
    }
