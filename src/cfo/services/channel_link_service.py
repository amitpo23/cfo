"""Channel-identity linking (decision 6, plan 2026-07-26).

A user authenticated via JWT mints a one-time code inside the app
(issue_link_code). They then type that code into an external channel —
currently Telegram, via ``/start <code>`` — and the channel-side handler
calls redeem_link_code with the provider + external chat id. Only the
code's sha256 hash is ever persisted; the plaintext code is returned to the
caller exactly once (by the route) and never stored.

No phone-number lookups, no passwords in chat — the code itself, scoped to
a short TTL and single-use, is the entire trust chain from "authenticated
web session" to "verified channel identity".
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from ..models import ChannelIdentity, ChannelLinkCode

LINK_CODE_TTL_MINUTES = 15


class ChannelLinkError(ValueError):
    """Raised on any redemption failure. Message is Hebrew and user-facing
    (surfaced verbatim back to the chat channel)."""


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def issue_link_code(db: Session, organization_id: int, user_id: int) -> dict:
    """Mint a fresh one-time link code for this user.

    Any of the user's previously issued, still-unused, still-unexpired
    codes are invalidated first (used_at set now) — only the newest code is
    ever redeemable, so an old code shown on screen earlier can't quietly
    keep working after a new one was requested.
    """
    now = datetime.utcnow()
    db.query(ChannelLinkCode).filter(
        ChannelLinkCode.user_id == user_id,
        ChannelLinkCode.used_at.is_(None),
        ChannelLinkCode.expires_at > now,
    ).update({"used_at": now}, synchronize_session=False)

    code = secrets.token_hex(4)  # 8 hex chars — short enough to type into Telegram
    expires_at = now + timedelta(minutes=LINK_CODE_TTL_MINUTES)
    row = ChannelLinkCode(
        organization_id=organization_id, user_id=user_id,
        code_hash=_hash_code(code), expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"code": code, "expires_at": expires_at}


def redeem_link_code(
    db: Session, code: str, *, provider: str, external_id: str,
    display_name: Optional[str] = None,
) -> ChannelIdentity:
    """Validate and consume a one-time code, binding (provider, external_id)
    to the code's issuing user/organization.

    If a ChannelIdentity already exists for this exact (provider,
    external_id) pair (e.g. the same Telegram chat re-linking to a
    different rezef account), it is re-pointed to the new user/org and
    un-revoked — a link code always wins over whatever mapping existed
    before, since redeeming one requires a fresh authenticated JWT session.
    """
    row = (
        db.query(ChannelLinkCode)
        .filter(ChannelLinkCode.code_hash == _hash_code(code))
        .order_by(ChannelLinkCode.id.desc())
        .first()
    )
    if row is None:
        raise ChannelLinkError("קוד הקישור אינו קיים או שגוי")
    if row.used_at is not None:
        raise ChannelLinkError("קוד הקישור כבר נוצל — יש להנפיק קוד חדש")
    if row.expires_at < datetime.utcnow():
        raise ChannelLinkError("קוד הקישור פג תוקף — יש להנפיק קוד חדש")

    row.used_at = datetime.utcnow()

    identity = (
        db.query(ChannelIdentity)
        .filter(
            ChannelIdentity.provider == provider,
            ChannelIdentity.external_id == external_id,
        )
        .first()
    )
    if identity is None:
        identity = ChannelIdentity(
            organization_id=row.organization_id, user_id=row.user_id,
            provider=provider, external_id=external_id,
        )
        db.add(identity)
    else:
        identity.organization_id = row.organization_id
        identity.user_id = row.user_id
        identity.revoked_at = None
    if display_name:
        identity.display_name = display_name
    identity.verified_at = datetime.utcnow()

    db.commit()
    db.refresh(identity)
    return identity


def resolve_identity(db: Session, provider: str, external_id: str) -> Optional[ChannelIdentity]:
    """Return the verified, non-revoked identity for (provider, external_id),
    or None. A revoked or never-verified row must behave identically to "no
    identity" everywhere a caller checks this — never partially trusted."""
    return (
        db.query(ChannelIdentity)
        .filter(
            ChannelIdentity.provider == provider,
            ChannelIdentity.external_id == external_id,
            ChannelIdentity.verified_at.isnot(None),
            ChannelIdentity.revoked_at.is_(None),
        )
        .first()
    )
