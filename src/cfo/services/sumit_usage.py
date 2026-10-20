"""SUMIT usage ledger, 70% cap alert, and daily spike detection.

This module never calls the provider. Rows are written by the request path
after a network attempt. Bodies, credentials and query strings are not stored.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import SQLAlchemyError

from ..config import settings
from ..database import SessionLocal
from ..models import Alert, AlertSeverity, AlertStatus, ProviderCallLog

logger = logging.getLogger(__name__)

_PURPOSES = {"sync", "filing", "quota", "ops", "webhook_followup", "unspecified"}
_CAP_ALERT = "sumit_usage_cap"
_SPIKE_ALERT = "sumit_usage_spike"


def _monthly_request_limit() -> int:
    if settings.sumit_environment == "test":
        return settings.sumit_test_monthly_request_limit
    return settings.sumit_live_monthly_request_limit


def _endpoint_class(endpoint: str) -> str:
    from ..integrations.sumit_integration import (
        INFERRED_FREE_ENDPOINTS,
        VERIFIED_FREE_ENDPOINTS,
    )

    path = (endpoint or "").split("?", 1)[0]
    if path in VERIFIED_FREE_ENDPOINTS:
        return "free"
    if path in INFERRED_FREE_ENDPOINTS:
        return "inferred"
    return "paid"


def _purpose(value: str | None, *, environment_verification: bool) -> str:
    if environment_verification:
        return "ops"
    if value in _PURPOSES:
        return value
    return "unspecified"


def _median(values: list[int]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    if count == 0:
        return 0.0
    mid = count // 2
    if count % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _day_start(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(moment: datetime) -> datetime:
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _has_active_alert(
    db, organization_id: int, alert_type: str, *, key_name: str, key: str,
) -> bool:
    rows = (
        db.query(Alert)
        .filter(
            Alert.organization_id == organization_id,
            Alert.alert_type == alert_type,
            Alert.status == AlertStatus.ACTIVE,
        )
        .all()
    )
    return any((row.meta or {}).get(key_name) == key for row in rows)


def _raise_alert(db, *, organization_id: int, alert_type: str, title: str, message: str, meta: dict) -> None:
    db.add(Alert(
        organization_id=organization_id,
        alert_type=alert_type,
        severity=AlertSeverity.WARNING,
        title=title,
        message=message,
        status=AlertStatus.ACTIVE,
        meta=meta,
    ))


def _count_calls(db, *, organization_id: int | None, office_organization_id: int | None,
                 start: datetime, end: datetime, end_inclusive: bool) -> int:
    query = db.query(ProviderCallLog).filter(
        ProviderCallLog.provider == "sumit",
        ProviderCallLog.at >= start,
    )
    if end_inclusive:
        query = query.filter(ProviderCallLog.at <= end)
    else:
        query = query.filter(ProviderCallLog.at < end)
    if office_organization_id is not None:
        query = query.filter(ProviderCallLog.office_organization_id == office_organization_id)
    else:
        query = query.filter(ProviderCallLog.organization_id == organization_id)
    return query.count()


def audit_sumit_usage(
    db, organization_id: int, *, now: datetime, office_organization_id: int | None = None,
) -> list[str]:
    """Return the alert types created for this observation. Does not commit.

    The monthly cap alert is keyed by calendar month, so the next month can
    alert again. A spike is today's count at or above both twice the prior
    14-day median and 5 calls.
    """
    office_id = office_organization_id or organization_id
    created = _audit_window(
        db, organization_id, now=now, office_organization_id=None,
    )
    if office_id != organization_id:
        created.extend(_audit_window(
            db, office_id, now=now, office_organization_id=office_id,
        ))
    return created


def _audit_window(
    db, organization_id: int, *, now: datetime, office_organization_id: int | None,
) -> list[str]:
    created: list[str] = []
    month_start = _month_start(now)
    month_key = month_start.date().isoformat()[:7]
    month_count = _count_calls(
        db, organization_id=organization_id, office_organization_id=office_organization_id,
        start=month_start, end=now, end_inclusive=True,
    )
    limit = _monthly_request_limit()
    if limit > 0:
        threshold = (limit * 7 + 9) // 10
        if month_count >= threshold and not _has_active_alert(
            db, organization_id, _CAP_ALERT, key_name="month", key=month_key,
        ):
            _raise_alert(
                db,
                organization_id=organization_id,
                alert_type=_CAP_ALERT,
                title="שימוש SUMIT הגיע ל-70% מהתקרה החודשית",
                message=(
                    f"נרשמו {month_count} קריאות החודש מול תקרה של {limit}. "
                    "אין כאן סכומים או מפתחות."
                ),
                meta={
                    "month": month_key,
                    "month_count": month_count,
                    "limit": limit,
                    "threshold": threshold,
                    "scope": "office" if office_organization_id else "org",
                },
            )
            created.append(_CAP_ALERT)

    today = _day_start(now)
    prior_counts = []
    for offset in range(1, 15):
        start = today - timedelta(days=offset)
        end = start + timedelta(days=1)
        prior_counts.append(_count_calls(
            db, organization_id=organization_id, office_organization_id=office_organization_id,
            start=start, end=end, end_inclusive=False,
        ))
    today_count = _count_calls(
        db, organization_id=organization_id, office_organization_id=office_organization_id,
        start=today, end=now, end_inclusive=True,
    )
    median = _median(prior_counts)
    threshold = max(2 * median, 5)
    if today_count >= threshold:
        day_key = today.date().isoformat()
        if not _has_active_alert(db, organization_id, _SPIKE_ALERT, key_name="day", key=day_key):
            _raise_alert(
                db,
                organization_id=organization_id,
                alert_type=_SPIKE_ALERT,
                title="שימוש SUMIT היום חורג מפי 2 מהחציון ולפחות 5 קריאות",
                message=(
                    f"היום {today_count} קריאות, חציון 14 הימים {median:.2f}, "
                    f"סף {threshold:.2f}. אין כאן סכומים או מפתחות."
                ),
                meta={
                    "day": day_key,
                    "today_count": today_count,
                    "median_14d": median,
                    "threshold": threshold,
                    "scope": "office" if office_organization_id else "org",
                },
            )
            created.append(_SPIKE_ALERT)
    return created


def record_sumit_call(
    *,
    organization_id: int | None,
    endpoint: str,
    outcome: str,
    purpose: str | None = None,
    environment_verification: bool = False,
    now: datetime | None = None,
) -> None:
    """Append one ledger row and run the cap/spike audit. Failures are logged.

    A ledger write must not hide the provider result, and it must not itself
    call SUMIT.
    """
    if not isinstance(organization_id, int) or organization_id <= 0:
        return
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    path = (endpoint or "").split("?", 1)[0][:200]
    db = SessionLocal()
    try:
        with db.begin():
            from .sumit_request_budget import resolve_office_organization_id
            office_id = resolve_office_organization_id(db, organization_id)
            db.add(ProviderCallLog(
                provider="sumit",
                organization_id=organization_id,
                office_organization_id=office_id,
                purpose=_purpose(purpose, environment_verification=environment_verification),
                endpoint_class=_endpoint_class(path),
                endpoint=path,
                outcome=outcome if outcome in {"success", "http_error", "error"} else "error",
                at=moment,
            ))
            db.flush()
            audit_sumit_usage(
                db, organization_id, now=moment, office_organization_id=office_id,
            )
    except SQLAlchemyError:
        logger.warning("SUMIT usage ledger write failed", exc_info=True)
    finally:
        db.close()
