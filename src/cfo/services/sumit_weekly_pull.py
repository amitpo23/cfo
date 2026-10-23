"""SUMIT weekly pull: at most one scheduled read-only pull per ISO week.

Owner decision 2026-10-23. One scheduled pull per week for all organizations
combined, plus on-demand admin requests, inside the account-wide monthly
ceiling (50 calls on live, ``sumit_request_budget.account_monthly_request_limit``).
This module only decides and records; the sync itself is the cron route's
existing loop.

Order of the gates, all before any SUMIT client is built:

1. ``SUMIT_WEEKLY_PULL_ENABLED`` (default off).
2. Quota: the calls left this month minus the on-demand reserve (at least 10)
   must cover ``targets * sumit_weekly_pull_calls_per_org``. Otherwise skip.
3. Idempotency: one durable claim per Asia/Jerusalem ISO week in
   ``provider_request_budgets`` (atomic upsert, shared by every instance).

While the pull runs, ``scheduled_pull_guard`` lowers the account ceiling by
the reserve and refuses any endpoint that is not a free read, so a wrong
estimate cannot spend the reserve or write to SUMIT.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import settings
from ..models import ProviderRequestBudget
from .sumit_request_budget import (
    SumitRequestLimiter,
    _db_now,
    account_month_used,
    account_monthly_request_limit,
)

logger = logging.getLogger(__name__)

WEEKLY_PULL_SCOPE = "sumit:weekly-pull"
WEEKLY_PULL_CALLS_SCOPE = "sumit:weekly-pull:calls"
WEEKLY_WINDOW_KIND = "week"
MIN_ON_DEMAND_RESERVE = 10
ISRAEL = ZoneInfo("Asia/Jerusalem")


def on_demand_reserve() -> int:
    return max(MIN_ON_DEMAND_RESERVE, int(settings.sumit_weekly_pull_reserve_calls))


def iso_week(now: datetime) -> tuple[str, datetime]:
    """The Asia/Jerusalem ISO week of ``now``: its key and its Monday 00:00 (UTC)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(ISRAEL)
    year, week, weekday = local.isocalendar()
    monday = (local - timedelta(days=weekday - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return f"{year}-W{week:02d}", monday.astimezone(timezone.utc)


@dataclass(frozen=True)
class QuotaView:
    limit: int
    used: int
    reserve: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def available_for_pull(self) -> int:
        return max(0, self.remaining - self.reserve)

    def as_dict(self) -> dict:
        return {
            "limit": self.limit,
            "used": self.used,
            "remaining": self.remaining,
            "reserve_for_on_demand": self.reserve,
            "available_for_weekly_pull": self.available_for_pull,
        }


def quota_view(db, *, now: datetime | None = None) -> QuotaView:
    return QuotaView(
        limit=account_monthly_request_limit(),
        used=account_month_used(db, now=now),
        reserve=on_demand_reserve(),
    )


def estimated_calls(target_count: int) -> int:
    return max(0, int(target_count)) * max(1, int(settings.sumit_weekly_pull_calls_per_org))


def quota_skip(quota: QuotaView, target_count: int) -> dict | None:
    """A skip payload when the pull would eat into the reserve or the cap."""
    needed = estimated_calls(target_count)
    if needed <= quota.available_for_pull:
        return None
    return {
        "status": "ok",
        "skipped": "sumit_monthly_quota_reserved",
        "estimated_calls": needed,
        "quota": quota.as_dict(),
        "results": [],
    }


def claim_week(db, *, now: datetime) -> tuple[bool, str]:
    """Atomically claim this ISO week's single run. False if already claimed."""
    week_key, week_start = iso_week(now)
    claimed = SumitRequestLimiter._claim_window(
        db,
        scope_key=WEEKLY_PULL_SCOPE,
        organization_id=None,
        window_kind=WEEKLY_WINDOW_KIND,
        window_start=week_start,
        limit_value=1,
        now=now,
    )
    return claimed, week_key


def record_calls_used(db, *, now: datetime, calls_used: int) -> None:
    """Keep the calls one weekly pull spent next to its claim (no new table)."""
    if calls_used <= 0:
        return
    _, week_start = iso_week(now)
    SumitRequestLimiter._seed_window_floor(
        db,
        scope_key=WEEKLY_PULL_CALLS_SCOPE,
        organization_id=None,
        window_kind=WEEKLY_WINDOW_KIND,
        window_start=week_start,
        used=calls_used,
        limit_value=account_monthly_request_limit(),
        now=now,
    )


def _week_rows(db, scope_key: str) -> list[ProviderRequestBudget]:
    return (
        db.query(ProviderRequestBudget)
        .filter(
            ProviderRequestBudget.provider == "sumit",
            ProviderRequestBudget.scope_key == scope_key,
            ProviderRequestBudget.window_kind == WEEKLY_WINDOW_KIND,
        )
        .order_by(ProviderRequestBudget.window_start.desc())
        .all()
    )


def weekly_pull_status(db, *, now: datetime | None = None) -> dict:
    """Read-only admin indicator: calls left this month and the last weekly pull."""
    moment = now or _db_now(db)
    quota = quota_view(db, now=moment)
    last = next(iter(_week_rows(db, WEEKLY_PULL_SCOPE)), None)
    last_pull = None
    if last is not None:
        calls = next(
            (row.used for row in _week_rows(db, WEEKLY_PULL_CALLS_SCOPE)
             if row.window_start == last.window_start),
            0,
        )
        last_pull = {
            "week": iso_week(last.window_start)[0],
            "claimed_at": last.updated_at.isoformat() if last.updated_at else None,
            "calls_used": int(calls),
        }
    return {
        "enabled": bool(settings.sumit_weekly_pull_enabled),
        "schedule": "Sunday 05:00 Asia/Jerusalem (03:00 UTC)",
        "this_week": iso_week(moment)[0],
        "estimated_calls_per_org": max(1, int(settings.sumit_weekly_pull_calls_per_org)),
        "quota": quota.as_dict(),
        "last_pull": last_pull,
        "provider_calls": 0,
    }
