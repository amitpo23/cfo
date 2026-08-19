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


QUOTA_CHECKPOINT_ENTITY = "quota_check"


def store_quota_snapshot(db, organization_id: int, snapshot: QuotaSnapshot) -> None:
    """שומר מדידת מכסה ל-`SyncCheckpoint` הקיים — בלי טבלה/מיגרציה חדשה.

    `entity_type="quota_check"` הוא שורת-סנטינל פר-ארגון (אותו דפוס
    שהתיעוד של SyncCheckpoint כבר מתאר ל-`__source__`); ה-JSON נכנס
    ל-`cursor` (String(500) — בהרבה מעבר למה שנדרש כאן). כתיבה חוזרת
    דורסת את השורה הקיימת (UniqueConstraint על org+source+entity_type),
    לא מצטברת.
    """
    import json

    from ..models import SyncCheckpoint

    row = db.query(SyncCheckpoint).filter(
        SyncCheckpoint.organization_id == organization_id,
        SyncCheckpoint.source == "sumit",
        SyncCheckpoint.entity_type == QUOTA_CHECKPOINT_ENTITY,
    ).first()
    if row is None:
        row = SyncCheckpoint(
            organization_id=organization_id, source="sumit",
            entity_type=QUOTA_CHECKPOINT_ENTITY,
        )
        db.add(row)
    row.cursor = json.dumps({
        "used": snapshot.used,
        "limit": snapshot.limit,
        "measured_at": snapshot.measured_at.isoformat(),
    })
    row.last_success_at = datetime.now(timezone.utc)
    db.commit()


def load_quota_snapshot(db, organization_id: int) -> Optional[QuotaSnapshot]:
    """טוען את המדידה האחרונה שנשמרה. honest-null: שום שורה/JSON לא-תקין
    ⇒ `None` — לא מכסה מומצאת, ולא מכסה 'פנויה' כברירת מחדל."""
    import json

    from ..models import SyncCheckpoint

    row = db.query(SyncCheckpoint).filter(
        SyncCheckpoint.organization_id == organization_id,
        SyncCheckpoint.source == "sumit",
        SyncCheckpoint.entity_type == QUOTA_CHECKPOINT_ENTITY,
    ).first()
    if row is None or not row.cursor:
        return None
    try:
        payload = json.loads(row.cursor)
        measured_at = datetime.fromisoformat(payload["measured_at"])
        return QuotaSnapshot(
            organization_id=organization_id,
            used=int(payload["used"]),
            limit=int(payload["limit"]),
            measured_at=measured_at,
        )
    except (TypeError, ValueError, KeyError):
        return None


async def refresh_quota_snapshot_for_org(
    db, organization_id: int, *, api_key: str, company_id: Optional[str],
) -> dict[str, Any]:
    """קורא `listquotas` (חינמי — ר' docs/SUMIT_API_REFERENCE.md; **אין
    תיעוד רשמי לעלות/הגבלה על הקריאה עצמה**, רק קריאה מאושרת בודדת
    ב-17/08/2026) ושומר תוצאה. עוברת דרך אותו צוואר-בקבוק כמו כל קריאת
    SUMIT אחרת (`request_limiter` אמיתי, נאכף fail-closed ברגע הרשת) —
    אין כאן פטור. תדירות הקריאה (פעם ביום לארגון) נאכפת ע"י הקורא
    (cron), לא כאן.

    honest-null: תשובה בלי שורת ActionsBilling/Operations תקינה לא
    נשמרת ולא ממציאה מכסה — ר' `parse_quota_response`.
    """
    from ..integrations.sumit_integration import SumitIntegration
    from .sumit_request_budget import SumitRequestLimiter

    client = SumitIntegration(
        api_key=api_key, company_id=company_id,
        request_limiter=SumitRequestLimiter(organization_id),
    )
    async with client:
        payload = await client.list_quotas()

    snapshot = parse_quota_response(payload, organization_id=organization_id)
    if snapshot is None:
        return {"organization_id": organization_id, "stored": False,
                "reason": "malformed_or_missing_quota_row"}

    store_quota_snapshot(db, organization_id, snapshot)
    return {"organization_id": organization_id, "stored": True,
            "used": snapshot.used, "limit": snapshot.limit}


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
