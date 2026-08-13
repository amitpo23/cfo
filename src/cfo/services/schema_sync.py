"""השוואת המודלים (Base.metadata) מול הסכמה החיה — וגישור additive.

משמש גם את scripts/schema_drift_check.py (קריאה בלבד) וגם את
POST /api/admin/db/migrate (תיקון). additive בלבד: לעולם לא מוחק.

``compute_missing`` נשמר כחוזה הצר של מנגנון התיקון: הוא יודע להוסיף רק
טבלאות ועמודות. ``compute_schema_drift`` הוא שער האימות המלא יותר, ובודק גם
טיפוסים, nullability, מפתחות ראשיים/זרים, unique constraints ואינדקסים. כך
תיקון additive לעולם לא מתחזה להוכחה שאילוצים שלא תוקנו אכן קיימים.
"""
from typing import Any, Dict, List

from sqlalchemy import CheckConstraint, UniqueConstraint, inspect
from sqlalchemy import text as sa_text
from sqlalchemy.engine import Engine

from ..database import Base


_FULL_DRIFT_KEYS = (
    "tables",
    "columns",
    "types",
    "nullability",
    "primary_keys",
    "foreign_keys",
    "unique_constraints",
    "indexes",
)

# These additive legacy/column migrations cannot apply ALTER TABLE ... ADD FK
# on SQLite, while their PostgreSQL paths create the constraints.  They remain
# visible in the report as dialect_exemptions, but are not production
# exemptions: PostgreSQL must contain them or the gate fails.
_SQLITE_FOREIGN_KEY_EXEMPTIONS = {
    ("expenses", ("account_id",), "accounts", ("id",)),
    (
        "irreversible_action_requests",
        ("approved_by_authority_id",),
        "organization_signing_authorities",
        ("id",),
    ),
    ("moshko_memory", ("approved_by",), "users", ("id",)),
}


def empty_schema_drift() -> Dict[str, Any]:
    """Return a fresh, JSON-serializable empty full-drift report."""
    return {
        "tables": [],
        "columns": {},
        "types": {},
        "nullability": {},
        "primary_keys": {},
        "foreign_keys": {},
        "unique_constraints": {},
        "indexes": {},
        "dialect_exemptions": {},
    }


def has_schema_drift(report: Dict[str, Any]) -> bool:
    """True when any known structural drift bucket is non-empty."""
    return any(bool(report.get(key)) for key in _FULL_DRIFT_KEYS)


def expected_check_constraints() -> Dict[str, set]:
    """אילוצי CHECK ששמם מוגדר במפורש במודלים.

    אילוץ בלי שם אינו נכלל: אי-אפשר לזהות אותו במסד באופן יציב, ובדיקה
    לפי טקסט הביטוי הייתה מייצרת drift מדומה בין ניבים.
    """
    from ..models import Base

    expected: Dict[str, set] = {}
    for table in Base.metadata.sorted_tables:
        names = {
            c.name for c in table.constraints
            if isinstance(c, CheckConstraint) and c.name
        }
        if names:
            expected[table.name] = names
    return expected


def compute_check_constraint_drift(engine: Engine) -> list[dict]:
    """אילוצי CHECK שהמודל דורש ואינם קיימים במסד.

    `compute_schema_drift` בודק טבלאות, עמודות, טיפוסים, FK, unique
    ואינדקסים — אך **לא** CHECK. הפער הזה מהותי עבור
    `ck_membership_role_not_super_admin`: הוא מה שמונע ממנהל ארגון
    להעניק חברות SUPER_ADMIN בתיק שלו. מסד שסומן `head` בלעדיו נושא
    הצהרה שקרית על ההגנות שקיימות בו.
    """
    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names())
    drift: list[dict] = []

    for table_name, expected_names in expected_check_constraints().items():
        if table_name not in actual_tables:
            continue  # טבלה חסרה מדווחת ממילא ב-compute_missing
        try:
            present = {
                c.get("name") for c in inspector.get_check_constraints(table_name)
            }
        except NotImplementedError:  # pragma: no cover - ניב ללא תמיכה
            continue
        missing = sorted(n for n in expected_names if n not in present)
        if missing:
            drift.append({"table": table_name, "missing_check_constraints": missing})

    return drift


