"""Offline contract for the owner-approved Gate-0 schema transition."""

from pathlib import Path

import sqlalchemy as sa
import pytest

from cfo.database import Base
from cfo.services import schema_deployment


ROOT = Path(__file__).resolve().parents[1]


def _legacy_engine(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "ALTER TABLE organizations "
                "DROP COLUMN collection_sms_sender"
            )
        )
    return engine


def test_legacy_database_is_repaired_and_verified_before_head_stamp(tmp_path):
    engine = _legacy_engine(tmp_path)
    events = []

    def stamp(_config, revision):
        assert schema_deployment.compute_missing(engine) == {
            "tables": [],
            "columns": {},
        }
        events.append(("stamp", revision))

    result = schema_deployment.reconcile_schema_to_head(
        engine,
        alembic_config=object(),
        stamp=stamp,
    )

    assert result["action"] == "reconciled_legacy_database"
    assert result["schema_sync"]["columns"]["organizations"] == [
        "collection_sms_sender"
    ]
    assert result["remaining"] == {"tables": [], "columns": {}}
    assert events == [("stamp", "head")]


def test_unclosed_drift_prevents_false_head_stamp(tmp_path, monkeypatch):
    engine = _legacy_engine(tmp_path)
    stamp_calls = []
    # ה-patch נעשה על המודול המקורי ולא על שם מועתק ב-schema_deployment.
    # `schema_deployment` ניגש דרך `schema_sync.apply_additive` בכל קריאה
    # (שונה ב-09/08/2026), ולכן ה-patch נתפס — ומתנקה כראוי בסוף הטסט
    # במקום לקפוא על התחליף ולהפיל טסטים שרצים אחריו.
    monkeypatch.setattr(
        schema_deployment.schema_sync,
        "apply_additive",
        lambda _engine: {"tables": [], "columns": {}},
    )

    with pytest.raises(
        schema_deployment.SchemaDeploymentError,
        match="schema drift remains",
    ):
        schema_deployment.reconcile_schema_to_head(
            engine,
            alembic_config=object(),
            stamp=lambda *_args: stamp_calls.append("called"),
        )

    assert stamp_calls == []


@pytest.mark.parametrize(
    "relative_path",
    [
        "scripts/fix_prod_schema_drift.py",
        "scripts/apply_tax_rules_schema.py",
        "scripts/apply_morning_cycle_schema.py",
    ],
)
def test_partial_schema_repair_scripts_never_stamp_alembic_head(relative_path):
    source = (ROOT / relative_path).read_text()

    assert "alembic_command.stamp" not in source
    assert "then: alembic stamp head" not in source
