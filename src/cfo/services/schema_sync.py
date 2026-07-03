"""השוואת המודלים (Base.metadata) מול הסכמה החיה — וגישור additive.

משמש גם את scripts/schema_drift_check.py (קריאה בלבד) וגם את
POST /api/admin/db/migrate (תיקון). additive בלבד: לעולם לא מוחק.
"""
from typing import Dict, List

from sqlalchemy import inspect
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
    raise NotImplementedError  # Task 3
