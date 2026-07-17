"""RSF-030 — Open Finance read-path cache.

Policy (owner, 2026-07-17): all Open Finance data is synced into our own
Postgres once daily; analytics/UI/bot read from OUR database. Live Open
Finance calls are allowed only for (a) the scheduled daily sync, (b) explicit
user-triggered refresh under cooldown, (c) write operations. Open Finance has
a small monthly call-credit budget and a read-path leak is a real cost bug
(the same class of bug that caused real SUMIT overage charges).

This module is the one place that decides "serve cache vs. call live" for
routes that don't have a first-class local model to read from directly
(`open_finance.py`'s `/accounts` and `/transactions` read `Account`/
`BankTransaction` directly instead and never touch this module).

Usage — `get_or_fetch` never builds/calls the Open Finance client itself.
The caller passes `fetch_coro_factory`, a zero-argument callable that
*returns a coroutine* (e.g. ``lambda: _run(db, org_id, lambda c: c.list_payments())``).
The factory is invoked (and therefore the client constructed) only on a
stale/missing cache row or an explicit forced refresh — a fresh cache hit
never touches it, which is what keeps a cache-hit page view from spending
any of the call budget.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy.orm import Session

from ..config import settings
from ..models import OfSnapshotCache

logger = logging.getLogger(__name__)


class OfSnapshotRefreshCooldown(Exception):
    """Raised when `force_refresh=True` is requested before the cooldown
    window (since the last live fetch of this resource) has elapsed. Routes
    map this to HTTP 429 with `retry_after_seconds`."""

    def __init__(self, retry_after_seconds: int, cooldown_until: datetime):
        self.retry_after_seconds = max(0, retry_after_seconds)
        self.cooldown_until = cooldown_until
        super().__init__(
            f"refresh cooldown active — retry in {self.retry_after_seconds}s"
        )


def _row_payload(row: OfSnapshotCache) -> dict[str, Any]:
    payload = row.payload
    if not isinstance(payload, dict):
        payload = {"items": payload}
    return dict(payload)


async def get_or_fetch(
    db: Session,
    org_id: int,
    resource: str,
    fetch_coro_factory: Callable[[], Awaitable[Any]],
    *,
    max_age_hours: float = 20,
    force_refresh: bool = False,
    refresh_cooldown_minutes: int | None = None,
) -> dict[str, Any]:
    """Return a cached payload (fresh) or fetch live once (stale/missing/forced).

    - Fresh cache (`age < max_age_hours`) and not `force_refresh`: return the
      cached payload with `as_of`/`source: "cache"` added — the factory is
      never called.
    - `force_refresh=True`: bypass the freshness check, but enforce
      `refresh_cooldown_minutes` since the last live fetch — raises
      `OfSnapshotRefreshCooldown` if still within the window.
    - Stale/missing (or a permitted forced refresh): call the factory
      exactly once, upsert the cache, return the fresh payload with
      `source: "live"`.
    - If the live fetch raises and a cache row already exists, return the
      stale row instead of failing the page, tagged
      `source: "stale_cache"` with an `error` field. No existing row ->
      propagate the exception (there is nothing to fall back to).
    """
    if refresh_cooldown_minutes is None:
        refresh_cooldown_minutes = settings.manual_refresh_cooldown_minutes

    row = (
        db.query(OfSnapshotCache)
        .filter(
            OfSnapshotCache.organization_id == org_id,
            OfSnapshotCache.resource == resource,
        )
        .first()
    )
    now = datetime.utcnow()
    age = (now - row.fetched_at) if (row and row.fetched_at) else None

    if force_refresh:
        if age is not None and age < timedelta(minutes=refresh_cooldown_minutes):
            cooldown_until = row.fetched_at + timedelta(minutes=refresh_cooldown_minutes)
            retry_after = int((cooldown_until - now).total_seconds())
            raise OfSnapshotRefreshCooldown(retry_after, cooldown_until)
    elif age is not None and age < timedelta(hours=max_age_hours):
        payload = _row_payload(row)
        payload["as_of"] = row.fetched_at.isoformat()
        payload["source"] = "cache"
        return payload

    try:
        live_payload = await fetch_coro_factory()
    except Exception as exc:  # noqa: BLE001 — deliberately broad: fall back to stale cache
        if row is not None:
            logger.warning(
                "Open Finance live fetch failed for org=%s resource=%s — serving stale cache: %s",
                org_id, resource, exc,
            )
            payload = _row_payload(row)
            payload["as_of"] = row.fetched_at.isoformat() if row.fetched_at else None
            payload["source"] = "stale_cache"
            payload["error"] = str(exc)
            return payload
        raise

    if not isinstance(live_payload, dict):
        stored_payload: dict[str, Any] = {"items": live_payload}
    else:
        stored_payload = dict(live_payload)

    if row is None:
        row = OfSnapshotCache(organization_id=org_id, resource=resource)
        db.add(row)
    row.payload = stored_payload
    row.fetched_at = now
    db.commit()

    result = dict(stored_payload)
    result["as_of"] = now.isoformat()
    result["source"] = "live"
    return result
