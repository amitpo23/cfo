"""שלב 2 — הקצאת מסד לעוסק ואכיפת "הכול או כלום".

התבנית לעוסק חדש אינה צריכה להיכתב: היא 54 הטבלאות ו-42 המיגרציות.
מסד לעוסק נוצר ב-`alembic upgrade head` על מסד ריק. מה שנדרש הוא
העטיפה — להריץ, לאמת, ולרשום — ולוודא שאף מסד לא נשאר מאחור.

מדיניות "הכול או כלום" (החלטת בעלים 09/08): מיגרציה נחשבת מוצלחת רק
כשמסד הבקרה **וכל** מסדי העוסקים הגיעו ל-head עם drift נקי.

הטסטים כאן אינם נוגעים ב-Neon ואינם יוצרים מסד מרוחק — ההקצאה נבדקת
מול sqlite זמני.
"""
import pytest

from cfo.database import SessionLocal
from cfo.services import tenant_routing
from cfo.services.tenant_provisioning import (
    ProvisioningError,
    migration_readiness,
    provision_tenant_database,
    verify_tenant_schema,
)


def _cleanup(db, org_id: int) -> None:
    from cfo.models import TenantDatabase

    db.query(TenantDatabase).filter(TenantDatabase.organization_id == org_id).delete()
    db.commit()
    tenant_routing.reset_routing()


def test_provisioning_creates_the_full_schema_on_an_empty_database(tmp_path, fresh_org):
    """מסד ריק מקבל את מלוא התבנית — כל 54 הטבלאות — ונרשם כפעיל."""
    org_id = fresh_org()["org_id"]
    dsn = f"sqlite:///{tmp_path/'tenant.db'}"
    db = SessionLocal()
    try:
        result = provision_tenant_database(db, org_id, dsn)

        assert result["organization_id"] == org_id
        assert result["tables_created"] > 40
        assert result["drift"] == []
        assert result["status"] == "active"
    finally:
        _cleanup(db, org_id)
        db.close()


def test_provisioned_database_passes_its_own_schema_verification(tmp_path, fresh_org):
    org_id = fresh_org()["org_id"]
    dsn = f"sqlite:///{tmp_path/'tenant.db'}"
    db = SessionLocal()
    try:
        provision_tenant_database(db, org_id, dsn)
        assert verify_tenant_schema(dsn) == []
    finally:
        _cleanup(db, org_id)
        db.close()


def test_empty_database_fails_verification_rather_than_reporting_ok(tmp_path):
    """מסד שלא הוקצה חייב להיכשל באימות. שער שמדווח OK על מסד ריק
    הוא גרוע מאין שער."""
    missing = verify_tenant_schema(f"sqlite:///{tmp_path/'never-provisioned.db'}")

    assert missing, "מסד ריק דווח כתקין"


def test_provisioning_refuses_to_overwrite_a_populated_database(tmp_path, fresh_org):
    """אפס אוטונומיה בבלתי-הפיך: הקצאה על מסד שכבר מכיל נתונים נעצרת
    ואינה דורסת. הקצאה חוזרת בטעות על מסד חי היא אובדן נתוני לקוח."""
    org_id = fresh_org()["org_id"]
    dsn = f"sqlite:///{tmp_path/'tenant.db'}"
    db = SessionLocal()
    try:
        provision_tenant_database(db, org_id, dsn)

        with pytest.raises(ProvisioningError):
            provision_tenant_database(db, org_id, dsn)
    finally:
        _cleanup(db, org_id)
        db.close()


def test_provisioning_is_allowed_again_with_an_explicit_force_flag(tmp_path, fresh_org):
    org_id = fresh_org()["org_id"]
    dsn = f"sqlite:///{tmp_path/'tenant.db'}"
    db = SessionLocal()
    try:
        provision_tenant_database(db, org_id, dsn)
        result = provision_tenant_database(db, org_id, dsn, force=True)
        assert result["status"] == "active"
    finally:
        _cleanup(db, org_id)
        db.close()


# ---------------------------------------------------------------------- #
# הכול או כלום
# ---------------------------------------------------------------------- #
def test_readiness_reports_control_plane_even_with_no_tenants():
    """מסד בקרה בלי `alembic_version` (למשל סביבה שנבנתה ב-create_all)
    מדווח revision=None ולא מפיל את הדוח."""
    report = migration_readiness(SessionLocal())

    assert "revision" in report["control_plane"]
    assert report["control_plane"]["drift"] == []
    assert "all_or_nothing" in report


def test_a_provisioned_tenant_is_clean_and_carries_a_known_revision(tmp_path, fresh_org):
    """עוסק שהוקצה כראוי מדווח בלי drift ועם revision ידוע.

    הדוח הכולל נשאר אדום כאן, ובצדק: מסד הבקרה בסביבת ההרצה נבנה
    ב-`create_all` ולכן אינו מנוהל ב-alembic. אחרי התיקון של 09/08
    מסד לא-מנוהל מכשיל את השער במקום לעבור בשקט.
    """
    org_id = fresh_org()["org_id"]
    dsn = f"sqlite:///{tmp_path/'tenant.db'}"
    db = SessionLocal()
    try:
        provision_tenant_database(db, org_id, dsn)
        report = migration_readiness(db)

        mine = [t for t in report["tenants"] if t["organization_id"] == org_id]
        assert mine and mine[0]["drift"] == []
        assert mine[0]["revision"]
        assert org_id not in report["unmanaged"]
    finally:
        _cleanup(db, org_id)
        db.close()


