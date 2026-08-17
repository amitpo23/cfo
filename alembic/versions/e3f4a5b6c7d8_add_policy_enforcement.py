"""Persist organization policy and three-moment action evidence.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa


revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


_ROLE_VALUES = (
    "SUPER_ADMIN", "ADMIN", "ACCOUNTANT", "MANAGER", "USER", "VIEWER",
)


def _user_role_type():
    if op.get_context().dialect.name == "postgresql":
        from sqlalchemy.dialects import postgresql

        return postgresql.ENUM(*_ROLE_VALUES, name="userrole", create_type=False)
    return sa.Enum(*_ROLE_VALUES, name="userrole")


def upgrade() -> None:
    op.create_table(
        "policy_grants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("effect", sa.String(length=10), nullable=False,
                  server_default="allow"),
        sa.Column("role", _user_role_type(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("max_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("daily_limit_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("monthly_limit_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False,
                  server_default="ILS"),
        sa.Column("allowed_bank_accounts", sa.JSON(), nullable=True),
        sa.Column("allowed_counterparties", sa.JSON(), nullable=True),
        sa.Column("allowed_document_types", sa.JSON(), nullable=True),
        sa.Column("allowed_channels", sa.JSON(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requires_step_up", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("required_approvals", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("separation_of_duties", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("requires_reason", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("revoked_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("effect IN ('allow', 'deny')",
                           name="ck_policy_grant_effect"),
        sa.CheckConstraint(
            "((role IS NOT NULL AND user_id IS NULL) OR "
            "(role IS NULL AND user_id IS NOT NULL))",
            name="ck_policy_grant_single_subject",
        ),
        sa.CheckConstraint("required_approvals >= 1",
                           name="ck_policy_required_approvals"),
        sa.CheckConstraint("max_amount IS NULL OR max_amount > 0",
                           name="ck_policy_max_amount_positive"),
        sa.CheckConstraint(
            "daily_limit_amount IS NULL OR daily_limit_amount > 0",
            name="ck_policy_daily_limit_positive",
        ),
        sa.CheckConstraint(
            "monthly_limit_amount IS NULL OR monthly_limit_amount > 0",
            name="ck_policy_monthly_limit_positive",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_policy_grant_org_action_active", "policy_grants",
        ["organization_id", "action", "is_active"],
    )
    op.create_index(
        "ix_policy_grant_org_user", "policy_grants",
        ["organization_id", "user_id"],
    )

    op.add_column(
        "irreversible_action_requests",
        sa.Column("origin_channel", sa.String(length=30), nullable=False,
                  server_default="internal"),
    )
    op.add_column(
        "irreversible_action_requests",
        sa.Column("policy_proposed_decision", sa.JSON(), nullable=True),
    )
    op.add_column(
        "irreversible_action_requests",
        sa.Column("policy_approved_decision", sa.JSON(), nullable=True),
    )
    op.add_column(
        "irreversible_action_requests",
        sa.Column("policy_execution_decision", sa.JSON(), nullable=True),
    )

    op.create_table(
        "irreversible_action_approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("approved_by_user_id", sa.Integer(), nullable=False),
        sa.Column("authority_id", sa.Integer(), nullable=False),
        sa.Column("authority_type", sa.String(length=30), nullable=False),
        sa.Column("policy_decision", sa.JSON(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["irreversible_action_requests.id"]),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["authority_id"], ["organization_signing_authorities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_id", "approved_by_user_id",
            name="uq_action_approval_request_user",
        ),
    )
    op.create_index(
        "ix_action_approval_org_request", "irreversible_action_approvals",
        ["organization_id", "request_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_action_approval_org_request",
                  table_name="irreversible_action_approvals")
    op.drop_table("irreversible_action_approvals")
    op.drop_column("irreversible_action_requests", "policy_execution_decision")
    op.drop_column("irreversible_action_requests", "policy_approved_decision")
    op.drop_column("irreversible_action_requests", "policy_proposed_decision")
    op.drop_column("irreversible_action_requests", "origin_channel")
    op.drop_index("ix_policy_grant_org_user", table_name="policy_grants")
    op.drop_index("ix_policy_grant_org_action_active", table_name="policy_grants")
    op.drop_table("policy_grants")
