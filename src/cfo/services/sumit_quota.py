"""מכסת הפעולות בתשלום של SUMIT — נקראת, לא מנוחשת. איסור מוחלט לעבור.

**הממצא שהוליד את המודול (17/08/2026).** קריאה חינמית אחת ל-
`/website/companies/listquotas/` על תיק עמית פורת (`439924597`) החזירה:

    ActionsBilling / Operations    Usage 0    Quota 50

זו מכסת הפעולות **בתשלום** — `getdetails` ו-`getpdf` נספרות שם.
התקרה הפנימית שהייתה בקוד היא `sumit_enrichment_daily_action_limit = 25`
**ליום לארגון**. אם ה-50 חודשיים, 25/יום הם 750 בחודש — **פי 15**.

כלומר התקרה מעולם לא הייתה תקרה: היא הייתה גדולה מהמכסה עצמה. זה מסביר
את ₪62.23/יום שחויבו ב-17/07 — המערכת חצתה את המכסה הכלולה בתוך יומיים,
וכל קריאה מעבר לה היא חיוב ישיר לאמצעי התשלום של **חברת הלקוח**.

## העיקרון

לא לנחש מכסה. `listquotas` היא קריאה **חינמית** (הוכח בקריאה מאושרת),
ולכן היא נמשכת פעם ביום ונשמרת. התקרה נגזרת מהמדידה.

## honest-null מחמיר — וזו הנקודה שעולה כסף

אין מדידה טרייה ⇒ פעולה בתשלום **נחסמת**. מכסה לא-ידועה אינה מכסה
פנויה, ומדידה מאתמול אינה ראיה למצב היום. תקרה שנפתחת כשאי-אפשר למדוד
היא בדיוק התקרה שנעלמת ברגע שהמערכת לא יציבה.

## מה שהמודול הזה **אינו** יודע

**לאיזו תקופה מתייחסת ה-`Quota`** — יומי, חודשי או מצטבר. ה-API אינו
אומר. לכן ההשוואה כאן היא מול הערך כפי שהוא, ולא מול חישוב יומי: מכסה
של 50 היא 50, ואם היא מתאפסת מדי חודש — הרענון היומי יראה זאת.
"""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.exc import SQLAlchemyError

from ..config import settings
from ..database import SessionLocal
from .sumit_request_budget import (
    SumitRequestBudgetUnavailable,
    SumitRequestLimiter,
    paced_daily_limit,
    _utc_windows,
)


QUOTA_ENDPOINT = "/website/companies/listquotas/"

# השורה שמייצגת פעולות בתשלום. `Obligo` היא מסגרת אשראי ולא מונה
# פעולות; `Mails`/`Storage` אינן עולות פר-קריאה.
_PAID_APPLICATION = "ActionsBilling"
_PAID_STATISTIC = "Operations"

# מדידה ישנה מזו נחשבת לא-קיימת. הרענון יומי, ולכן חלון של 26 שעות
# סובל עיכוב cron בלי לפתוח חלון שבו פועלים על נתון בן יומיים.
MAX_MEASUREMENT_AGE = timedelta(hours=26)

# סף התרעה — כדי שהבעלים יידע **לפני** שנחסם, לא אחרי.
NEAR_LIMIT_RATIO = 0.8


class SumitQuotaError(RuntimeError):
    """בסיס לכשלי מכסה. הבקשה לעולם לא נשלחה."""


class SumitQuotaExhausted(SumitQuotaError):
    """המכסה בתשלום נוצלה. כל פעולה נוספת היא חיוב לחברת הלקוח."""


class SumitQuotaUnknown(SumitQuotaError):
    """אין מדידה טרייה. פעולה בתשלום נחסמת — לא נפתחת."""


@dataclass(frozen=True)
class QuotaSnapshot:
    organization_id: int
    used: int
    limit: int
    measured_at: datetime

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def is_near_limit(self) -> bool:
        if self.limit <= 0:
            return True
        return (self.used / self.limit) >= NEAR_LIMIT_RATIO

    @property
    def age(self) -> timedelta:
        measured = self.measured_at
        if measured.tzinfo is None:
            measured = measured.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - measured

    def as_dict(self) -> dict[str, Any]:
        return {
            "organization_id": self.organization_id,
            "used": self.used,
            "limit": self.limit,
            "remaining": self.remaining,
            "is_near_limit": self.is_near_limit,
            "measured_at": self.measured_at.isoformat(),
            "period": "unknown",  # ה-API אינו מוסר תקופה — לא ננחש
        }


