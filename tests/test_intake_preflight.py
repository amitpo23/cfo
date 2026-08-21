"""שער לפני קליטה: תיק לא נקשר לארגון שכבר שייך לתיק אחר.

הרקע (אודיט פרוד 05/08/2026): רשומת `may way` (חברת SUMIT 895072659) נקשרה
ל-`target_organization_id=5` — הארגון של עומר ועודד פורת, שכבר היה שייך
לחברה 1999386278. התוצאה: `office_rollup` סינתז את org 5 פעמיים והמע"מ שלו
נספר כפול בדוח המשרד.

שני מסלולים כותבים את הקישור הזה, ושניהם עשו זאת ללא בדיקה:
`office_service.register_client` ו-`client_automation_service.ensure_row`.
"""
import pytest

from cfo.models import IntegrationConnection, Organization, SumitCompany
from cfo.services.roster_coverage import (
    IntakeConflict,
    assert_intake_allowed,
    intake_conflict,
)

OFFICE = 1
ORG_IDS = (987201, 987202)
TEST_COMPANY_IDS = ("1999386278", "895072659")


def _purge(db):
    db.query(IntegrationConnection).filter(
        IntegrationConnection.organization_id.in_(ORG_IDS)).delete(
        synchronize_session=False)
    # גם לפי company_id: שורת ה-may way נזרעת עם target_organization_id=None
    # ולכן לא הייתה נתפסת בסינון לפי ארגון-יעד.
    db.query(SumitCompany).filter(
        SumitCompany.company_id.in_(TEST_COMPANY_IDS)).delete(
        synchronize_session=False)
    db.query(SumitCompany).filter(
        SumitCompany.target_organization_id.in_(ORG_IDS)).delete(
        synchronize_session=False)
    db.query(Organization).filter(Organization.id.in_(ORG_IDS)).delete(
        synchronize_session=False)
    db.commit()


@pytest.fixture
def seeded(client):
    from cfo.database import SessionLocal

    db = SessionLocal()
    _purge(db)
    db.add(Organization(id=987201, name="תיק תפוס", is_active=True))
    db.add(Organization(id=987202, name="תיק פנוי", is_active=True))
    db.flush()
    db.add(SumitCompany(
        office_organization_id=OFFICE, company_id="1999386278",
        name="הבעלים החוקי", target_organization_id=987201, status="active",
    ))
    db.commit()
    yield db
    _purge(db)
    db.close()


def test_binding_a_second_company_to_a_claimed_org_is_blocked(seeded):
    """הכשל של may way בדיוק."""
    conflict = intake_conflict(
        seeded, office_organization_id=OFFICE,
        company_id="895072659", target_organization_id=987201,
    )
    assert conflict is not None
    assert "1999386278" in conflict
    assert "987201" in conflict


def test_rebinding_a_company_to_its_own_org_is_allowed(seeded):
    """קליטה חוזרת של אותו תיק אינה התנגשות."""
    assert intake_conflict(
        seeded, office_organization_id=OFFICE,
        company_id="1999386278", target_organization_id=987201,
    ) is None


def test_binding_to_a_free_org_is_allowed(seeded):
    assert intake_conflict(
        seeded, office_organization_id=OFFICE,
        company_id="895072659", target_organization_id=987202,
    ) is None


def test_an_inactive_owner_does_not_block(seeded):
    """רשומה מושבתת אינה תופסת ארגון — אחרת השבתה הייתה נועלת אותו לנצח."""
    row = seeded.query(SumitCompany).filter(
        SumitCompany.company_id == "1999386278").first()
    row.status = "inactive"
    seeded.commit()

    assert intake_conflict(
        seeded, office_organization_id=OFFICE,
        company_id="895072659", target_organization_id=987201,
    ) is None


def test_assert_raises_on_conflict(seeded):
    with pytest.raises(IntakeConflict) as exc:
        assert_intake_allowed(
            seeded, office_organization_id=OFFICE,
            company_id="895072659", target_organization_id=987201,
        )
    assert "895072659" in str(exc.value)


