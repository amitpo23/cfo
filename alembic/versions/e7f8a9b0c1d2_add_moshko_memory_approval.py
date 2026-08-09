"""add human approval metadata to Moshko memory

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-08-01 12:00:00.000000

Additive only. Existing memories intentionally remain unapproved.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("moshko_memory")
    }


def _approved_by_fk_exists() -> bool:
    return any(
        foreign_key.get("name") == "fk_moshko_memory_approved_by_users"
        or foreign_key.get("constrained_columns") == ["approved_by"]
        for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys("moshko_memory")
    )


def upgrade() -> None:
    columns = _columns()
    if "approved_at" not in columns:
        op.add_column("moshko_memory", sa.Column("approved_at", sa.DateTime(), nullable=True))
    if "approved_by" not in columns:
        op.add_column(
            "moshko_memory",
            sa.Column("approved_by", sa.Integer(), nullable=True),
        )
    # SQLite cannot ALTER a table to add a foreign-key constraint. Keep the
    # local migration additive and enforce the FK on production-capable
    # dialects; the ORM still declares the relationship for fresh metadata.
    if op.get_bind().dialect.name != "sqlite" and not _approved_by_fk_exists():
        op.create_foreign_key(
            "fk_moshko_memory_approved_by_users",
            "moshko_memory",
            "users",
            ["approved_by"],
            ["id"],
        )


def downgrade() -> None:
    columns = _columns()
    if "approved_by" in columns:
        if op.get_bind().dialect.name != "sqlite" and _approved_by_fk_exists():
            op.drop_constraint(
                "fk_moshko_memory_approved_by_users",
                "moshko_memory",
                type_="foreignkey",
            )
        op.drop_column("moshko_memory", "approved_by")
    if "approved_at" in columns:
        op.drop_column("moshko_memory", "approved_at")
