"""W6.1 — ניטור-עצמי: המערכת סופרת את הכשלים של עצמה וחושפת אותם.

עד 21/08 חריגה לא-מטופלת נעלמה ב-stdout של Vercel וה-health החזיר מחרוזת
קבועה. עכשיו: כל 500 נספר במונה יומי עמיד (אותה טבלת מונים אטומית של
תקציבי הבקשות — provider="system"), וה-health בודק DB + revision + מונה.
best-effort בלבד — רישום כשל לעולם לא מפיל בקשה בעצמו.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# תקרת המונה — גדולה מספיק כדי שלעולם לא תחסום ספירה (המונה מודד, לא מגביל).
_ERROR_COUNTER_CAP = 1_000_000_000


def _day_window(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def record_system_error_best_effort(*, path: str = "") -> None:
    """מונה כשל-מערכת אחד (חלון יומי, עמיד, חוצה-שרתים)."""
    try:
        from ..database import SessionLocal
        from .sumit_request_budget import SumitRequestLimiter

        now = datetime.now(timezone.utc)
        db = SessionLocal()
        try:
            with db.begin():
                claimed = SumitRequestLimiter._claim_window(
                    db,
                    scope_key="errors",
                    organization_id=None,
                    window_kind="day",
                    window_start=_day_window(now),
                    limit_value=_ERROR_COUNTER_CAP,
                    now=now,
                    provider="system",
                )
            if not claimed:  # pragma: no cover — תקרה תיאורטית
                logger.warning("system error counter refused a claim")
        finally:
            db.close()
        logger.error("unhandled server error on %s", path)
    except Exception:  # noqa: BLE001
        logger.exception("failed to record system error (best effort)")


def todays_error_count() -> int:
    try:
        from ..database import SessionLocal
        from ..models import ProviderRequestBudget

        now = datetime.now(timezone.utc)
        db = SessionLocal()
        try:
            row = (
                db.query(ProviderRequestBudget.used)
                .filter(
                    ProviderRequestBudget.provider == "system",
                    ProviderRequestBudget.scope_key == "errors",
                    ProviderRequestBudget.window_kind == "day",
                    ProviderRequestBudget.window_start == _day_window(now),
                )
                .first()
            )
            return int(row[0]) if row else 0
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        return -1  # honest-null: לא ידוע ≠ אפס


def health_snapshot() -> dict:
    """בדיקות אמת: DB חי, גרסת סכימה, כשלים היום."""
    from sqlalchemy import text

    from ..database import SessionLocal

    database = "ok"
    revision = None
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            try:
                revision = db.execute(
                    text("SELECT version_num FROM alembic_version"),
                ).scalar()
            except Exception:
                revision = "unknown"
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        database = f"error: {type(exc).__name__}"

    errors_today = todays_error_count()
    status = "healthy"
    if database != "ok":
        status = "unhealthy"
    elif errors_today > 0 or errors_today == -1:
        status = "degraded"
    return {
        "status": status,
        "database": database,
        "alembic_revision": revision or "unknown",
        "errors_today": errors_today,
    }