def test_assert_is_silent_when_allowed(seeded):
    assert_intake_allowed(
        seeded, office_organization_id=OFFICE,
        company_id="895072659", target_organization_id=987202,
    )


def test_register_client_refuses_to_steal_a_claimed_org(seeded, monkeypatch):
    """המסלול הראשון שכותב את הקישור."""
    from cfo.services import office_service

    with pytest.raises(IntakeConflict):
        office_service._guard_intake(
            seeded, office_organization_id=OFFICE,
            company_id="895072659", target_organization_id=987201,
        )


def test_repair_does_not_steal_an_org_owned_by_another_company(seeded, monkeypatch):
    """המסלול השני: `ensure_row` קישר מחדש ללא תנאי, ולכן היה יכול לגנוב
    ארגון של תיק אחר בכל ריצת cron.

    שתי טענות בבדיקה אחת, בכוונה: שהשער מנע את הגניבה, **ושהבדיקה בכלל
    הגיעה אליו**. בלי הטענה השנייה, בדיקה שאינה מבקרת בשורה הייתה עוברת
    גם עם השער מנוטרל — אותו כשל כמו mock שמחזיר את הערך שנזרע.
    ל-`ensure_row` יש דרך אחת להגיע ל-org 987201: חיבור SUMIT פעיל שהקרדנשלים
    שלו מפענחים ל-895072659.
    """
    from cfo.services import client_automation_service as cas
    from cfo.services import roster_coverage
    from cfo.services.credentials_vault import encrypt_credentials

    seeded.add(IntegrationConnection(
        organization_id=987201, source="sumit", status="active",
        credentials_encrypted=encrypt_credentials(
            {"api_key": "k", "company_id": "895072659"}
        ),
    ))
    seeded.add(SumitCompany(
        office_organization_id=OFFICE, company_id="895072659",
        name="may way", target_organization_id=None, status="active",
    ))
    seeded.commit()

    checked = []
    original = roster_coverage.intake_conflict

    def spy(db, **kw):
        checked.append(kw["company_id"])
        return original(db, **kw)

    monkeypatch.setattr(roster_coverage, "intake_conflict", spy)
    cas.repair_missing_client_roster(seeded, office_organization_id=OFFICE)

    assert "895072659" in checked, (
        "הבדיקה לא הגיעה ל-ensure_row ולכן אינה מכסה את השער"
    )
    row = seeded.query(SumitCompany).filter(
        SumitCompany.company_id == "895072659").first()
    assert row.target_organization_id != 987201, (
        "התיקון גנב ארגון שכבר שייך לחברה אחרת"
    )


def test_skipped_repair_is_reported_not_only_logged(seeded, monkeypatch):
    """honest-null: דילוג שקיים רק בלוג אינו אות. ה-cron מדווח את `repaired`,
    ולכן הדילוג חייב להופיע שם — אבל בלי להיכנס ללולאת האוטומציה."""
    from cfo.services import client_automation_service as cas
    from cfo.services.credentials_vault import encrypt_credentials

    seeded.add(IntegrationConnection(
        organization_id=987201, source="sumit", status="active",
        credentials_encrypted=encrypt_credentials(
            {"api_key": "k", "company_id": "895072659"}
        ),
    ))
    seeded.add(SumitCompany(
        office_organization_id=OFFICE, company_id="895072659",
        name="may way", target_organization_id=None, status="active",
    ))
    seeded.commit()

    enqueued = []
    monkeypatch.setattr(
        cas, "enqueue_client_automation",
        lambda db, **kw: enqueued.append(kw["client_company_id"]))

    result = cas.repair_missing_client_roster(seeded, office_organization_id=OFFICE)

    skipped = [r for r in result if r.get("skipped")]
    assert len(skipped) == 1
    assert skipped[0]["company_id"] == "895072659"
    assert "1999386278" in skipped[0]["reason"]
    assert "895072659" not in enqueued, "שורה שדולגה לא נכנסת ללולאה"
