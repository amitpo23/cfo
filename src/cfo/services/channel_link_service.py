"""Channel-identity linking (decision 6, plan 2026-07-26; package G, plan
2026-07-27b).

Two independent linking routes feed the same ChannelIdentity table:

1. App-issued code (issue_link_code / redeem_link_code, unchanged below): a
   user authenticated via JWT mints a one-time code inside the app, types it
   into the external channel (``/start <code>``), and the channel-side
   handler calls redeem_link_code with the provider + external chat id.

2. Email-based verification (start_email_verification /
   complete_email_verification, package G): SUMIT exposes no API for the
   list of phone numbers/users authorized on an org's account (verified:
   zero endpoints — ``companies/roles`` is UI-only), so a phone number
   messaging the bot cannot be checked against SUMIT directly. Instead the
   channel identity is verified against rezef's own ``User`` table: the
   phone types the email it registered with, and a 6-digit code is sent to
   that *registered* email address — control of the phone plus control of
   the mailbox is a real two-factor check.

Only a sha256 hash of any code is ever persisted; a plaintext code is
returned/sent to the user exactly once and never stored.
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from ..models import ChannelIdentity, ChannelLinkCode, ChannelProcessedUpdate, User
from .email_sender import send_email_smtp

LINK_CODE_TTL_MINUTES = 15

# --- package G: email-based verification for unknown phone numbers --- #
EMAIL_CODE_TTL_MINUTES = 10
MAX_ATTEMPTS_PER_EXTERNAL_ID = 5  # failed verification attempts per external_id
_ATTEMPT_WINDOW = timedelta(hours=1)

# ChannelLinkCode has no external_id/email/attempts column (models.py is owned
# by package E in this branch — out of scope here, see plan package G). Two
# deliberate schema-free choices close that gap without a migration:
#
#   - external_id binding: the code's sha256 hash folds in
#     f"{provider}:{external_id}:{code}" (see _hash_email_code) instead of
#     just the code. A code is therefore only ever redeemable by looking up
#     the *same* hash, which requires the *same* external_id — a code sent
#     to one phone/chat cannot be redeemed by quoting it from another one,
#     with zero extra storage.
#   - attempt counting: ChannelProcessedUpdate (provider/update_id dedupe
#     table, otherwise used for Telegram update-id dedupe) is reused as an
#     append-only failed-attempt log, one row per failed attempt, with
#     provider="link_attempt" and update_id encoding
#     "<real_provider>|<external_id>|<random suffix>". Counting failed
#     attempts in the last hour is a LIKE-prefix query on update_id. This is
#     the "or an existing table" option the plan explicitly allows, chosen
#     over "count codes created" because it tracks the thing that actually
#     matters for brute-force protection (wrong guesses), not code reissuance.
_ATTEMPT_LOG_PROVIDER = "link_attempt"

# Rate limit on *requesting* a code, separate from the failed-guess limit
# above. Without it, start_email_verification is an unbounded oracle: an
# attacker holding Moshko's number can probe addresses to learn who is a
# rezef customer, and can repeatedly mint codes into a real customer's
# inbox (mail bombing). Uses the same append-only log under its own marker.
MAX_REQUESTS_PER_EXTERNAL_ID = 3
_REQUEST_LOG_PROVIDER = "link_request"

# The enumeration-safe response is only enumeration-safe if it also takes
# the same time to produce. The known-email path does DB writes and awaits
# an SMTP round trip; returning instantly for an unknown address turns
# latency into the very oracle the identical wording exists to remove.
# Both paths are padded to this floor. It narrows the signal rather than
# erasing it — an unusually slow SMTP hop can still exceed the floor — but
# combined with MAX_REQUESTS_PER_EXTERNAL_ID (3/hour) there is no usable
# probing budget left.
_MIN_START_RESPONSE_SECONDS = 2.0


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


# --- package G: email-based verification --- #

_ENUMERATION_SAFE_RESPONSE = {
    "status": "code_sent",
    "message": "אם הכתובת רשומה במערכת, נשלח אליה קוד בן 6 ספרות. הקוד תקף 10 דקות.",
}


def _hash_email_code(provider: str, external_id: str, code: str) -> str:
    """Folds provider+external_id into the hash so a code is only ever
    redeemable by the exact (provider, external_id) it was issued for —
    see the module docstring for why this replaces a dedicated column."""
    return hashlib.sha256(f"{provider}:{external_id}:{code}".encode("utf-8")).hexdigest()


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _record_attempt(db: Session, provider: str, external_id: str, marker: str) -> None:
    db.add(ChannelProcessedUpdate(
        provider=marker,
        update_id=f"{provider}|{external_id}|{secrets.token_hex(8)}",
    ))
    db.commit()


def _record_failed_attempt(db: Session, provider: str, external_id: str) -> None:
    _record_attempt(db, provider, external_id, _ATTEMPT_LOG_PROVIDER)


def _attempt_count(db: Session, provider: str, external_id: str, marker: str) -> int:
    window_start = datetime.utcnow() - _ATTEMPT_WINDOW
    pattern = f"{_like_escape(provider)}|{_like_escape(external_id)}|%"
    return (
        db.query(ChannelProcessedUpdate)
        .filter(
            ChannelProcessedUpdate.provider == marker,
            ChannelProcessedUpdate.update_id.like(pattern, escape="\\"),
            ChannelProcessedUpdate.created_at >= window_start,
        )
        .count()
    )


def _failed_attempt_count(db: Session, provider: str, external_id: str) -> int:
    return _attempt_count(db, provider, external_id, _ATTEMPT_LOG_PROVIDER)


async def _pad_to_floor(started_at: float) -> None:
    """Hold the response until _MIN_START_RESPONSE_SECONDS have elapsed, so
    the unknown-email path can't be told apart from the send-an-email path
    by how fast it answers."""
    remaining = _MIN_START_RESPONSE_SECONDS - (time.monotonic() - started_at)
    if remaining > 0:
        await asyncio.sleep(remaining)


async def start_email_verification(
    db: Session, *, provider: str, external_id: str, email: str,
    display_name: Optional[str] = None,
) -> dict:
    """Begin email-based verification for an unlinked channel identity.

    Always returns the SAME response dict for an unknown email as for a
    known one — the only observable difference is whether an email actually
    goes out — so a phone number probing addresses can never learn which
    ones are registered in rezef. ``display_name`` is accepted for symmetry
    with the app-issued-code flow but is not persisted by this function:
    there is no schema slot to carry it across to complete_email_verification
    without a models.py change (out of scope, see module docstring), so a
    caller that wants it on the resulting ChannelIdentity should set
    ``identity.display_name`` itself after a successful
    complete_email_verification (the Telegram webhook does exactly this).
    """
    started_at = time.monotonic()

    # Counted BEFORE any lookup, and for every request regardless of outcome
    # — otherwise the limit itself would only bite on real addresses and
    # become an oracle of its own.
    if _attempt_count(db, provider, external_id, _REQUEST_LOG_PROVIDER) >= MAX_REQUESTS_PER_EXTERNAL_ID:
        await _pad_to_floor(started_at)
        return {
            "status": "rate_limited",
            "message": (
                "יותר מדי בקשות קוד ממכשיר זה — נסה שוב בעוד שעה, "
                "או השתמש בקוד קישור מהאפליקציה."
            ),
        }
    _record_attempt(db, provider, external_id, _REQUEST_LOG_PROVIDER)

    normalized_email = email.strip().lower()
    user = (
        db.query(User)
        .filter(
            User.email == normalized_email,
            User.is_active.is_(True),
            User.organization_id.isnot(None),  # excludes super admins (decision: package G)
        )
        .first()
    )
    if user is None:
        await _pad_to_floor(started_at)
        return dict(_ENUMERATION_SAFE_RESPONSE)

    now = datetime.utcnow()
    # Invalidate the user's previous open codes (app-issued or email) —
    # same "only the newest code is redeemable" rule as issue_link_code.
    # Scoped by user_id rather than external_id (the plan's "same
    # external_id" wording) because external_id isn't a queryable column
    # here; a user only ever has one phone in practice, so this is a strict
    # superset of the intended invalidation, not a security gap.
    db.query(ChannelLinkCode).filter(
        ChannelLinkCode.user_id == user.id,
        ChannelLinkCode.used_at.is_(None),
        ChannelLinkCode.expires_at > now,
    ).update({"used_at": now}, synchronize_session=False)

    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = now + timedelta(minutes=EMAIL_CODE_TTL_MINUTES)
    row = ChannelLinkCode(
        organization_id=user.organization_id, user_id=user.id,
        code_hash=_hash_email_code(provider, external_id, code),
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()

    from ..config import settings

    sent = await send_email_smtp(
        normalized_email,
        "קוד אימות לרצף",
        (
            f"קוד האימות שלך לחיבור ערוץ צ'אט ({provider}) ברצף: {code}\n"
            f"הקוד תקף ל-{EMAIL_CODE_TTL_MINUTES} דקות, וניתן למימוש רק מהמכשיר "
            "שממנו נשלחה הבקשה.\n"
            "אם לא ביקשת קוד זה, אפשר להתעלם מהודעה זו."
        ),
        settings,
    )
    if not sent:
        # Honest-null: never claim "sent" when it wasn't. Burn the code we
        # just minted so an undelivered code can't sit valid for 10 minutes
        # with nobody but us knowing its value.
        row.used_at = datetime.utcnow()
        db.commit()
        await _pad_to_floor(started_at)
        return {
            "status": "email_unavailable",
            "message": "לא הצלחנו לשלוח מייל כרגע — נסה שוב מאוחר יותר.",
        }
    await _pad_to_floor(started_at)
    return dict(_ENUMERATION_SAFE_RESPONSE)


def complete_email_verification(
    db: Session, *, provider: str, external_id: str, code: str,
) -> ChannelIdentity:
    """Validate a 6-digit email-verification code and, on success, bind
    (provider, external_id) to the code's user/org — same re-pointing
    semantics as redeem_link_code — and (whatsapp only) backfill User.phone."""
    if _failed_attempt_count(db, provider, external_id) >= MAX_ATTEMPTS_PER_EXTERNAL_ID:
        raise ChannelLinkError(
            "יותר מדי ניסיונות שגויים ממכשיר זה — נסה שוב בעוד שעה, "
            "או השתמש בקוד קישור מהאפליקציה (/start <קוד>)"
        )

    row = (
        db.query(ChannelLinkCode)
        .filter(ChannelLinkCode.code_hash == _hash_email_code(provider, external_id, code))
        .order_by(ChannelLinkCode.id.desc())
        .first()
    )
    if row is None:
        _record_failed_attempt(db, provider, external_id)
        raise ChannelLinkError("קוד שגוי או שאינו שייך למכשיר זה")
    if row.used_at is not None:
        _record_failed_attempt(db, provider, external_id)
        raise ChannelLinkError("קוד האימות כבר נוצל — יש לבקש קוד חדש")
    if row.expires_at < datetime.utcnow():
        _record_failed_attempt(db, provider, external_id)
        raise ChannelLinkError("קוד האימות פג תוקף — יש לבקש קוד חדש")

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
    identity.verified_at = datetime.utcnow()

    # Deviation from the plan's literal "whatsapp OR phone empty": external_id
    # is only actually a phone number for provider="whatsapp" — for telegram
    # it's a chat_id. Backfilling User.phone with a chat_id whenever the
    # field happened to be empty would put fabricated data into a column
    # other features (package F WhatsApp routing, package H "מספרים
    # מורשים") will read as a real phone number — the honest-null doctrine
    # applied to a field, not just a number. Only whatsapp writes here;
    # ChannelIdentity.external_id already preserves the telegram chat_id.
    user = db.query(User).filter(User.id == row.user_id).first()
    if user is not None and provider == "whatsapp":
        user.phone = external_id

    db.commit()
    db.refresh(identity)
    return identity
