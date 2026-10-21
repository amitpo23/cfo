"""Public dashboard rate limits, separate from provider request budgets.

Not applied to production. Gate 0 still requires an owner-approved repair.
"""
from alembic import op
import sqlalchemy as sa

revision = "g15b7d43e9f0"
down_revision = "f14a6c32d8e5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dashboard_rate_limits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope_key", sa.String(length=64), nullable=False),
        sa.Column("window_kind", sa.String(length=20), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "scope_key", "window_kind", "window_start",
            name="uq_dashboard_rate_window",
        ),
    )
    op.create_index(
        "ix_dashboard_rate_window_start",
        "dashboard_rate_limits",
        ["window_start"],
    )


def downgrade():
    op.drop_index("ix_dashboard_rate_window_start", table_name="dashboard_rate_limits")
    op.drop_table("dashboard_rate_limits")
