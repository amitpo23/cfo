"""add bank transaction provisional evidence flag

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-07-25 20:10:00.000000

The model and sync path have carried ``is_provisional`` since July 4, but the
column was previously created only by the additive startup repair.  A clean
Alembic deployment therefore drifted from the ORM.  Keep the migration
additive and idempotent for databases that already received that repair.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def upgrade() -> None:
    if "is_provisional" not in _columns("bank_transactions"):
        op.add_column(
            "bank_transactions",
            sa.Column("is_provisional", sa.Boolean(), nullable=True),
        )


def downgrade() -> None:
    if "is_provisional" in _columns("bank_transactions"):
        op.drop_column("bank_transactions", "is_provisional")
