"""Add cross-instance provider request budgets.

Revision ID: f3a4b5c6d7e8
Revises: e3f4a5b6c7d8
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa


revision = "f3a4b5c6d7e8"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_request_budgets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("scope_key", sa.String(length=80), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("window_kind", sa.String(length=20), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("limit_value", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("used >= 0",
                           name="ck_provider_budget_used_nonnegative"),
        sa.CheckConstraint("limit_value >= 0",
                           name="ck_provider_budget_limit_nonnegative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "scope_key", "window_kind", "window_start",
            name="uq_provider_budget_window",
        ),
    )
    op.create_index(
        "ix_provider_budget_provider_window", "provider_request_budgets",
        ["provider", "window_kind", "window_start"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_budget_provider_window",
        table_name="provider_request_budgets",
    )
    op.drop_table("provider_request_budgets")
