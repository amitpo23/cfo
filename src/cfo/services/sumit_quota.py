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
    _db_now,
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

# P0-A תיקון 2 (סקירת קודקס 23/08): מדידה עם measured_at עתידי (שעון
# instance שגוי, או frozen future מבחינה) מחשבת age שלילי — שלילי הוא
# תמיד קטן מ-MAX_MEASUREMENT_AGE, כלומר הייתה עוברת כ"טרייה" בלי קשר
# לכמה רחוק בעתיד. סובלנות קטנה (jitter/ניקוד-שעון סביר בין instances),
# לא אפס — כדי לא לחסום מדידה אמיתית שנרשמה מילישניות לפני שהזמן
# הקנוני של הקורא "התקדם".
MAX_FUTURE_SKEW = timedelta(minutes=5)

# סף התרעה — כדי שהבעלים יידע **לפני** שנחסם, לא אחרי.
NEAR_LIMIT_RATIO = 0.8

# שורת תיאום יציבה לארגון. היא אינה תקציב (used=limit=0); תפקידה היחיד
# לסדר claim ורענון-דור באותה נעילת DB עד commit.
_GENERATION_LOCK_START = datetime(1970, 1, 1, tzinfo=timezone.utc)


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
    claim_budget: bool = True, now: Optional[datetime] = None,
) -> None:
    """**האיסור המוחלט.** נקרא לפני כל פעולה בתשלום.

    ארבעה מצבים חוסמים, וכולם fail-closed:
    - אין מדידה
    - המדידה מתוארכת לעתיד (מעבר לסבילות קטנה — ראו MAX_FUTURE_SKEW)
    - המדידה ישנה מ-26 שעות
    - הניצול הגיע למכסה או עבר אותה

    `now` — P0-A תיקון 2 (סקירת קודקס 23/08): זמן קנוני, רצוי מה-DB
    (`_db_now`) ולא משעון-התהליך — קורא-הייצור (`sumit_integration.py`)
    מעביר אותו במפורש. ברירת המחדל (`None` → שעון-התהליך) נשמרת
    לתאימות לאחור עם טסטים טהורים שבונים snapshot בעצמם בלי DB.

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

    effective_now = now if now is not None else datetime.now(timezone.utc)
    measured = snapshot.measured_at
    if measured.tzinfo is None:
        measured = measured.replace(tzinfo=timezone.utc)

    if measured - effective_now > MAX_FUTURE_SKEW:
        raise SumitQuotaUnknown(
            f"פעולה בתשלום נחסמה ({endpoint}): מדידת המכסה מתוארכת לעתיד "
            f"({measured.isoformat()} מול {effective_now.isoformat()}). "
            "פער-שעון או מדידה לא-אמינה — לא ראיה למצב הנוכחי."
        )

    age = effective_now - measured
    if age > MAX_MEASUREMENT_AGE:
        hours = int(age.total_seconds() // 3600)
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
       חלון תביעה טרי אוטומטית. (מרוץ-הדורות בין תביעה למדידה הבאה
       נסגר בנפרד ב-`_reconcile_generation`, הנקראת מ-`refresh_quota_measurement`.)
    2. **month** — התקרה הפנימית העמידה (90 ב-test, לפי קונפיג ב-live).
       קיימת עוד לפני P0-A; כאן היא רק אחת משלוש, לא היחידה.
    3. **day** — קצב יומי הנגזר מהיתרה **האפקטיבית** — min(יתרת-הספק,
       יתרה-פנימית), לא מהתקרה הפנימית בלבד (P0-A תיקון 5) —
       `paced_daily_limit(provider_remaining=...)`, כדי שיתרה חודשית
       גדולה לא תישרף ביום אחד, וגם כדי שיתרת-ספק זעירה תיחסם כמעט
       מיד ולא תיפרס על פני "יום גדול" לפי התקרה הפנימית בלבד.

    זמן החלונות נשאב תמיד מה-DB בתוך אותה טרנזקציה. גם זמן שסופק לבדיקה
    המוקדמת של snapshot אינו רשאי לעקוף כשל DB במסלול ה-claim.
    """
    if settings.sumit_environment == "test":
        limit_value = settings.sumit_test_monthly_paid_action_limit
    else:
        limit_value = settings.sumit_live_monthly_paid_action_limit
    scope_key = f"paid:org:{organization_id}"
    db = SessionLocal()
    try:
        with db.begin():
            canonical_now = _db_now(db)
            _lock_paid_generation(
                db, organization_id=organization_id, now=canonical_now,
            )
            # claim עשוי היה לטעון snapshot רגע לפני שרענון מקביל פרסם
            # דור חדש. הנעילה למעלה מסדרת את שני הצדדים; הבדיקה אחרי
            # קבלתה מונעת מ-claim ישן להירשם בדור שכבר הותאם ונחתם.
            latest = load_latest_snapshot(db, organization_id)
            if latest is not None:
                latest_at = latest.measured_at
                snapshot_at = snapshot.measured_at
                if latest_at.tzinfo is None:
                    latest_at = latest_at.replace(tzinfo=timezone.utc)
                if snapshot_at.tzinfo is None:
                    snapshot_at = snapshot_at.replace(tzinfo=timezone.utc)
                if latest_at > snapshot_at:
                    raise SumitQuotaUnknown(
                        f"SUMIT paid action refused ({endpoint}): a newer quota "
                        "measurement was published while this claim was starting",
                    )
            _, day_start, month_start = _utc_windows(canonical_now)
            snapshot_claimed = SumitRequestLimiter._claim_window(
                db,
                scope_key=scope_key,
                organization_id=organization_id,
                window_kind="snapshot",
                window_start=snapshot.measured_at,
                limit_value=snapshot.remaining,
                now=canonical_now,
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
            days_in_month = monthrange(canonical_now.year, canonical_now.month)[1]
            effective_daily = paced_daily_limit(
                configured_daily=limit_value,
                monthly_limit=limit_value,
                month_used=month_used,
                day_used=day_used,
                days_left=days_in_month - canonical_now.day + 1,
                provider_remaining=snapshot.remaining,
            )
            month_claimed = SumitRequestLimiter._claim_window(
                db,
                scope_key=scope_key,
                organization_id=organization_id,
                window_kind="month",
                window_start=month_start,
                limit_value=limit_value,
                now=canonical_now,
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
                now=canonical_now,
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


def _lock_paid_generation(db, *, organization_id: int, now: datetime) -> None:
    """Serialize paid claims and quota refresh for one organization."""
    SumitRequestLimiter._lock_window(
        db,
        scope_key=f"paid:org:{organization_id}",
        organization_id=organization_id,
        window_kind="generation_lock",
        window_start=_GENERATION_LOCK_START,
        now=now,
    )


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
    # אותה שורת coordination ננעלת גם ב-claim. לכן claim שקדם לנעילה
    # ייכלל ב-prior_claimed, ו-claim שהמתין אחריה יראה את הדור החדש
    # וייחסם כ-stale — אין חלון בין הקריאה ל-commit שבו תביעה יכולה להישמט.
    canonical_now = _db_now(db)
    _lock_paid_generation(
        db, organization_id=organization_id, now=canonical_now,
    )
    previous = load_latest_snapshot(db, organization_id)
    store_measurement(db, snapshot)
    _reconcile_generation(db, previous=previous, new=snapshot)
    if snapshot.is_near_limit:
        _record_near_limit_insight(db, snapshot)
    db.commit()
    return snapshot


# ==================================================================== #
# P0-A תיקונים 1+3 (סקירת קודקס 23/08/2026) — התאמה בין דורות מדידה
# ==================================================================== #

def _reconcile_generation(
    db, *, previous: Optional[QuotaSnapshot], new: QuotaSnapshot,
) -> None:
    """נקרא פעם אחת בכל רענון מכסה, אחרי ש-`new` נשמר. שני תיקונים
    בלתי-תלויים, מאותם שני מספרים:

    **תיקון 1 — מרוץ-דורות.** כל `measured_at` פותח חלון `since_snapshot`
    טרי משלו (תקרתו `remaining` של המדידה ההיא). בלי זה: תביעה שהוענקה
    תחת הדור הישן (`previous`) ועדיין לא באה לידי ביטוי ב-`Usage` של
    המדידה החדשה (עדיין אותו 49/50 — הספק פשוט עוד לא עדכן) הייתה
    יכולה להיספר שוב תחת הדור החדש (עוד +1 remaining) — 51/50 אפשרי.
    שמרני: כל תביעה מהדור הקודם שלא **הוכחה** נספגת (עלייה מקבילה
    ב-Usage האמיתי) נזרעת כרצפת-`used` בחלון של הדור החדש, לפני
    שהוא נפתח לתביעות חדשות.

    **תיקון 3 — הסגר inferred.** אם ה-delta האמיתי ב-Usage גדול ממה
    שהתביעות שלנו מסבירות — משהו צורך מכסה בלי לעבור בשער-התשלום.
    ההסבר הסביר ביותר: אחד מ-endpoints ה-'inferred' ב-FREE_ENDPOINTS
    הוא בעצם paid. תגובה: הסגר מיידי (לא רק התרעת 80%) לכל שכבת
    ה-inferred, עד שחרור ידני של הבעלים.
    """
    if previous is None:
        return
    scope_key = f"paid:org:{new.organization_id}"
    prior_claimed = SumitRequestLimiter._window_used(
        db, scope_key=scope_key, window_kind="snapshot",
        window_start=previous.measured_at,
    )
    # ירידת Usage (איפוס תקופה אצל הספק) אינה הוכחה שהתביעות "נספגו" —
    # honest-null: 0 מוכח-נספג, לא הכול-מאופס.
    provider_delta = max(0, new.used - previous.used)

    # **לא** "return מוקדם אם prior_claimed<=0": דווקא התרחיש הכי מסוכן
    # של תיקון 3 הוא prior_claimed==0 — אפס תביעות שלנו, ובכל זאת
    # ה-Usage אצל הספק עלה. return מוקדם כאן היה מדלג בדיוק על ההסגר
    # שאמור לתפוס את זה.
    if prior_claimed > 0:
        confirmed = min(prior_claimed, provider_delta)
        carry = prior_claimed - confirmed
        if carry > 0:
            now = _db_now(db)
            seeded = min(carry, max(0, new.remaining))
            SumitRequestLimiter._seed_window_floor(
                db,
                scope_key=scope_key,
                organization_id=new.organization_id,
                window_kind="snapshot",
                window_start=new.measured_at,
                used=seeded,
                limit_value=max(0, new.remaining),
                now=now,
            )

    unexplained = provider_delta - prior_claimed
    if unexplained > settings.sumit_unexplained_quota_delta_threshold:
        _trigger_inferred_endpoint_quarantine(
            db,
            organization_id=new.organization_id,
            environment=settings.sumit_environment,
            unexplained_delta=unexplained,
            evidence={
                "previous_measured_at": previous.measured_at.isoformat(),
                "previous_used": previous.used,
                "new_measured_at": new.measured_at.isoformat(),
                "new_used": new.used,
                "provider_delta": provider_delta,
                "claimed_by_us_since_previous": prior_claimed,
                "unexplained_delta": unexplained,
                "threshold": settings.sumit_unexplained_quota_delta_threshold,
            },
        )


def _quarantine_fingerprint(organization_id: int, environment: str) -> str:
    # בלי חותמת-זמן/חודש בכוונה: ההסגר לא "מתאפס" מדי חודש כמו התרעת
    # near-limit — הוא נשאר עד ניקוי ידני, ולכן אותו fingerprint לצמיתות.
    return f"sumit_inferred_endpoint_quarantine:{organization_id}:{environment}"


def _trigger_inferred_endpoint_quarantine(
    db, *, organization_id: int, environment: str,
    unexplained_delta: int, evidence: dict,
) -> None:
    """יוצר/מעדכן CfoInsight שהוא **גם** דגל ההסגר עצמו (נבדק חי ע"י
    `is_inferred_endpoint_quarantined`) — לא רק התרעה. status != 'resolved'
    ⇒ הסגר פעיל. שחרור רק דרך עדכון סטטוס ידני (מסלולי ה-insights
    הקיימים, `PATCH /brain/insights/{id}` או `/insights/{id}/status`)."""
    from ..models import CfoInsight

    fingerprint = _quarantine_fingerprint(organization_id, environment)
    existing = db.query(CfoInsight).filter(
        CfoInsight.organization_id == organization_id,
        CfoInsight.fingerprint == fingerprint,
    ).first()
    title = f"הסגר אוטומטי: פער בלתי-מוסבר במכסת SUMIT ({unexplained_delta} פעולות)"
    message = (
        "מדידת המכסה הראתה עלייה בשימוש שלא הוסברה ע\"י פעולות שהמערכת "
        "עצמה תבעה דרך שער-התשלום. כל endpoint ב-FREE_ENDPOINTS מהדרגה "
        "'inferred' (לא 'verified free'/'bootstrap') עבר לשער הפעולות-"
        "בתשלום עד שחרור ידני — אחרי שאותרה סיבת הפער."
    )
    recommended_action = (
        "לבדוק את הראיות (evidence) — אילו endpoints נקראו בחלון הזמן "
        "שבין שתי המדידות; לאשש שאף inferred endpoint אינו בעצם paid "
        "לפני שחרור ההסגר."
    )
    if existing is not None:
        # 'resolved' → הבעלים שחרר בעבר; פער בלתי-מוסבר **חדש** פותח
        # הסגר מחדש (fail-closed: לא משאירים 'קלירד לצמיתות' מול איתות
        # אמיתי חדש) — activated_at מתעדכן, לא רק evidence.
        existing.status = "active"
        existing.severity = "critical"
        existing.title = title
        existing.message = message
        existing.evidence = evidence
        existing.recommended_action = recommended_action
        existing.resolved_at = None
    else:
        db.add(CfoInsight(
            organization_id=organization_id,
            fingerprint=fingerprint,
            insight_type="sumit_inferred_endpoint_quarantine",
            severity="critical",
            title=title,
            message=message,
            evidence=evidence,
            recommended_action=recommended_action,
        ))


def is_inferred_endpoint_quarantined(
    db, *, organization_id: int, environment: str,
) -> bool:
    """נקרא משער הרשת (`sumit_integration.py`) לפני שנותנים ל-endpoint
    'inferred free' לעבור בלי שער-תשלום. `True` = הסגר פעיל."""
    from ..models import CfoInsight

    fingerprint = _quarantine_fingerprint(organization_id, environment)
    row = db.query(CfoInsight).filter(
        CfoInsight.organization_id == organization_id,
        CfoInsight.fingerprint == fingerprint,
        CfoInsight.status != "resolved",
    ).first()
    return row is not None


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
