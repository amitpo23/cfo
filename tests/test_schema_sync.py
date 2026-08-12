"""schema_sync — גילוי גנרי של drift בין המודלים לסכמה החיה."""
import sqlalchemy as sa

from cfo.database import Base
from cfo.services.schema_sync import (
    apply_additive,
    compute_missing,
    compute_schema_drift,
    empty_schema_drift,
    has_schema_drift,
)


def _fresh_engine(tmp_path):
    return sa.create_engine(f"sqlite:///{tmp_path}/drift.db")


def test_no_drift_on_full_schema(tmp_path):
    """אחרי create_all מלא — אין שום דבר חסר."""
    engine = _fresh_engine(tmp_path)
    Base.metadata.create_all(engine)
    missing = compute_missing(engine)
    assert missing["tables"] == []
    assert missing["columns"] == {}


def test_full_schema_verifier_is_clean_after_create_all(tmp_path):
    engine = _fresh_engine(tmp_path)
    Base.metadata.create_all(engine)

    drift = compute_schema_drift(engine)

    assert drift == empty_schema_drift()
    assert has_schema_drift(drift) is False


def test_full_schema_verifier_detects_type_and_nullability_drift(tmp_path):
    engine = _fresh_engine(tmp_path)
    with engine.begin() as conn:
        # Both deviations are deliberate: ORM expects name VARCHAR NOT NULL.
        conn.execute(sa.text(
            "CREATE TABLE organizations (id INTEGER PRIMARY KEY, name INTEGER NULL)"
        ))

    drift = compute_schema_drift(engine)

    assert "name" in drift["types"]["organizations"]
    assert drift["nullability"]["organizations"]["name"] == {
        "expected": False,
        "actual": True,
    }
    assert has_schema_drift(drift) is True


def test_full_schema_verifier_detects_missing_index(tmp_path):
    engine = _fresh_engine(tmp_path)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP INDEX ix_aichat_org_session"))

    drift = compute_schema_drift(engine)

    assert {
        "columns": ["organization_id", "session_id"],
        "unique": False,
    } in drift["indexes"]["ai_chat_messages"]


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


def test_apply_additive_adds_notnull_python_default_column_as_nullable(tmp_path):
    """עמודת NOT NULL עם default צד-Python בלבד (בלי server_default) — כמו
    organizations.collection_reminders_enabled (nullable=False, default=False).
    SQLAlchemy's CreateColumn DDL compiler never emits a Python-side default=
    as a DDL DEFAULT clause — רק server_default מגיע ל-DDL. לכן חייבים להוסיף
    אותה כ-nullable, אחרת ADD COLUMN NOT NULL בלי DEFAULT נכשל על טבלה מאוכלסת.
    """
    engine = _fresh_engine(tmp_path)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        # מכניסים שורה בזמן שהעמודה עדיין קיימת (כדי לספק ערך מפורש ל-NOT NULL)
        conn.execute(sa.text(
            "INSERT INTO organizations (name, collection_reminders_enabled) "
            "VALUES ('שורד-בלי-server-default', 0)"
        ))
        # מדמים drift: מסירים עמודת NOT NULL עם Python-side default בלבד
        conn.execute(sa.text(
            "ALTER TABLE organizations DROP COLUMN collection_reminders_enabled"
        ))

    apply_additive(engine)  # לפני התיקון: OperationalError (NOT NULL בלי DEFAULT)

    assert compute_missing(engine) == {"tables": [], "columns": {}}
    with engine.connect() as conn:
        names = [r[0] for r in conn.execute(sa.text("SELECT name FROM organizations"))]
    assert "שורד-בלי-server-default" in names