def parse_quota_response(
    payload: Any, *, organization_id: int,
) -> Optional[QuotaSnapshot]:
    """מחלץ את מכסת הפעולות בתשלום מתשובת `listquotas`.

    honest-null: תשובה בלי השורה הרלוונטית, או תשובה פגומה, מחזירה
    `None` — **לא** מכסה פנויה. השורה חייבת להיות `ActionsBilling` +
    `Operations`; `Obligo` היא מסגרת אשראי ולא מונה פעולות, ובלבול
    ביניהן היה מציג מכסה של מאות אלפים במקום 50.
    """
    if not isinstance(payload, dict):
        return None
    rows = payload.get("Data")
    if not isinstance(rows, list):
        return None

    for row in rows:
        if not isinstance(row, dict):
            continue
        if (row.get("ApplicationName") == _PAID_APPLICATION
                and row.get("StatisticName") == _PAID_STATISTIC):
            try:
                used = int(row.get("Usage"))
                limit = int(row.get("Quota"))
            except (TypeError, ValueError):
                return None
            return QuotaSnapshot(
                organization_id=organization_id, used=used, limit=limit,
                measured_at=datetime.now(timezone.utc),
            )
    return None


def assert_paid_action_within_quota(
    snapshot: Optional[QuotaSnapshot], *, endpoint: str,
    claim_budget: bool = True,
) -> None:
    """**האיסור המוחלט.** נקרא לפני כל פעולה בתשלום.

    שלושה מצבים חוסמים, וכולם fail-closed:
    - אין מדידה
    - המדידה ישנה מ-26 שעות
    - הניצול הגיע למכסה או עבר אותה

    `claim_budget=False` — בדיקה טהורה בלבד (שומרי המתודות, שרצים לפני
    שער הרשת): חוסמת מוקדם בלי לתפוס משבצת מהמונה החודשי, כדי שפעולה
    אחת לא תיספר פעמיים.
    """
    if snapshot is None:
        raise SumitQuotaUnknown(
            f"פעולה בתשלום נחסמה ({endpoint}): מכסת SUMIT אינה ידועה. "
            "יש לרענן אותה דרך listquotas (קריאה חינמית) לפני פעולות "
            "בתשלום. מכסה לא-ידועה אינה מכסה פנויה."
        )

    if snapshot.age > MAX_MEASUREMENT_AGE:
        hours = int(snapshot.age.total_seconds() // 3600)
        raise SumitQuotaUnknown(
            f"פעולה בתשלום נחסמה ({endpoint}): מדידת המכסה בת {hours} שעות, "
            f"מעל התקרה של {int(MAX_MEASUREMENT_AGE.total_seconds() // 3600)}. "
            "מדידה ישנה אינה ראיה למצב הנוכחי."
        )

    if snapshot.remaining <= 0:
        raise SumitQuotaExhausted(
            f"פעולה בתשלום נחסמה ({endpoint}): נוצלו {snapshot.used} מתוך "
            f"{snapshot.limit}. כל פעולה נוספת מחויבת לאמצעי התשלום של "
            "חברת הלקוח."
        )

    # P0-A (23/08/2026, ביקורת קודקס): המונה החודשי העמיד לבדו לא הספיק —
    # הוא לא אותחל מ-snapshot.used ולא נחסם ע"י snapshot.remaining, כך
    # שמדידה כמעט-מוצתה מהספק (49/50) עדיין נתנה לו לאשר עד לתקרתו
    # הפנימית (90). כאן נתבע גם מונה "מאז-המדידה" שתקרתו snapshot.remaining
    # — מדידה טרייה **מצמצמת** את מה שהמונה הפנימי ירשה, לעולם לא מגדילה
    # אותו מעבר לתקרה הפנימית.
    if claim_budget:
        _claim_monthly_paid_action(
            organization_id=snapshot.organization_id,
            endpoint=endpoint,
            snapshot=snapshot,
        )


def _claim_monthly_paid_action(
    *, organization_id: int, endpoint: str, snapshot: QuotaSnapshot,
) -> None:
    """ליבת ה-ledger המאוחד: שלוש תביעות עמידות, אטומיות יחד.

    כישלון באחת מבטל את כולן (raise בתוך `with db.begin()`, כמו
    ב-`SumitRequestLimiter.claim`) — לא נשאר מונה חלקית-תפוס.

    1. **since_snapshot** — מפתחה `snapshot.measured_at`, תקרתה
       `snapshot.remaining`. זו סגירת הפער בין מדידת הספק למונה הפנימי:
       מדידה טרייה **מצמצמת** את מה שהמונה ירשה, לעולם לא מגדילה מעבר
       לתקרה הפנימית. כשמתפרסמת מדידה חדשה (`measured_at` אחר) — נפתח
       חלון תביעה טרי אוטומטית.
    2. **month** — התקרה הפנימית העמידה (90 ב-test, לפי קונפיג ב-live).
       קיימת עוד לפני P0-A; כאן היא רק אחת משלוש, לא היחידה.
    3. **day** — קצב יומי הנגזר מהיתרה החודשית (`paced_daily_limit`,
       אותה נוסחה כמו ב-`SumitRequestLimiter.claim`), כדי שיתרה גדולה
       בתחילת החודש לא תישרף ביום אחד ותשאיר את שאר החודש חסום.
    """
    if settings.sumit_environment == "test":
        limit_value = settings.sumit_test_monthly_paid_action_limit
    else:
        limit_value = settings.sumit_live_monthly_paid_action_limit
    now = datetime.now(timezone.utc)
    _, day_start, month_start = _utc_windows(now)
    scope_key = f"paid:org:{organization_id}"
    db = SessionLocal()
    try:
        with db.begin():
            snapshot_claimed = SumitRequestLimiter._claim_window(
                db,
                scope_key=scope_key,
                organization_id=organization_id,
                window_kind="snapshot",
                window_start=snapshot.measured_at,
                limit_value=snapshot.remaining,
                now=now,
            )
            if not snapshot_claimed:
                raise SumitQuotaExhausted(
                    f"פעולה בתשלום נחסמה ({endpoint}): המדידה האחרונה "
                    f"מהספק ({snapshot.used}/{snapshot.limit}) כבר מוצתה "
                    "ע\"י פעולות שנתבעו מאז. מדידה טרייה תפתח יתרה חדשה."
                )
            month_used = SumitRequestLimiter._window_used(
                db, scope_key=scope_key, window_kind="month",
                window_start=month_start,
            )
            day_used = SumitRequestLimiter._window_used(
                db, scope_key=scope_key, window_kind="day",
                window_start=day_start,
            )
            days_in_month = monthrange(now.year, now.month)[1]
            effective_daily = paced_daily_limit(
                configured_daily=limit_value,
                monthly_limit=limit_value,
                month_used=month_used,
                day_used=day_used,
                days_left=days_in_month - now.day + 1,
            )
            month_claimed = SumitRequestLimiter._claim_window(
                db,
                scope_key=scope_key,
                organization_id=organization_id,
                window_kind="month",
                window_start=month_start,
                limit_value=limit_value,
                now=now,
            )
            if not month_claimed:
                raise SumitQuotaExhausted(
                    f"SUMIT monthly paid-action budget exceeded ({endpoint})",
                )
            day_claimed = SumitRequestLimiter._claim_window(
                db,
                scope_key=scope_key,
                organization_id=organization_id,
                window_kind="day",
                window_start=day_start,
                limit_value=effective_daily,
                now=now,
            )
            if not day_claimed:
                raise SumitQuotaExhausted(
                    f"SUMIT daily paid-action pace exceeded ({endpoint})",
                )
    except SumitQuotaError:
        raise
    except (SQLAlchemyError, SumitRequestBudgetUnavailable) as exc:
        raise SumitQuotaUnknown(
            f"SUMIT monthly paid-action usage is unknown ({endpoint}); "
            "the paid action was refused",
        ) from exc
    finally:
        db.close()


# שם היסטורי — קיים כי נקודות קריאה ותיקות (וטסטים) מפנות אליו. ההתנהגות
# זהה: המגבלה נבחרת לפי הסביבה בתוך הפונקציה עצמה.
_claim_test_monthly_paid_action = _claim_monthly_paid_action


# ==================================================================== #
# W2.1 — persistence של המדידה (הרענון היומי כותב, השער קורא)
# ==================================================================== #

def store_measurement(db, snapshot: QuotaSnapshot) -> None:
    """שומר מדידה אחת כפי שנקראה מהספק. commit באחריות הקורא."""
    from ..models import SumitQuotaMeasurement

    db.add(SumitQuotaMeasurement(
        organization_id=snapshot.organization_id,
        environment=settings.sumit_environment,
        used=snapshot.used,
        limit_value=snapshot.limit,
        measured_at=snapshot.measured_at,
    ))


def load_latest_snapshot(db, organization_id: int) -> Optional[QuotaSnapshot]:
    """המדידה הטרייה ביותר לארגון **בסביבה הנוכחית** — או `None`.

    מדידת test אינה ראיה למכסת live ולהפך, ולכן הסינון לפי הסביבה
    הפעילה. בדיקת הטריות (26h) נעשית ב-`assert_paid_action_within_quota`
    — כאן מוחזרת המדידה כמו שהיא.
    """
    from ..models import SumitQuotaMeasurement

    row = (
        db.query(SumitQuotaMeasurement)
        .filter(
            SumitQuotaMeasurement.organization_id == organization_id,
            SumitQuotaMeasurement.environment == settings.sumit_environment,
        )
        .order_by(SumitQuotaMeasurement.measured_at.desc())
        .first()
    )
    if row is None:
        return None
    measured = row.measured_at
    if measured.tzinfo is None:
        measured = measured.replace(tzinfo=timezone.utc)
    return QuotaSnapshot(
        organization_id=row.organization_id,
        used=row.used,
        limit=row.limit_value,
        measured_at=measured,
    )


async def refresh_quota_measurement(db, organization_id: int, integration):
    """מרענן את המדידה מ-`listquotas` (קריאה חינמית) ושומר אותה.

    honest-null: תשובה בלי השורה הרלוונטית אינה נשמרת — עדיף חוסם-אמת
    מאשר מדידה מזויפת. מחזיר את ה-snapshot או `None`.
    """
    payload = await integration._make_request(QUOTA_ENDPOINT, data={})
    snapshot = parse_quota_response(payload, organization_id=organization_id)
    if snapshot is None:
        return None
    store_measurement(db, snapshot)
    if snapshot.is_near_limit:
        _record_near_limit_insight(db, snapshot)
    db.commit()
    return snapshot


def _record_near_limit_insight(db, snapshot: QuotaSnapshot) -> None:
    """W2.5 — הצרכן של `NEAR_LIMIT_RATIO`: הבעלים יודע לפני החסימה.

    ההתרעה נכתבת כ-CfoInsight (עולה בבריף הבוקר ובהתרעות הערוץ),
    עם fingerprint פר-חודש כדי שלא תשוכפל בכל רענון יומי.
    """
    from ..models import CfoInsight

    now = datetime.now(timezone.utc)
    fingerprint = (
        f"sumit_quota_near_limit:{snapshot.organization_id}:{now:%Y-%m}"
    )
    existing = db.query(CfoInsight).filter(
        CfoInsight.organization_id == snapshot.organization_id,
        CfoInsight.fingerprint == fingerprint,
    ).first()
    severity = "critical" if snapshot.remaining <= 0 else "high"
    title = (
        f"מכסת הפעולות בתשלום של SUMIT ב-{int(snapshot.used / max(1, snapshot.limit) * 100)}% "
        f"({snapshot.used}/{snapshot.limit})"
    )
    message = (
        "מעבר למכסה — כל פעולה מחויבת לאמצעי התשלום של חברת הלקוח. "
        "פעולות בתשלום ייחסמו אוטומטית במיצוי."
    )
    if existing is not None:
        existing.severity = severity
        existing.title = title
        existing.evidence = snapshot.as_dict()
        existing.status = "active"
    else:
        db.add(CfoInsight(
            organization_id=snapshot.organization_id,
            fingerprint=fingerprint,
            insight_type="sumit_quota_near_limit",
            severity=severity,
            title=title,
            message=message,
            evidence=snapshot.as_dict(),
            recommended_action="לבדוק מה צורך פעולות בתשלום החודש; להעלות מכסה מול SUMIT או להמתין לאיפוס.",
        ))
