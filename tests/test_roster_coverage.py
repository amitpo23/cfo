"""בקרת כיסוי הלולאה: ארגון לא נושר מהסנכרון בשקט.

הרקע (אודיט פרוד 05/08/2026): ל-org 2 היה `integration_connections.status =
'paused'` מ-17/07 ול-org 3 `'inactive'` מ-06/07. `scheduled_sync_sumit` מסנן
`status == 'active'` ו-`roster_sync_targets` קורא ל-`active_sources()` שדורש
אותו דבר — כך ששני הארגונים נשמטו מה-cron היומי בלי שגיאה ובלי התרעה. הם
פשוט הפסיקו להסתנכרן, ואיש לא ידע במשך שבועות.
"""
from datetime import datetime, timedelta, timezone

import pytest

from cfo.models import (
    IntegrationConnection,
    Organization,
    SumitCompany,
    SyncRun,
    SyncStatus,
)
from cfo.services.roster_coverage import (
    STALE_AFTER_HOURS,
    ZOMBIE_AFTER_HOURS,
    coverage_alert_lines,
    roster_coverage_report,
)


ORG_IDS = (101, 102, 103, 104)


def _purge(db):
    """ה-DB של הבדיקות משותף למודול — מנקים לפני ואחרי כל בדיקה."""
    from cfo.models import Expense, Invoice

    db.query(Expense).filter(Expense.organization_id.in_(ORG_IDS)).delete(
        synchronize_session=False)
    db.query(Invoice).filter(Invoice.organization_id.in_(ORG_IDS)).delete(
        synchronize_session=False)
    db.query(SyncRun).filter(SyncRun.organization_id.in_(ORG_IDS)).delete(
        synchronize_session=False)
    db.query(IntegrationConnection).filter(
        IntegrationConnection.organization_id.in_(ORG_IDS)).delete(
        synchronize_session=False)
    db.query(SumitCompany).filter(
        SumitCompany.target_organization_id.in_(ORG_IDS)).delete(
        synchronize_session=False)
    db.query(Organization).filter(Organization.id.in_(ORG_IDS)).delete(
        synchronize_session=False)
    db.commit()


@pytest.fixture
def seeded(client):
    """משרד עם ארבעה תיקים במצבים שונים — כמו בפרוד."""
    from cfo.database import SessionLocal

    db = SessionLocal()
    _purge(db)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    orgs = {}
    for oid, name in [(101, "בריא"), (102, "מושהה"), (103, "מנותק"), (104, "מיושן")]:
        o = Organization(id=oid, name=name, is_active=True)
        db.add(o)
        orgs[oid] = o
    db.flush()

    for oid in orgs:
        db.add(SumitCompany(
            office_organization_id=1, company_id=f"C{oid}", name=orgs[oid].name,
            target_organization_id=oid, status="active",
        ))

    db.add(IntegrationConnection(organization_id=101, source="sumit", status="active"))
    db.add(IntegrationConnection(organization_id=102, source="sumit", status="paused"))
    db.add(IntegrationConnection(organization_id=103, source="sumit", status="inactive"))
    db.add(IntegrationConnection(organization_id=104, source="sumit", status="active"))

    # 101 סונכרן עכשיו; 104 פעיל אבל הסנכרון האחרון שלו עתיק.
    db.add(SyncRun(organization_id=101, source="sumit", status=SyncStatus.COMPLETED,
                   started_at=now - timedelta(minutes=10),
                   finished_at=now - timedelta(minutes=9)))
    db.add(SyncRun(organization_id=104, source="sumit", status=SyncStatus.COMPLETED,
                   started_at=now - timedelta(hours=STALE_AFTER_HOURS + 24),
                   finished_at=now - timedelta(hours=STALE_AFTER_HOURS + 24)))
    db.commit()
    yield db
    _purge(db)
    db.close()


def _by_org(report):
    return {r["organization_id"]: r for r in report["clients"]}


def test_healthy_client_reports_ok(seeded):
    rows = _by_org(roster_coverage_report(seeded))
    assert rows[101]["verdict"] == "ok"
    assert rows[101]["issues"] == []


def test_paused_connection_is_reported_not_silently_dropped(seeded):
    """הכשל שקרה בפועל ל-org 2."""
    rows = _by_org(roster_coverage_report(seeded))
    assert rows[102]["verdict"] == "disconnected"
    assert "sumit:paused" in rows[102]["connection_statuses"]
    assert any("paused" in i for i in rows[102]["issues"])


def test_inactive_connection_is_reported(seeded):
    """הכשל שקרה בפועל ל-org 3."""
    rows = _by_org(roster_coverage_report(seeded))
    assert rows[103]["verdict"] == "disconnected"
    assert any("inactive" in i for i in rows[103]["issues"])


def test_active_but_stale_sync_is_reported(seeded):
    rows = _by_org(roster_coverage_report(seeded))
    assert rows[104]["verdict"] == "stale"
    assert rows[104]["hours_since_last_ok"] > STALE_AFTER_HOURS


def test_report_summary_counts_problems(seeded):
    """הדוח גלובלי לכל המשרד, ומודולי בדיקה אחרים משאירים רשומות פנקס
    ב-DB המשותף — לכן מודדים את ארגוני הבדיקה בלבד."""
    report = roster_coverage_report(seeded)
    rows = _by_org(report)
    mine = [rows[o] for o in ORG_IDS if o in rows]

    assert len(mine) == 4
    verdicts = [r["verdict"] for r in mine]
    assert verdicts.count("ok") == 1
    assert verdicts.count("disconnected") == 2
    assert verdicts.count("stale") == 1
    assert report["healthy"] is False
    assert report["summary"]["total"] >= 4


