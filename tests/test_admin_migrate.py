"""POST /api/admin/db/migrate חייב להשלים גם עמודות חסרות (drift), לא רק alembic."""
import sqlalchemy as sa

from cfo.database import engine


def test_migrate_endpoint_reports_and_fixes_drift(client, owner):
    """מדמים drift של עמודה ואז מוודאים שה-endpoint סוגר אותו ומדווח."""
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE organizations DROP COLUMN collection_sms_sender"))

    resp = client.post("/api/admin/db/migrate", headers=owner["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert "schema_sync" in body
    assert "collection_sms_sender" in body["schema_sync"]["columns"].get("organizations", [])

    insp = sa.inspect(engine)
    cols = {c["name"] for c in insp.get_columns("organizations")}
    assert "collection_sms_sender" in cols


def test_migrate_endpoint_falls_back_to_stamp_on_already_exists_conflict(client, owner, monkeypatch):
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

    resp = client.post("/api/admin/db/migrate", headers=owner["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["action"].startswith("stamped_after_conflict")
    assert stamp_calls == ["head"]
