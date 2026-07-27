"""add push_enabled and last_push_at to channel_identities

Revision ID: a0b1c2d3e4f5
Revises: f2a3b4c5d6e7
Create Date: 2026-07-27 09:00:00.000000

Package B (proactive push + opt-in + quiet hours) of
docs/superpowers/plans/2026-07-27-moshko-full-bot.md. Additive and
idempotent, matching the convention set by
e6f7a8b9c0d1_add_bank_transaction_provisional.py: each column is added only
if missing, so a database that already carries it via the ORM's create_all
(pre-Alembic drift) is left alone.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def upgrade() -> None:
    columns = _columns("channel_identities")

    if "push_enabled" not in columns:
        op.add_column(
            "channel_identities",
            sa.Column("push_enabled", sa.Boolean(), nullable=True),
        )

    if "last_push_at" not in columns:
        op.add_column(
            "channel_identities",
            sa.Column("last_push_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    columns = _columns("channel_identities")

    if "last_push_at" in columns:
        op.drop_column("channel_identities", "last_push_at")

    if "push_enabled" in columns:
        op.drop_column("channel_identities", "push_enabled")
