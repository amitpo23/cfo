"""schema_sync — גילוי גנרי של drift בין המודלים לסכמה החיה."""
import sqlalchemy as sa

from cfo.database import Base
from cfo.services.schema_sync import compute_missing


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
