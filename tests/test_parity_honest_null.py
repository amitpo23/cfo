"""התאמה יומית לא מכריזה "ok" על נתונים ריקים.

**הממצא שהוליד את הקובץ (17/08/2026).** הבעלים ביקש "צ'ק ליסט אמיתי
ו-workflow שממפה את רצף וסאמיט והבנק בצורה מושלמת". ה-workflow קיים ורץ
(`/api/cron/bookkeeper-morning` ב-03:45 → `morning_cycle_service._step_parity`
→ `parity_service.check_and_alert`) — אבל שלוש עובדות שנמדדו קודם מפרקות
את המשמעות שלו:

- `build_journal` קורא `Invoice`/`Bill`/`Expense`/`Payment` ו**אינו** קורא
  `JournalEntry`. 15,060 הפקודות של org5 אינן בשימוש.
- ל-org1 ול-org2 יש **0** פקודות יומן.
- שני הארגונים מחזירים **7 כרטיסים גנריים** בלבד.

כלומר שתי הבדיקות הכבדות — `_check_internal_double_computation`
(רצף מול עצמו) ו-`_check_sumit_crosscheck` — מקבלות אפסים בשני הצדדים.
אפס פחות אפס הוא אפס, אפס ≤ הסבילות, ולכן הן מחזירות `ok`.

**דוח ירוק שאינו מוכיח דבר גרוע מהיעדר דוח.** הוא סוגר התראות
(`check_and_alert` עושה resolve על `status == "ok"`) על בסיס שתיקה. זו
אותה תבנית fail-open שתוקנה ב-`spent_today=None → Decimal("0")` וב-
`parse_quota_response` שמחזירה `None` ולא מכסה פנויה.

**הכלל שנאכף כאן:** אין נתונים להשוות ⇒ הכרעה `unknown`, לא `ok`.
"unknown" אינו כשל ואינו מתריע — אבל הוא גם **אינו סוגר** התראה קיימת,
בדיוק כמו `authoritative=False`.
"""
from datetime import date

import pytest

from cfo.database import SessionLocal
from cfo.services import parity_service


AS_OF = date(2026, 8, 17)


@pytest.fixture
def empty_org_id(fresh_org):
    """ארגון בלי פקודות יומן, בלי מסמכים ובלי אינדקס — מצב org1/org2 בפועל.

    `fresh_org` (ולא ה-org המשותף) הוא הכרחי כאן: הבדיקה מתבססת על כך
    שהצדדים **ריקים**, וארגון משותף בין קבצים היה נגוע במסמכים של טסטים
    אחרים ומאבד את המשמעות.
    """
    return fresh_org()["org_id"]


# ==================================================================== #
# החישוב הכפול הפנימי
# ==================================================================== #
def test_internal_double_computation_on_empty_data_is_not_ok(empty_org_id):
    """אפס מול אפס אינו הוכחת עקביות.

    זו הבדיקה שאמורה לתפוס טעות חישוב ברצף. על ארגון בלי נתונים היא
    משווה 0 ל-0 ומחזירה "ok" — ומדווחת הצלחה על כך שלא בדקה כלום.
    """
    db = SessionLocal()
    result = parity_service._check_internal_double_computation(
        db, empty_org_id, AS_OF
    )

    assert result["status"] != "ok", (
        "הבדיקה הכריזה 'ok' על ארגון בלי שום נתון. "
        f"revenue={result.get('cumulative_pl_revenue')} "
        f"expense={result.get('cumulative_pl_expense')}"
    )
    assert result["status"] == "unknown"


def test_the_unknown_verdict_says_why_in_hebrew(empty_org_id):
    """מי שקורא את הדוח חייב להבין שלא נבדק כלום — אחרת הוא יקרא 'unknown'
    כתקלה טכנית ויתעלם."""
    db = SessionLocal()
    result = parity_service._check_internal_double_computation(
        db, empty_org_id, AS_OF
    )

    assert result["details_he"], "הכרעת unknown בלי הסבר"
    assert "אין" in result["details_he"] or "ריק" in result["details_he"]


