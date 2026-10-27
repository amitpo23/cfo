"""accounts.available_limit — the bank's available amount (open to buy on a card).

Not applied to production. Apply with POST /api/admin/db/migrate after a pg_dump
restore point (docs/GATE0_DEPLOYMENT_RUNBOOK.md). Nullable, no default, no
backfill: the next Open Finance sync fills it from interimAvailable. The model
column is added only after this runs (an ORM INSERT writes every mapped column).

Revision ID: k40a1b2c3d4e
Revises: g15b7d43e9f0
"""
from alembic import op
import sqlalchemy as sa

revision = "k40a1b2c3d4e"
down_revision = "g15b7d43e9f0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("accounts", sa.Column("available_limit", sa.Numeric(precision=14, scale=2), nullable=True))


def downgrade():
    op.drop_column("accounts", "available_limit")
