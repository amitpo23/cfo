"""השוואת המודלים (Base.metadata) מול הסכמה החיה — וגישור additive.

משמש גם את scripts/schema_drift_check.py (קריאה בלבד) וגם את
POST /api/admin/db/migrate (תיקון). additive בלבד: לעולם לא מוחק.
"""
from typing import Dict, List

from sqlalchemy import inspect
from sqlalchemy import text as sa_text
from sqlalchemy.engine import Engine

from ..database import Base


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