def _type_signature(column_type: Any) -> Dict[str, Any]:
    """Normalize dialect-specific SQLAlchemy types to a stable contract.

    Affinity avoids false drift such as SQLite ``VARCHAR`` vs SQLAlchemy
    ``String``.  Declared length/precision/scale are still enforced when the
    ORM explicitly specifies them.
    """
    affinity = getattr(column_type, "_type_affinity", type(column_type))
    signature: Dict[str, Any] = {"affinity": affinity.__name__.lower()}
    for attribute in ("length", "precision", "scale"):
        value = getattr(column_type, attribute, None)
        if value is not None:
            signature[attribute] = value
    return signature


def _types_match(expected: Any, actual: Any) -> bool:
    expected_signature = _type_signature(expected)
    actual_signature = _type_signature(actual)
    return all(
        actual_signature.get(key) == value
        for key, value in expected_signature.items()
    )


def _expected_foreign_keys(table: Any) -> set[tuple]:
    return {
        (
            tuple(element.parent.name for element in constraint.elements),
            constraint.elements[0].column.table.name,
            tuple(element.column.name for element in constraint.elements),
        )
        for constraint in table.foreign_key_constraints
        if constraint.elements
    }


def _actual_foreign_keys(inspector: Any, table_name: str) -> set[tuple]:
    return {
        (
            tuple(row.get("constrained_columns") or ()),
            row.get("referred_table"),
            tuple(row.get("referred_columns") or ()),
        )
        for row in inspector.get_foreign_keys(table_name)
    }


def _expected_unique_constraints(table: Any) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _actual_unique_constraints(inspector: Any, table_name: str) -> set[tuple[str, ...]]:
    constraints = {
        tuple(row.get("column_names") or ())
        for row in inspector.get_unique_constraints(table_name)
    }
    # An explicitly-created unique index enforces the same column-tuple
    # invariant.  Several additive migrations use this portable form because
    # SQLite cannot add a named UNIQUE constraint without rebuilding a table.
    constraints.update(
        tuple(row.get("column_names") or ())
        for row in inspector.get_indexes(table_name)
        if row.get("unique")
    )
    return constraints


def _expected_indexes(table: Any) -> set[tuple[tuple[str, ...], bool]]:
    return {
        (tuple(column.name for column in index.columns), bool(index.unique))
        for index in table.indexes
    }


def _actual_indexes(inspector: Any, table_name: str) -> set[tuple[tuple[str, ...], bool]]:
    return {
        (tuple(row.get("column_names") or ()), bool(row.get("unique")))
        for row in inspector.get_indexes(table_name)
    }


