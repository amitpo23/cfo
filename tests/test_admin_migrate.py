"""Gate-0 schema migration is global, explicit and fail-closed."""

import pytest
import sqlalchemy as sa

from cfo.auth import create_access_token
from cfo.database import engine
from cfo.database import SessionLocal
from cfo.models import User, UserRole


CONFIRMATION = "I_UNDERSTAND_SCHEMA_MIGRATION_IS_GLOBAL"


@pytest.fixture
def migration_super_admin(client, fresh_org):
    actor = fresh_org()
    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .filter(User.organization_id == actor["org_id"])
            .order_by(User.id)
            .first()
        )
        user.role = UserRole.SUPER_ADMIN
        db.commit()
        token = create_access_token(
            data={
                "sub": str(user.id),
                "role": UserRole.SUPER_ADMIN.value,
                "org_id": user.organization_id,
            }
        )
    finally:
        db.close()
    return {"Authorization": f"Bearer {token}"}


def test_organization_admin_cannot_run_global_schema_migration(client, owner):
    response = client.post(
        "/api/admin/db/migrate",
        json={"confirmation": CONFIRMATION},
        headers=owner["headers"],
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Super admin access required"


def test_super_admin_must_confirm_before_schema_mutation(
    client,
    migration_super_admin,
    monkeypatch,
):
    def forbidden(*args, **kwargs):
        raise AssertionError("schema mutation reached without exact confirmation")

    monkeypatch.setattr("alembic.command.upgrade", forbidden)
    monkeypatch.setattr("alembic.command.stamp", forbidden)
    monkeypatch.setattr("cfo.services.schema_sync.apply_additive", forbidden)

    response = client.post(
        "/api/admin/db/migrate",
        json={"confirmation": "yes"},
        headers=migration_super_admin,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        f"Exact confirmation required: {CONFIRMATION}"
    )


def test_migrate_endpoint_reports_and_fixes_drift(
    client,
    migration_super_admin,
):
    """מדמים drift של עמודה ואז מוודאים שה-endpoint סוגר אותו ומדווח.

    הטסט הרסני במכוון — הוא מוחק עמודה אמיתית. ה-`finally` מחזיר אותה גם
    כשה-endpoint נכשל; בלעדיו העמודה נשארת מחוקה וכל טסט שנוגע ב-
    `organizations` אחריו קורס. זה קרה בפועל ותועד בביקורת Codex 09/08/2026.
    """
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE organizations DROP COLUMN collection_sms_sender"))

    try:
        resp = client.post(
            "/api/admin/db/migrate",
            json={"confirmation": CONFIRMATION},
            headers=migration_super_admin,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "schema_sync" in body
        assert "collection_sms_sender" in body["schema_sync"]["columns"].get("organizations", [])

        insp = sa.inspect(engine)
        cols = {c["name"] for c in insp.get_columns("organizations")}
        assert "collection_sms_sender" in cols
    finally:
        insp = sa.inspect(engine)
        if "collection_sms_sender" not in {
            c["name"] for c in insp.get_columns("organizations")
        }:
            with engine.begin() as conn:
                conn.execute(
                    sa.text("ALTER TABLE organizations ADD COLUMN collection_sms_sender VARCHAR")
                )


def test_migrate_endpoint_falls_back_to_verified_repair_on_already_exists_conflict(
    client,
    migration_super_admin,
    monkeypatch,
):
    """create_all↔alembic conflict: upgrade נכשל עם 'already exists' (DatabaseError) —
    ה-endpoint צריך ליפול חזרה ל-stamp ולדווח action=stamped_after_conflict, ולא
    להתפוצץ. מוודאים שהתפיסה מוגבלת ל-DatabaseError (ולא Exception כללי) ע"י
    כך שה-mock מעלה בדיוק sqlalchemy.exc.OperationalError.
    """
    # ודאי שענף upgrade נלקח (לא stamp הראשוני): טבלת alembic_version קיימת ומאוכלסת.
    with engine.begin() as conn:
        conn.execute(sa.text(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num VARCHAR(32) NOT NULL)"
        ))
        existing = conn.execute(sa.text("SELECT COUNT(*) FROM alembic_version")).scalar()
        if not existing:
            conn.execute(sa.text(
                "INSERT INTO alembic_version (version_num) VALUES ('deadbeef0001')"
            ))

    stamp_calls = []

    def fake_upgrade(cfg, revision):
        raise sa.exc.OperationalError(
            "stmt", {}, Exception("table users already exists")
        )

    def fake_stamp(cfg, revision):
        stamp_calls.append(revision)

    monkeypatch.setattr("alembic.command.upgrade", fake_upgrade)
    monkeypatch.setattr("alembic.command.stamp", fake_stamp)

    resp = client.post(
        "/api/admin/db/migrate",
        json={"confirmation": CONFIRMATION},
        headers=migration_super_admin,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["action"].startswith("reconciled_after_conflict")
    assert stamp_calls == ["head"]
