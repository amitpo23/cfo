"""schema_sync — גילוי גנרי של drift בין המודלים לסכמה החיה."""
import sqlalchemy as sa

from cfo.database import Base
from cfo.services.schema_sync import apply_additive, compute_missing


def _fresh_engine(tmp_path):
    return sa.create_engine(f"sqlite:///{tmp_path}/drift.db")


def test_no_drift_on_full_schema(tmp_path):
    """אחרי create_all מלא — אין שום דבר חסר."""
    engine = _fresh_engine(tmp_path)
    Base.metadata.create_all(engine)
    missing = compute_missing(engine)
    assert missing["tables"] == []
    assert missing["columns"] == {}


def test_detects_missing_table_and_column(tmp_path):
    """טבלה שלא נוצרה ועמודה שהוסרה — שתיהן מתגלות."""
    engine = _fresh_engine(tmp_path)
    tables = dict(Base.metadata.tables)
    victim_table = "collection_reminders"
    assert victim_table in tables, "מודל הייחוס לבדיקה לא קיים עוד — עדכן את הטסט"
    Base.metadata.create_all(
        engine,
        tables=[t for name, t in tables.items() if name != victim_table],
    )
    # מסירים עמודה מטבלה קיימת כדי לדמות drift של עמודה
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE organizations DROP COLUMN collection_sms_sender"))

    missing = compute_missing(engine)
    assert victim_table in missing["tables"]
    assert "collection_sms_sender" in missing["columns"]["organizations"]


def test_apply_additive_closes_the_gap(tmp_path):
    """אחרי apply_additive — compute_missing חוזר ריק, והנתונים הקיימים שורדים."""
    engine = _fresh_engine(tmp_path)
    tables = dict(Base.metadata.tables)
    Base.metadata.create_all(
        engine,
        tables=[t for name, t in tables.items() if name != "collection_reminders"],
    )
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE organizations DROP COLUMN collection_sms_sender"))
        # collection_reminders_enabled is NOT NULL with no server_default (only a
        # Python-side ORM default), so a raw INSERT must supply it explicitly.
        conn.execute(sa.text(
            "INSERT INTO organizations (name, collection_reminders_enabled) "
            "VALUES ('שרידות-נתונים', 0)"
        ))

    applied = apply_additive(engine)
    assert "collection_reminders" in applied["tables"]
    assert "collection_sms_sender" in applied["columns"]["organizations"]

    assert compute_missing(engine) == {"tables": [], "columns": {}}
    with engine.connect() as conn:
        names = [r[0] for r in conn.execute(sa.text("SELECT name FROM organizations"))]
    assert "שרידות-נתונים" in names
