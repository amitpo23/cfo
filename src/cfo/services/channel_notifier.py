"""Proactive (agent-initiated) push to conversational channels — package B of
docs/superpowers/plans/2026-07-27-moshko-full-bot.md.

Before this module, ``TelegramGateway`` (channel_gateway.py) was only ever
constructed inside telegram_webhook.py's own request cycle — there was no
path from a cron job or the morning brief to Telegram. This module is that
path, and the ONLY one: callers that want to push to an organization's linked
channel identities go through ``push_to_organization`` here, never build a
gateway directly.

Two independent gates apply before any message reaches Telegram:
  * per-identity opt-in (``ChannelIdentity.push_enabled``, default True —
    same nullable-defaults-True convention as
    ``Organization.morning_brief_email_enabled``: NULL means "not explicitly
    disabled", not "disabled").
  * quiet hours (22:00-07:00 Israel time) — anything below "critical"
    severity is held back during quiet hours; "critical" always goes
    through, and an explicit ``force=True`` bypasses the gate too (used by
    /cron/channel-alerts style callers, NOT by morning_brief_service, which
    deliberately never passes force through — see that module's
    _deliver_channel).

Never raises: every failure (missing token, no recipients, a single
recipient's send blowing up) is captured and reported in the returned dict
instead of propagating, matching the "never breaks the rest of the run"
contract every other outbound-notification path in this codebase already
follows (see morning_brief_service._deliver_email/_deliver_sms).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..config import settings
from ..models import ChannelIdentity

logger = logging.getLogger(__name__)

QUIET_START_HOUR = 22
QUIET_END_HOUR = 7


def is_quiet_hours(now: Optional[datetime] = None) -> bool:
    """True between 22:00 and 07:00 Israel time (settings.timezone).

    ``now`` may be omitted (defaults to the current time), timezone-aware
    (converted to Israel time), or naive (treated as already being Israel
    local time — the convenience callers/tests use when constructing a fixed
    instant to check)."""
    tz = ZoneInfo(settings.timezone)
    if now is None:
        local = datetime.now(tz)
    elif now.tzinfo is not None:
        local = now.astimezone(tz)
    else:
        local = now

    hour = local.hour
    return hour >= QUIET_START_HOUR or hour < QUIET_END_HOUR


def recipients_for(
    db: Session, organization_id: int, *, provider: str = "telegram",
) -> list[ChannelIdentity]:
    """Verified, non-revoked, not-explicitly-opted-out identities for an
    organization on the given provider — the exact set any push should reach.
    Mirrors channel_link_service.resolve_identity's verified/not-revoked
    filter, plus the push_enabled opt-in (NULL/True both count as enabled;
    only an explicit False opts out)."""
    return (
        db.query(ChannelIdentity)
        .filter(
            ChannelIdentity.organization_id == organization_id,
            ChannelIdentity.provider == provider,
            ChannelIdentity.verified_at.isnot(None),
            ChannelIdentity.revoked_at.is_(None),
            ChannelIdentity.push_enabled.isnot(False),
        )
        .all()
    )


async def push_to_organization(
    db: Session,
    organization_id: int,
    text: str,
    *,
    severity: str = "info",
    provider: str = "telegram",
    gateway=None,
    force: bool = False,
) -> dict:
    """Push `text` to every eligible ChannelIdentity of `organization_id`.

    Never raises. Returns a dict always carrying sent/failed/skipped counts
    plus a `status` summarizing the overall outcome:
      not_configured  - no telegram_bot_token configured; nothing attempted.
      no_recipients   - token is configured but the org has no eligible
                        identity to push to.
      quiet_hours     - held back by the 22:00-07:00 gate (severity below
                        "critical" and not `force`).
      sent            - at least one recipient received the message.
      failed          - had recipients, attempted, but every send failed.
    """
    if not settings.telegram_bot_token:
        return {"status": "not_configured", "sent": 0, "failed": 0, "skipped": 0}

    recipients = recipients_for(db, organization_id, provider=provider)
    if not recipients:
        return {"status": "no_recipients", "sent": 0, "failed": 0, "skipped": 0}

    if is_quiet_hours() and severity != "critical" and not force:
        return {"status": "quiet_hours", "sent": 0, "failed": 0, "skipped": len(recipients)}

    if gateway is None:
        from .channel_gateway import TelegramGateway

        gateway = TelegramGateway()

    sent = 0
    failed = 0
    for identity in recipients:
        try:
            await gateway.send_text(identity.external_id, text)
        except Exception:  # noqa: BLE001 — one recipient's failure must not sink the rest
            logger.exception(
                "Channel push failed for organization %s identity %s",
                organization_id, identity.id,
            )
            failed += 1
            continue
        sent += 1
        identity.last_push_at = datetime.utcnow()

    db.commit()

    return {
        "status": "sent" if sent else "failed",
        "sent": sent,
        "failed": failed,
        "skipped": 0,
    }
