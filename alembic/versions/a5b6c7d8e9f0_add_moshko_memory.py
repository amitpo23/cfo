"""add moshko_memory table

Revision ID: a5b6c7d8e9f0
Revises: a0b1c2d3e4f5
Create Date: 2026-07-27 10:00:00.000000

Package E (2026-07-27b moshko-memory-and-whatsapp plan) — Moshko's learned
memory. Additive and idempotent, matching the convention set by
d5e6f7a8b9c0_add_irreversible_action_control.py: the table is created only
if missing, so a database that already carries it via the ORM's create_all
(pre-Alembic drift) is left alone.

Not a migration of CfoMemory (cfo_memory table) — that table is org-only,
has no user_id, and is intentionally left untouched. moshko_memory is a new,
separate table: organization_id NOT NULL, user_id nullable (NULL = a fact
about the business, visible to every user in the org; a value = a personal
memory, visible only to its owner).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a5b6c7d8e9f0"
down_revision: Union[str, None] = "a0b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "moshko_memory" not in _tables():
        op.create_table(
            "moshko_memory",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "organization_id",
                sa.Integer(),
                sa.ForeignKey("organizations.id"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("category", sa.String(length=30), nullable=True),
            sa.Column("source", sa.String(length=50), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "ix_moshko_memory_organization_id",
            "moshko_memory",
            ["organization_id"],
            unique=False,
        )
        op.create_index(
            "ix_moshko_memory_org_user",
            "moshko_memory",
            ["organization_id", "user_id"],
            unique=False,
        )


def downgrade() -> None:
    tables = _tables()
    if "moshko_memory" in tables:
        op.drop_table("moshko_memory")