def test_zombie_running_sync_runs_are_surfaced(seeded):
    """ריצות תקועות ב-RUNNING מסתירות את הכשל שהפיל אותן.

    אומת שאינן חוסמות סנכרון חדש — אף קוד אינו קורא `SyncStatus.RUNNING`,
    והשער בפועל הוא `SyncCheckpoint.last_success_at`. זו תקלת נראוּת.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    seeded.add(SyncRun(organization_id=101, source="sumit", status=SyncStatus.RUNNING,
                       started_at=now - timedelta(hours=ZOMBIE_AFTER_HOURS + 1)))
    seeded.commit()

    report = roster_coverage_report(seeded)
    zombies = report["zombie_runs"]
    assert len(zombies) == 1
    assert zombies[0]["organization_id"] == 101
    assert zombies[0]["hours_stuck"] > ZOMBIE_AFTER_HOURS
    assert report["healthy"] is False


def test_duplicate_target_org_is_flagged(seeded):
    """שתי רשומות פנקס על אותו ארגון => office_rollup סופר אותו פעמיים
    (הכשל של 'may way' על org 5)."""
    seeded.add(SumitCompany(
        office_organization_id=1, company_id="PHANTOM", name="phantom",
        target_organization_id=101, status="active",
    ))
    seeded.commit()

    report = roster_coverage_report(seeded)
    assert 101 in report["duplicate_target_orgs"]
    assert report["healthy"] is False


def test_inactive_roster_rows_are_excluded(seeded):
    """רשומה מושבתת אינה נספרת ככפילות ואינה מדווחת."""
    seeded.add(SumitCompany(
        office_organization_id=1, company_id="PHANTOM", name="phantom",
        target_organization_id=101, status="inactive",
    ))
    seeded.commit()

    report = roster_coverage_report(seeded)
    assert 101 not in report["duplicate_target_orgs"]
    rows = _by_org(report)
    assert len([o for o in ORG_IDS if o in rows]) == 4


def test_one_healthy_source_does_not_mask_a_dead_one(seeded):
    """הפגם שהתגלה מול פרוד: ל-org 2 היה open_finance תקין ו-sumit מושהה.

    שקלול ברמת הארגון החזיר 'ok' כי היה סנכרון מוצלח *כלשהו* היום — והתיק
    שנשר לא הופיע בהתרעה בכלל. הכיסוי חייב להישפט פר-מקור.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # ל-102 (sumit מושהה) מוסיפים open_finance בריא שסונכרן ממש עכשיו.
    seeded.add(IntegrationConnection(
        organization_id=102, source="open_finance", status="active"))
    seeded.add(SyncRun(organization_id=102, source="open_finance",
                       status=SyncStatus.COMPLETED,
                       started_at=now, finished_at=now))
    seeded.commit()

    report = roster_coverage_report(seeded)
    row = _by_org(report)[102]

    assert row["verdict"] == "disconnected", (
        "מקור מת חייב לגבור על מקור בריא באותו ארגון"
    )
    assert any("paused" in i for i in row["issues"])
    assert "שף" not in str(row)  # שמירה על מיקוד: זה ארגון הבדיקה, לא פרוד

    lines = coverage_alert_lines(report)
    assert any("102" in ln or (row["name"] or "") in ln for ln in lines), (
        "ארגון שנשר חייב להופיע בהתרעה"
    )


def test_stale_is_judged_per_source(seeded):
    """מקור פעיל שלא סונכרן זמן רב מסומן stale גם אם מקור אחר טרי."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    seeded.add(IntegrationConnection(
        organization_id=101, source="open_finance", status="active"))
    # open_finance פעיל אך לא סונכרן מעולם בהצלחה מזה שבוע.
    seeded.add(SyncRun(organization_id=101, source="open_finance",
                       status=SyncStatus.COMPLETED,
                       started_at=now - timedelta(hours=STALE_AFTER_HOURS + 10),
                       finished_at=now - timedelta(hours=STALE_AFTER_HOURS + 10)))
    seeded.commit()

    row = _by_org(roster_coverage_report(seeded))[101]
    assert row["verdict"] == "stale"
    assert any("open_finance" in i for i in row["issues"])


# ---------- שלמות נתונים ----------

def test_data_integrity_counts_orphans_and_blank_drafts(seeded):
    """הבקרה מדווחת גם על איכות הנתונים, לא רק על זרימת הסנכרון.

    בפרוד 05/08: 415 טיוטות בסכום 0, 1,200 הוצאות בלי ח.פ ספק, ו-8 חשבוניות
    של org 5 בלי איש קשר. אלה לא עוצרים cron אבל הורסים כל דוח.
    """
    from datetime import date

    from cfo.models import Expense, Invoice

    db = seeded
    db.add(Expense(organization_id=101, source="sumit", external_id="E1",
                   status="pending", total=0, expense_date=date.today(),
                   supplier_name="ריק"))
    db.add(Expense(organization_id=101, source="sumit", external_id="E2",
                   status="pending", total=118, expense_date=date.today(),
                   supplier_name="מלא", supplier_tax_id="511402547"))
    db.add(Invoice(organization_id=101, invoice_number="INV-1", total=100,
                   issue_date=date.today(), contact_id=None))
    db.commit()

    row = _by_org(roster_coverage_report(db))[101]
    integrity = row["data_integrity"]

    assert integrity["expenses_total"] == 2
    assert integrity["expenses_blank_total"] == 1
    assert integrity["expenses_missing_supplier_tax_id"] == 1
    assert integrity["invoices_without_contact"] == 1


def test_clean_org_reports_no_integrity_problems(seeded):
    row = _by_org(roster_coverage_report(seeded))[101]
    integrity = row["data_integrity"]
    assert integrity["expenses_total"] == 0
    assert integrity["expenses_blank_total"] == 0
    assert integrity["invoices_without_contact"] == 0
