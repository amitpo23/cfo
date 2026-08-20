"""W2.1 — טבלת מדידות מכסת SUMIT (המפיק של quota_snapshot).

Revision ID: a2b3c4d5e6f7
Revises: 16d7e8f9a0b1
Create Date: 2026-08-20
"""
import sqlalchemy as sa
from alembic import op

revision = "a2b3c4d5e6f7"
down_revision = "16d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sumit_quota_measurements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id", sa.Integer(),
            sa.ForeignKey("organizations.id"), nullable=False,
        ),
        sa.Column("environment", sa.String(length=10), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False),
        sa.Column("limit_value", sa.Integer(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_sumit_quota_measurements_org_measured",
        "sumit_quota_measurements",
        ["organization_id", "measured_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sumit_quota_measurements_org_measured",
        table_name="sumit_quota_measurements",
    )
    op.drop_table("sumit_quota_measurements")