def compute_schema_drift(engine: Engine) -> Dict[str, Any]:
    """Compare every safely introspectable ORM structural requirement.

    The report contains *missing or incompatible requirements*, not harmless
    extra legacy objects.  It is read-only and deterministic across SQLite and
    PostgreSQL, making it suitable both for local QA and the authorized
    production migration endpoint.
    """
    inspector = inspect(engine)
    live_tables = set(inspector.get_table_names())
    report = empty_schema_drift()

    for table_name, table in Base.metadata.tables.items():
        if table_name not in live_tables:
            report["tables"].append(table_name)
            continue

        live_column_rows = {
            column["name"]: column
            for column in inspector.get_columns(table_name)
        }
        missing_columns = [
            column.name for column in table.columns
            if column.name not in live_column_rows
        ]
        if missing_columns:
            report["columns"][table_name] = sorted(missing_columns)

        pk_columns = {column.name for column in table.primary_key.columns}
        type_drift: Dict[str, Any] = {}
        nullability_drift: Dict[str, Any] = {}
        for column in table.columns:
            actual = live_column_rows.get(column.name)
            if actual is None:
                continue
            if not _types_match(column.type, actual["type"]):
                type_drift[column.name] = {
                    "expected": _type_signature(column.type),
                    "actual": _type_signature(actual["type"]),
                }
            # SQLite reports INTEGER PRIMARY KEY nullability differently from
            # PostgreSQL; PK membership is verified separately below.
            if column.name not in pk_columns and bool(actual.get("nullable")) != bool(column.nullable):
                nullability_drift[column.name] = {
                    "expected": bool(column.nullable),
                    "actual": bool(actual.get("nullable")),
                }
        if type_drift:
            report["types"][table_name] = type_drift
        if nullability_drift:
            report["nullability"][table_name] = nullability_drift

        expected_pk = tuple(column.name for column in table.primary_key.columns)
        actual_pk = tuple(
            inspector.get_pk_constraint(table_name).get("constrained_columns") or ()
        )
        if expected_pk != actual_pk:
            report["primary_keys"][table_name] = {
                "expected": list(expected_pk),
                "actual": list(actual_pk),
            }

        missing_foreign_keys = _expected_foreign_keys(table) - _actual_foreign_keys(
            inspector, table_name,
        )
        if engine.dialect.name == "sqlite" and missing_foreign_keys:
            exempt = {
                foreign_key
                for foreign_key in missing_foreign_keys
                if (table_name, *foreign_key) in _SQLITE_FOREIGN_KEY_EXEMPTIONS
            }
            if exempt:
                report["dialect_exemptions"][table_name] = [
                    {
                        "kind": "foreign_key",
                        "columns": list(columns),
                        "referred_table": referred_table,
                        "referred_columns": list(referred_columns),
                        "reason": "SQLite additive ALTER cannot create this FK; PostgreSQL must enforce it",
                    }
                    for columns, referred_table, referred_columns in sorted(exempt)
                ]
                missing_foreign_keys -= exempt
        if missing_foreign_keys:
            report["foreign_keys"][table_name] = [
                {
                    "columns": list(columns),
                    "referred_table": referred_table,
                    "referred_columns": list(referred_columns),
                }
                for columns, referred_table, referred_columns in sorted(missing_foreign_keys)
            ]

        missing_uniques = _expected_unique_constraints(table) - _actual_unique_constraints(
            inspector, table_name,
        )
        if missing_uniques:
            report["unique_constraints"][table_name] = [
                list(columns) for columns in sorted(missing_uniques)
            ]

        missing_indexes = _expected_indexes(table) - _actual_indexes(inspector, table_name)
        if missing_indexes:
            report["indexes"][table_name] = [
                {"columns": list(columns), "unique": unique}
                for columns, unique in sorted(missing_indexes)
            ]

    report["tables"] = sorted(report["tables"])
    return report


def compute_missing(engine: Engine) -> Dict:
    """מה חסר בסכמה החיה יחסית למודלים: טבלאות שלמות ועמודות בטבלאות קיימות."""
    inspector = inspect(engine)
    live_tables = set(inspector.get_table_names())

    missing_tables: List[str] = []
    missing_columns: Dict[str, List[str]] = {}

    for name, table in Base.metadata.tables.items():
        if name not in live_tables:
            missing_tables.append(name)
            continue
        live_cols = {c["name"] for c in inspector.get_columns(name)}
        gap = [c.name for c in table.columns if c.name not in live_cols]
        if gap:
            missing_columns[name] = gap

    return {"tables": sorted(missing_tables), "columns": missing_columns}


def apply_additive(engine: Engine) -> Dict:
    """משלים את הסכמה החיה למודלים — additive בלבד (יצירת טבלאות/עמודות חסרות).

    לעולם לא מוחק ולא משנה עמודות קיימות. בטוח להרצה חוזרת (idempotent).
    """
    from sqlalchemy.schema import CreateColumn

    missing = compute_missing(engine)

    if missing["tables"]:
        Base.metadata.create_all(
            engine,
            tables=[Base.metadata.tables[t] for t in missing["tables"]],
        )

    for table_name, col_names in missing["columns"].items():
        table = Base.metadata.tables[table_name]
        with engine.begin() as conn:
            for col_name in col_names:
                col = table.columns[col_name]
                ddl_col = CreateColumn(col).compile(dialect=engine.dialect)
                stmt = f'ALTER TABLE {table_name} ADD COLUMN {ddl_col}'
                if col.nullable is False and col.server_default is None:
                    # SQLAlchemy's CreateColumn DDL compiler never emits a Python-side
                    # default= as a DDL DEFAULT clause — only server_default reaches
                    # DDL. לכן כל עמודת NOT NULL בלי server_default (גם אם יש לה
                    # default צד-Python) תיכשל על טבלה מאוכלסת אם תישאר NOT NULL —
                    # מוסיפים כ-nullable; אכיפת NOT NULL נשארת למיגרציית alembic מסודרת.
                    stmt = stmt.replace(" NOT NULL", "")
                conn.execute(sa_text(stmt))

    return missing
