"""Medici auth port: dashboard email grants + one-time Google login codes.

Additive only. Two new tables; no existing column changes. Not applied to
production — deploy only via docs/GATE0_DEPLOYMENT_RUNBOOK.md.
"""
from alembic import op
import sqlalchemy as sa

revision = "h16a2c5e7b9d1"
down_revision = "g15b7d43e9f0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dashboard_access_grants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dashboard_id", sa.Integer(), sa.ForeignKey("client_dashboards.id"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="client_viewer"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="invited"),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="rezef"),
        sa.Column("granted_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint("dashboard_id", "email", name="uq_dashboard_grant_email"),
        sa.CheckConstraint(
            "role IN ('client_viewer','client_editor')", name="ck_dashboard_grant_role",
        ),
        sa.CheckConstraint(
            "status IN ('invited','active','revoked')", name="ck_dashboard_grant_status",
        ),
    )
    op.create_index(
        "ix_dashboard_grant_email_status", "dashboard_access_grants", ["email", "status"],
    )
    op.create_index("ix_dashboard_grant_user", "dashboard_access_grants", ["user_id"])

    op.create_table(
        "auth_login_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("browser_binding", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code_hash", name="uq_auth_login_code_hash"),
    )


def downgrade():
    op.drop_table("auth_login_codes")
    op.drop_index("ix_dashboard_grant_user", table_name="dashboard_access_grants")
    op.drop_index("ix_dashboard_grant_email_status", table_name="dashboard_access_grants")
    op.drop_table("dashboard_access_grants")