# ==================================================================== #
# ההכרעה הכוללת
# ==================================================================== #
def test_the_daily_run_does_not_report_ok_for_an_empty_org(empty_org_id):
    """ההכרעה הכוללת היא מה שמושקו והבעלים רואים. אסור לה להיות ירוקה
    כשאף בדיקה סמכותית לא הצליחה להשוות דבר."""
    db = SessionLocal()
    result = parity_service.run_daily_parity(db, empty_org_id, AS_OF)

    assert result["status"] != "ok", (
        "ריצה יומית ירוקה על ארגון ריק. זהו fail-open: "
        + "; ".join(f"{c['name']}={c['status']}" for c in result["checks"])
    )


def test_a_synced_but_empty_org_is_still_not_green(empty_org_id):
    """**זהו התרחיש בפרוד, וזה הטסט שהכי חשוב כאן.**

    בטסט הקודם ההכרעה הכוללת נצלה במקרה: אין `SyncCheckpoint`, ולכן
    הטריות דיווחה "stale" והורידה את הכולל. אבל org1/org2 **כן**
    מסתנכרנים כל יום (`/api/cron/sync-sumit` ב-01:30, `sync-open-finance`
    ב-02:00) — כלומר הטריות שלהם ירוקה.

    ברגע שהטריות ירוקה, שום דבר לא מונע מהריצה היומית להכריז "ok" על
    ארגון שאין בו מה להשוות. זה בדיוק הדוח הירוק-לשווא שמאמן להתעלם,
    והוא מה שהבעלים היה רואה כל בוקר ב-03:45.
    """
    from cfo.models import SyncCheckpoint
    from datetime import datetime, timedelta

    db = SessionLocal()
    for source, entity in (
        ("sumit", "invoices"), ("sumit", "bills"),
        ("open_finance", "accounts"), ("open_finance", "bank_transactions"),
    ):
        db.add(SyncCheckpoint(
            organization_id=empty_org_id, source=source, entity_type=entity,
            last_success_at=datetime.utcnow() - timedelta(hours=1),
        ))
    db.commit()

    result = parity_service.run_daily_parity(db, empty_org_id, AS_OF)

    assert result["status"] != "ok", (
        "ריצה יומית ירוקה על ארגון מסונכרן אך ריק — דוח שאינו מוכיח דבר: "
        + "; ".join(f"{c['name']}={c['status']}" for c in result["checks"])
    )


def test_an_unknown_check_never_resolves_an_existing_alert(empty_org_id):
    """הנזק הממשי של fail-open: הכרעה שאינה מבוססת **סוגרת** התראה
    אמיתית. אותו כלל כמו authoritative=False — unknown הוא no-op גמור."""
    db = SessionLocal()
    from cfo.models import CfoInsight

    stale_alert = CfoInsight(
        organization_id=empty_org_id,
        fingerprint=f"parity:internal_double_computation:{AS_OF.strftime('%Y-%m')}",
        insight_type=parity_service.INSIGHT_TYPE,
        severity="high",
        title="אי-התאמה שנמצאה בעבר",
        message="פער אמיתי שדווח קודם",
        status="active",
    )
    db.add(stale_alert)
    db.commit()
    alert_id = stale_alert.id

    parity_service.check_and_alert(db, empty_org_id, AS_OF)

    db.refresh(stale_alert)
    assert stale_alert.status == "active", (
        f"התראה {alert_id} נסגרה על בסיס בדיקה שלא היה לה מה להשוות"
    )


def test_unknown_does_not_raise_a_new_alert_either(empty_org_id):
    """שער נגדי: unknown אינו כשל. אם הוא היה מתריע, כל ארגון חדש היה
    מייצר התראת high ביום הראשון שלו — רעש שמאמן להתעלם."""
    db = SessionLocal()
    result = parity_service.check_and_alert(db, empty_org_id, AS_OF)

    unknown_names = {
        c["name"] for c in result["checks"] if c["status"] == "unknown"
    }
    alerted_names = {a["check"] for a in result["alerted"]}

    assert not (unknown_names & alerted_names), (
        f"בדיקות unknown יצרו התראה: {unknown_names & alerted_names}"
    )
