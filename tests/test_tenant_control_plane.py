"""שלב 1 של תוכנית ה-DB פר-ארגון — מסד הבקרה.

מסד הבקרה הוא היחיד שיודע מי קיים: `users`, `organizations`, ומיפוי
ארגון→DSN. משתמש אינו "שייך" למסד של עוסק — הוא **מורשה** אליו, וההרשאה
נבדקת פעם אחת מול מסד הבקרה (הבהרת בעלים 09/08/2026).

ה-DSN הוא סוד: הוא מכיל שם משתמש וסיסמה למסד של לקוח. הוא נשמר מוצפן
באותו מנגנון שמצפין כבר קרדנשלים של SUMIT ו-Open Finance.
"""
from cfo.database import SessionLocal
from cfo.services import tenant_routing
from cfo.services.tenant_control_plane import (
    dsn_for_organization,
    load_routing_from_control_plane,
    register_tenant_database,
    tenant_database_rows,
)


def _cleanup(db, org_id: int) -> None:
    from cfo.models import TenantDatabase

    db.query(TenantDatabase).filter(TenantDatabase.organization_id == org_id).delete()
    db.commit()
    tenant_routing.reset_routing()


def test_registering_a_tenant_database_stores_the_dsn_encrypted(fresh_org):
    """ה-DSN אינו נשמר בטקסט גלוי — הוא סוד ברמת קרדנשל ספק."""
    from cfo.models import TenantDatabase

    org_id = fresh_org()["org_id"]
    dsn = "postgresql+psycopg://user:secret-pass@host/db"
    db = SessionLocal()
    try:
        register_tenant_database(db, org_id, dsn)

        row = db.query(TenantDatabase).filter(
            TenantDatabase.organization_id == org_id
        ).one()
        assert dsn not in (row.dsn_encrypted or "")
        assert "secret-pass" not in (row.dsn_encrypted or "")
        assert dsn_for_organization(db, org_id) == dsn
    finally:
        _cleanup(db, org_id)
        db.close()


def test_unregistered_organization_has_no_dsn(fresh_org):
    """honest-null: ארגון שטרם פוצל מחזיר None ולא ניחוש."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        assert dsn_for_organization(db, org_id) is None
    finally:
        db.close()


def test_loading_routing_activates_only_registered_organizations(fresh_org):
    """טעינה ממסד הבקרה מפעילה ניתוב רק למי שנרשם; השאר נשארים על
    המסד המשותף. זה מה שהופך את הפיצול להדרגתי."""
    from cfo.database import engine as shared_engine

    org_id = fresh_org()["org_id"]
    other_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        register_tenant_database(db, org_id, "sqlite://")
        load_routing_from_control_plane(db)

        assert tenant_routing.engine_for(org_id) is not shared_engine
        assert tenant_routing.engine_for(other_id) is shared_engine
        assert tenant_routing.split_organization_ids() == [org_id]
    finally:
        _cleanup(db, org_id)
        db.close()


def test_inactive_rows_are_not_routed(fresh_org):
    """מסד שסומן inactive (למשל אחרי rollback של פיצול) אינו מנותב —
    התנועה חוזרת למסד המשותף בלי למחוק את הרשומה."""
    from cfo.database import engine as shared_engine
    from cfo.models import TenantDatabase

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        register_tenant_database(db, org_id, "sqlite://")
        row = db.query(TenantDatabase).filter(
            TenantDatabase.organization_id == org_id
        ).one()
        row.status = "inactive"
        db.commit()

        load_routing_from_control_plane(db)
        assert tenant_routing.engine_for(org_id) is shared_engine
    finally:
        _cleanup(db, org_id)
        db.close()


def test_re_registering_replaces_the_dsn_without_duplicating_rows(fresh_org):
    from cfo.models import TenantDatabase

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        register_tenant_database(db, org_id, "sqlite:///first")
        register_tenant_database(db, org_id, "sqlite:///second")

        rows = db.query(TenantDatabase).filter(
            TenantDatabase.organization_id == org_id
        ).all()
        assert len(rows) == 1
        assert dsn_for_organization(db, org_id) == "sqlite:///second"
    finally:
        _cleanup(db, org_id)
        db.close()


def test_tenant_database_rows_never_expose_the_secret(fresh_org):
    """הרשימה משמשת לתצוגה ולאכיפת 'הכול או כלום'. היא מחזירה סטטוס
    ומזהים — לא DSN, שלא ידלוף ללוגים או למסך אדמין."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        register_tenant_database(db, org_id, "postgresql+psycopg://u:p@h/d")

        rows = tenant_database_rows(db)
        mine = [row for row in rows if row["organization_id"] == org_id]
        assert mine
        for row in mine:
            assert "dsn" not in row
            assert "p@h" not in json_dump(row)
            assert row["status"] == "active"
    finally:
        _cleanup(db, org_id)
        db.close()


def json_dump(value) -> str:
    import json

    return json.dumps(value, default=str, ensure_ascii=False)


def test_undecryptable_dsn_fails_closed_instead_of_falling_back(fresh_org):
    """תיקון ביקורת (Codex QA 09/08): DSN שאינו ניתן לפענוח **חייב**
    להיכשל, לא להפיל את הארגון בשקט למסד המשותף.

    התרחיש: סיבוב מפתח הצפנה. אם הטעינה מדלגת בשקט, כל העוסקים חוזרים
    למסד אחד ואיש לא יודע — זה fail-open, וההפך מהדוקטרינה.
    """
    import pytest

    from cfo.models import TenantDatabase
    from cfo.services.tenant_control_plane import RoutingLoadError

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        register_tenant_database(db, org_id, "sqlite://")
        row = db.query(TenantDatabase).filter(
            TenantDatabase.organization_id == org_id
        ).one()
        row.dsn_encrypted = "לא-ניתן-לפענוח"
        db.commit()

        with pytest.raises(RoutingLoadError) as exc:
            load_routing_from_control_plane(db)
        assert str(org_id) in str(exc.value)
    finally:
        _cleanup(db, org_id)
        db.close()
