"""Phase A of the card "available" column: the migration only, safe to deploy before it runs.

Production, 27/10/2026: a card's stored balance is whichever Open Finance balance
came last (the last statement or the open-to-buy), so "how much is free on my
cards" cannot be answered. ``accounts.available_limit`` will hold the bank's
``interimAvailable``.

Phase B maps the column. A deferred column would keep it out of SELECT but not
out of INSERT (the ORM writes every mapped column on a new Account), so phase B
deploys only after ``POST /api/admin/db/migrate`` has run this revision in
production. The model column must match the migration exactly.
"""
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from cfo.models import Account

ROOT = Path(__file__).resolve().parents[1]


def test_the_model_column_matches_the_migration():
    column = Account.__table__.columns["available_limit"]
    assert column.nullable is True
    assert column.type.precision == 14 and column.type.scale == 2


def test_the_migration_adds_it_on_top_of_the_single_head():
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    heads = script.get_heads()
    assert len(heads) == 1
    revision = script.get_revision(heads[0])
    assert revision.down_revision == "g15b7d43e9f0"
    source = Path(revision.path).read_text(encoding="utf-8")
    assert "available_limit" in source and "add_column" in source and "drop_column" in source
    assert "nullable=True" in source
