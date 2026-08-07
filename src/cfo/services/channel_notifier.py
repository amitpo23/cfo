"""Proactive (agent-initiated) push to conversational channels — package B of
docs/superpowers/plans/2026-07-27-moshko-full-bot.md.

Before this module, ``TelegramGateway`` (channel_gateway.py) was only ever
constructed inside telegram_webhook.py's own request cycle — there was no
path from a cron job or the morning brief to Telegram. This module is that
path, and the ONLY one: callers that want to push to an organization's linked
channel identities go through ``push_to_organization`` here, never build a
gateway directly.

Provider-specific configuration, per-identity opt-in and quiet-hours gates
apply before any message reaches Telegram or WhatsApp. WhatsApp additionally
enforces Meta's 24-hour customer-service window; outside it, only an approved
configured template may be attempted.
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
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..config import settings
from ..models import ChannelIdentity

logger = logging.getLogger(__name__)

QUIET_START_HOUR = 22
QUIET_END_HOUR = 7
WHATSAPP_SERVICE_WINDOW = timedelta(hours=24)


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
    db: Session, organization_id: int, *, provider: str | None = None,
) -> list[ChannelIdentity]:
    """Verified, non-revoked, not-explicitly-opted-out identities for an
    organization on the given provider — the exact set any push should reach.
    Mirrors channel_link_service.resolve_identity's verified/not-revoked
    filter, plus the push_enabled opt-in (NULL/True both count as enabled;
    only an explicit False opts out)."""
    query = db.query(ChannelIdentity).filter(
            ChannelIdentity.organization_id == organization_id,
            ChannelIdentity.verified_at.isnot(None),
            ChannelIdentity.revoked_at.is_(None),
            ChannelIdentity.push_enabled.isnot(False),
        )
    if provider is not None:
        query = query.filter(ChannelIdentity.provider == provider)
    return query.all()


def _provider_configured(provider: str) -> bool:
    if provider == "telegram":
        return bool(settings.telegram_bot_token)
    if provider == "whatsapp":
        return bool(settings.whatsapp_phone_number_id and settings.whatsapp_access_token)
    return False


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def whatsapp_service_window_open(identity: ChannelIdentity, now: datetime) -> bool:
    if identity.last_inbound_at is None:
        return False
    elapsed = _utc_naive(now) - _utc_naive(identity.last_inbound_at)
    return timedelta(0) <= elapsed <= WHATSAPP_SERVICE_WINDOW


def _build_gateway(provider: str):
    if provider == "telegram":
        from .channel_gateway import TelegramGateway
        return TelegramGateway()
    if provider == "whatsapp":
        from .whatsapp_gateway import WhatsAppGateway
        return WhatsAppGateway()
    raise ValueError(f"Unsupported channel provider: {provider}")


async def push_to_organization(
    db: Session,
    organization_id: int,
    text: str,
    *,
    severity: str = "info",
    provider: str | None = None,
    gateway=None,
    gateways: dict[str, object] | None = None,
    force: bool = False,
    now: datetime | None = None,
) -> dict:
    """Push `text` to every eligible ChannelIdentity of `organization_id`.

    Never raises. Returns a dict always carrying sent/failed/skipped counts
    plus a `status` summarizing the overall outcome:
      not_configured  - the selected provider configuration is missing.
      no_recipients   - a provider is configured but the org has no eligible
                        identity to push to.
      quiet_hours     - held back by the 22:00-07:00 gate (severity below
                        "critical" and not `force`).
      sent            - at least one recipient received the message.
      failed          - had recipients, attempted, but every send failed.
      outside_service_window - WhatsApp is outside 24h and no template exists.
    """
    recipients = recipients_for(db, organization_id, provider=provider)
    if not recipients:
        configured = (
            _provider_configured(provider) if provider is not None
            else any(_provider_configured(name) for name in ("telegram", "whatsapp"))
        )
        return {
            "status": "no_recipients" if configured else "not_configured",
            "sent": 0, "failed": 0, "skipped": 0,
            "outside_service_window": 0, "not_configured": 0,
        }

    providers = {identity.provider for identity in recipients}
    configured_recipients = [i for i in recipients if _provider_configured(i.provider)]
    if not configured_recipients:
        return {
            "status": "not_configured", "sent": 0, "failed": 0, "skipped": len(recipients),
            "outside_service_window": 0, "not_configured": len(recipients),
        }

    current = now or datetime.now(timezone.utc)
    if is_quiet_hours(current) and severity != "critical" and not force:
        return {
            "status": "quiet_hours", "sent": 0, "failed": 0, "skipped": len(recipients),
            "outside_service_window": 0,
            "not_configured": len(recipients) - len(configured_recipients),
        }

    resolved_gateways = dict(gateways or {})
    if gateway is not None:
        # Backward-compatible test/caller injection for a single requested
        # provider. For provider=None it is used only when all recipients use
        # one provider, avoiding accidental cross-protocol reuse.
        if provider is not None:
            resolved_gateways[provider] = gateway
        elif len(providers) == 1:
            resolved_gateways[next(iter(providers))] = gateway

    sent = 0
    failed = 0
    skipped = 0
    outside_service_window = 0
    not_configured = 0
    for identity in recipients:
        if not _provider_configured(identity.provider):
            not_configured += 1
            skipped += 1
            continue
        identity_gateway = resolved_gateways.get(identity.provider)
        if identity_gateway is None:
            try:
                identity_gateway = _build_gateway(identity.provider)
            except ValueError:
                not_configured += 1
                skipped += 1
                continue
            resolved_gateways[identity.provider] = identity_gateway
        try:
            if identity.provider == "whatsapp" and not whatsapp_service_window_open(identity, current):
                template_name = settings.whatsapp_push_template_name
                if not template_name:
                    outside_service_window += 1
                    skipped += 1
                    continue
                await identity_gateway.send_template(
                    identity.external_id,
                    template_name,
                    settings.whatsapp_push_template_language,
                    [text],
                )
            else:
                await identity_gateway.send_text(identity.external_id, text)
        except Exception:  # noqa: BLE001 — one recipient's failure must not sink the rest
            logger.exception(
                "Channel push failed for organization %s identity %s",
                organization_id, identity.id,
            )
            failed += 1
            continue
        sent += 1
        identity.last_push_at = datetime.now(timezone.utc)

    db.commit()

    if sent:
        status = "sent"
    elif outside_service_window and not failed:
        status = "outside_service_window"
    elif not_configured and not failed:
        status = "not_configured"
    else:
        status = "failed"
    return {
        "status": status,
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
        "outside_service_window": outside_service_window,
        "not_configured": not_configured,
    }