def test_one_lagging_database_turns_the_whole_report_red(tmp_path, fresh_org):
    """תיק אחד שלא עבר מכשיל את כל הפריסה — זו בדיוק המדיניות.
    הקוד שרץ הוא אחד לכולם, ותיק שנשאר מאחור יקרוס בשימוש הראשון."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        # נרשם ידנית בלי הקצאה — מדמה מסד שלא קיבל את המיגרציות.
        from cfo.services.tenant_control_plane import register_tenant_database

        register_tenant_database(db, org_id, f"sqlite:///{tmp_path/'lagging.db'}")
        report = migration_readiness(db)

        assert report["all_or_nothing"] is False
        mine = [t for t in report["tenants"] if t["organization_id"] == org_id]
        assert mine and mine[0]["drift"]
    finally:
        _cleanup(db, org_id)
        db.close()


def test_two_tenants_on_different_revisions_turn_the_report_red(tmp_path, fresh_org):
    """שני עוסקים ב-revisions שונים = פריסה חלקית, והדגל אדום.

    זה לב מדיניות "הכול או כלום": הקוד שרץ הוא אחד לכל המסדים, ולכן
    עוסק שנשאר ב-revision ישן אינו "פחות מעודכן" — הוא יקרוס בשימוש
    הראשון בעמודה שנוספה.

    הטסט אינו נשען על מצב סביבת ההרצה: הוא מעמיד בפועל שני מסדים,
    אחד ב-head ואחד ב-revision קודם.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    from cfo.services.tenant_control_plane import register_tenant_database

    current_id = fresh_org()["org_id"]
    lagging_id = fresh_org()["org_id"]
    root = Path(__file__).resolve().parents[1]
    lagging_dsn = f"sqlite:///{tmp_path/'lagging.db'}"

    db = SessionLocal()
    try:
        provision_tenant_database(db, current_id, f"sqlite:///{tmp_path/'current.db'}")

        # מסד שני שנעצר ב-revision קודם — מצב פריסה חלקית אמיתי.
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "e7f8a9b0c1d2"],
            cwd=root,
            env={**os.environ, "DATABASE_URL": lagging_dsn},
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        register_tenant_database(db, lagging_id, lagging_dsn)

        report = migration_readiness(db)

        assert len(report["revisions_seen"]) > 1
        assert report["all_or_nothing"] is False
    finally:
        _cleanup(db, current_id)
        _cleanup(db, lagging_id)
        db.close()


# ---------------------------------------------------------------------- #
# תיקוני ביקורת (Codex QA, 09/08/2026)
# ---------------------------------------------------------------------- #
def test_all_none_revisions_are_not_green(tmp_path, fresh_org):
    """fail-open שנתפס בביקורת: `len(known_revisions) <= 1` החזיר True
    על סט ריק, כלומר מצב שבו אף מסד אינו מנוהל ב-alembic דווח ירוק.
    מסד לא מנוהל אינו "תקין" — הוא מסד שאיש לא יודע באיזו גרסה הוא."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        from cfo.services.tenant_control_plane import register_tenant_database
        import sqlalchemy as sa
        from cfo.models import Base

        # מסד שנבנה ב-create_all — סכימה מלאה, בלי alembic_version.
        dsn = f"sqlite:///{tmp_path/'unmanaged.db'}"
        eng = sa.create_engine(dsn)
        Base.metadata.create_all(eng)
        eng.dispose()

        register_tenant_database(db, org_id, dsn)
        report = migration_readiness(db)

        assert report["all_or_nothing"] is False, "מסד לא מנוהל דווח ירוק"
        assert org_id in report["unmanaged"]
    finally:
        _cleanup(db, org_id)
        db.close()


def test_unreachable_tenant_is_reported_red_not_raised(fresh_org):
    """תיק שלא ניתן להגיע אליו חייב להופיע בדוח כאדום. אם האימות זורק,
    הדוח כולו קורס ואי אפשר לדעת מי הבעייתי."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        from cfo.services.tenant_control_plane import register_tenant_database

        register_tenant_database(
            db, org_id, "postgresql+psycopg://u:p@127.0.0.1:1/nonexistent"
        )
        report = migration_readiness(db)

        assert report["all_or_nothing"] is False
        mine = [t for t in report["tenants"] if t["organization_id"] == org_id]
        assert mine and mine[0]["drift"]
    finally:
        _cleanup(db, org_id)
        db.close()


def test_provisioning_error_never_echoes_the_dsn(tmp_path, fresh_org):
    """הודעת שגיאה מגיעה ללוגים ולמסך. סיסמת מסד של לקוח לא נכנסת
    לשם — גם כשהיא הגיעה מ-stdout של alembic."""
    org_id = fresh_org()["org_id"]
    dsn = "postgresql+psycopg://user:top-secret-pw@127.0.0.1:1/db"
    db = SessionLocal()
    try:
        with pytest.raises(ProvisioningError) as exc:
            provision_tenant_database(db, org_id, dsn)
        assert "top-secret-pw" not in str(exc.value)
    finally:
        _cleanup(db, org_id)
        db.close()


def test_provisioning_refuses_a_dsn_already_used_by_another_organization(
    tmp_path, fresh_org
):
    """force אינו רישיון לאלייסינג: שני ארגונים על אותו מסד פיזי מבטלים
    את הבידוד שלשמו כל המהלך נעשה."""
    first = fresh_org()["org_id"]
    second = fresh_org()["org_id"]
    dsn = f"sqlite:///{tmp_path/'shared.db'}"
    db = SessionLocal()
    try:
        provision_tenant_database(db, first, dsn)

        with pytest.raises(ProvisioningError) as exc:
            provision_tenant_database(db, second, dsn, force=True)
        assert str(first) in str(exc.value)
    finally:
        _cleanup(db, first)
        _cleanup(db, second)
        db.close()
