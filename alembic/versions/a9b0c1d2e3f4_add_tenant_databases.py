"""add tenant_databases — מיפוי ארגון→מסד ייעודי (DB פר-ארגון, שלב 1)

Revision ID: a9b0c1d2e3f4
Revises: e7f8a9b0c1d2
Create Date: 2026-08-09 10:30:00.000000

Additive only. הטבלה נוצרת ריקה: ארגון בלי שורה כאן ממשיך לעבוד מול
המסד המשותף בדיוק כמו היום, ולכן המיגרציה אינה משנה שום התנהגות קיימת.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "tenant_databases" in _tables():
        return

    op.create_table(
        "tenant_databases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("dsn_encrypted", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False, server_default="neon"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("schema_revision", sa.String(length=64), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_tenant_databases_status", "tenant_databases", ["status"])


def downgrade() -> None:
    if "tenant_databases" in _tables():
        op.drop_table("tenant_databases")
