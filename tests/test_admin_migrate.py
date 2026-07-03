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
