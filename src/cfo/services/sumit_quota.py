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

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


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
) -> None:
    """**האיסור המוחלט.** נקרא לפני כל פעולה בתשלום.

    שלושה מצבים חוסמים, וכולם fail-closed:
    - אין מדידה
    - המדידה ישנה מ-26 שעות
    - הניצול הגיע למכסה או עבר אותה
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
