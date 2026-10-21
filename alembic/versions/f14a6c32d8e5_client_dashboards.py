"""Client dashboards, plans, snapshots, share links, and pipeline runs.

Not applied to production. Gate 0 still requires an owner-approved repair.
"""
from alembic import op
import sqlalchemy as sa

revision = "f14a6c32d8e5"
down_revision = "i27c9e65a3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "client_dashboards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=48), nullable=False, unique=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("primary_organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("office_organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("template", sa.String(length=32), nullable=False, server_default="generic"),
        sa.Column("access_mode", sa.String(length=20), nullable=False, server_default="link"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("current_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("access_mode IN ('members','link','public')", name="ck_dashboard_access_mode"),
        sa.CheckConstraint("status IN ('draft','active','paused','archived')", name="ck_dashboard_status"),
        sa.CheckConstraint("template IN ('generic','restaurant','services')", name="ck_dashboard_template"),
    )
    op.create_index("ix_dashboard_primary_org", "client_dashboards", ["primary_organization_id"])
    op.create_table(
        "dashboard_entities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dashboard_id", sa.Integer(), sa.ForeignKey("client_dashboards.id"), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.CheckConstraint("role IN ('primary','related')", name="ck_dashboard_entity_role"),
        sa.UniqueConstraint("dashboard_id", "organization_id", name="uq_dashboard_entity_org"),
    )
    op.create_table(
        "dashboard_entity_accounts",
        sa.Column("entity_id", sa.Integer(), sa.ForeignKey("dashboard_entities.id"), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), primary_key=True),
        sa.Column("display_label", sa.String(length=255), nullable=True),
    )
    op.create_table(
        "dashboard_members",
        sa.Column("dashboard_id", sa.Integer(), sa.ForeignKey("client_dashboards.id"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "role IN ('owner','accountant','client_editor','client_viewer')",
            name="ck_dashboard_member_role",
        ),
        sa.CheckConstraint("status IN ('invited','active','revoked')", name="ck_dashboard_member_status"),
    )
    op.create_table(
        "dashboard_share_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dashboard_id", sa.Integer(), sa.ForeignKey("client_dashboards.id"), nullable=False),
        sa.Column("token_sha256", sa.String(length=64), nullable=False, unique=True),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("scope", sa.String(length=40), nullable=False, server_default="snapshot_read"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "dashboard_plans",
        sa.Column("dashboard_id", sa.Integer(), sa.ForeignKey("client_dashboards.id"), primary_key=True),
        sa.Column("version", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_table(
        "dashboard_plan_revisions",
        sa.Column("version", sa.String(length=36), primary_key=True),
        sa.Column("dashboard_id", sa.Integer(), sa.ForeignKey("client_dashboards.id"), nullable=False),
        sa.Column("previous_version", sa.String(length=36), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.Column("changed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.UniqueConstraint("dashboard_id", "previous_version", name="uq_dashboard_plan_previous"),
    )
    op.create_table(
        "published_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dashboard_id", sa.Integer(), sa.ForeignKey("client_dashboards.id"), nullable=False),
        sa.Column("refreshed_day", sa.Date(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(), nullable=False),
        sa.Column("plan_version", sa.String(length=36), nullable=True),
        sa.Column("view_model", sa.JSON(), nullable=False),
        sa.Column("freshness", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("provider_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("provider_calls = 0", name="ck_snapshot_provider_calls"),
        sa.UniqueConstraint("dashboard_id", "refreshed_day", name="uq_snapshot_dashboard_day"),
    )
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("run_day", sa.Date(), nullable=False),
        sa.Column("step", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("counts", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','skipped','uncertain')",
            name="ck_pipeline_run_status",
        ),
        sa.UniqueConstraint("organization_id", "run_day", "step", name="uq_pipeline_run_org_day_step"),
    )


def downgrade():
    op.drop_table("pipeline_runs")
    op.drop_table("published_snapshots")
    op.drop_table("dashboard_plan_revisions")
    op.drop_table("dashboard_plans")
    op.drop_table("dashboard_share_links")
    op.drop_table("dashboard_members")
    op.drop_table("dashboard_entity_accounts")
    op.drop_table("dashboard_entities")
    op.drop_index("ix_dashboard_primary_org", table_name="client_dashboards")
    op.drop_table("client_dashboards")
