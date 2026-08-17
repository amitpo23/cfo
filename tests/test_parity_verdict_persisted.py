"""ההכרעה היומית נשמרת ב-DB של רצף — גם כשהיא "unknown".

**למה זה טסט נפרד (17/08/2026).** הבעלים ביקש workflow יומי ש"הנתונים
נשמרים בבסיס נתונים של רצף". התיקון שהוסיף את הכרעת `unknown`
(`parity_service`) יצר סיכון חדש: `check_and_alert` מטפל ב-`mismatch`
וב-`ok` בלבד, ולכן `unknown` הוא no-op **בהתראות**. אם ההכרעה גם לא
הייתה נשמרת ב-snapshot, התוצאה הייתה ריצה יומית שאינה מותירה שום עקבה —
כלומר הדוח היה נעשה כנה ובו-זמנית בלתי-נמצא.

הנתיב שנבדק כאן: `run_morning_cycle` → `run_daily_close_step` →
`DailySnapshot.parity_status` (עמודה קיימת, `String(20)`, שורה יחידה פר
ארגון-ותאריך). אין צורך במיגרציה — וזה מכוון: פרוד נמצא 6 revisions מאחור,
והוספת revision שביעי הייתה מזיזה את ה-head שסקריפט הפריסה מאמת.

מה שעדיין **אינו** נשמר: המספרים פר-בדיקה (ארבעת האפסים, הפערים). זה
דורש עמודה/טבלה חדשה, כלומר מיגרציה — ולכן הוא נדחה עד שפרוד יגיע ל-head.
"""
from datetime import date, datetime, timedelta

import pytest

from cfo.database import SessionLocal
from cfo.models import DailySnapshot, SyncCheckpoint
from cfo.services import morning_cycle_service, parity_service


AS_OF = date(2026, 8, 17)


@pytest.fixture
def synced_empty_org(fresh_org):
    """ארגון מסונכרן אך ריק — מצב org1/org2 בפועל."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    for source, entity in (
        ("sumit", "invoices"), ("sumit", "bills"),
        ("open_finance", "accounts"), ("open_finance", "bank_transactions"),
    ):
        db.add(SyncCheckpoint(
            organization_id=org_id, source=source, entity_type=entity,
            last_success_at=datetime.utcnow() - timedelta(hours=1),
        ))
    db.commit()
    return org_id


def test_the_unknown_verdict_is_written_to_the_daily_snapshot(synced_empty_org):
    """ריצה שלא הצליחה להשוות דבר חייבת להותיר עקבה מדידה. בלי זה אין
    מגמה, ואי-אפשר לדעת מתי הפער נסגר."""
    db = SessionLocal()

    morning_cycle_service.run_morning_cycle(db, synced_empty_org, AS_OF, force=True)

    snap = db.query(DailySnapshot).filter(
        DailySnapshot.organization_id == synced_empty_org,
        DailySnapshot.snapshot_date == AS_OF,
    ).one_or_none()

    assert snap is not None, "הריצה היומית לא הותירה snapshot בכלל"
    assert snap.parity_status == "unknown", (
        f"ההכרעה נשמרה כ-{snap.parity_status!r} במקום 'unknown' — "
        "ההכרעה הכנה אבדה בדרך ל-DB"
    )


def test_the_column_is_wide_enough_for_the_new_verdict():
    """`parity_status` הוא String(20). 'unknown' באורך 7 — אין צורך
    במיגרציה, וזה מה שמאפשר לתקן בלי להזיז את ה-head שסקריפט הפריסה מאמת."""
    col = DailySnapshot.__table__.columns["parity_status"]

    assert col.type.length >= len("unknown")


def test_the_traffic_light_does_not_show_green_on_an_unknown_verdict(synced_empty_org):
    """הרמזור הוא מה שהבעלים רואה. `unknown` אינו אדום (אין כשל מוכח) —
    אבל אסור לו להיות ירוק, אחרת חזרנו לדוח שאינו מוכיח דבר."""
    db = SessionLocal()

    result = morning_cycle_service.run_morning_cycle(
        db, synced_empty_org, AS_OF, force=True
    )

    assert result["cycle_status"] != "green", (
        f"רמזור ירוק על הכרעת parity={result.get('parity_status')!r}"
    )


def test_the_snapshot_stays_one_row_per_day(synced_empty_org):
    """שער נגדי: הרצה חוזרת מעדכנת ולא מוסיפה שורה. אחרת ריצה שנכשלה
    באמצע והורצה מחדש הייתה מכפילה את היום ומזהמת כל מגמה."""
    db = SessionLocal()

    morning_cycle_service.run_morning_cycle(db, synced_empty_org, AS_OF, force=True)
    morning_cycle_service.run_morning_cycle(db, synced_empty_org, AS_OF, force=True)

    rows = db.query(DailySnapshot).filter(
        DailySnapshot.organization_id == synced_empty_org,
        DailySnapshot.snapshot_date == AS_OF,
    ).count()

    assert rows == 1, f"{rows} שורות לאותו יום"


def test_the_daily_run_makes_no_network_calls():
    """הבעלים אישר קריאות SUMIT **רק במסגרת החינמיות**. ריצה יומית פר
    ארגון שהייתה נוגעת ב-getdetails/getpdf הייתה שורפת מכסה של 50 בתוך
    ימים. השער: המודול אינו מייבא את קליינט SUMIT כלל.

    זהו שער מקור ולא mock — mock היה מוכיח שהקריאה לא יצאה בטסט הזה,
    לא שאין נתיב כזה בקוד.
    """
    import inspect

    source = inspect.getsource(parity_service)

    for forbidden in ("SumitIntegration", "getdetails", "getpdf", "listquotas"):
        assert forbidden not in source, (
            f"parity_service מזכיר {forbidden!r} — הריצה היומית עלולה "
            "לגעת במכסת הפעולות בתשלום"
        )
