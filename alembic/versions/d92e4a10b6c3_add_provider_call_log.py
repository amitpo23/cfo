"""Append-only SUMIT/provider call ledger. No bodies, no credentials."""
from alembic import op
import sqlalchemy as sa

revision = "d92e4a10b6c3"
down_revision = "c81e6395fd71"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "provider_call_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("office_organization_id", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("endpoint_class", sa.String(length=20), nullable=False),
        sa.Column("endpoint", sa.String(length=200), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('sync','filing','quota','ops','webhook_followup','unspecified')",
            name="ck_provider_call_purpose",
        ),
        sa.CheckConstraint(
            "endpoint_class IN ('free','inferred','paid')",
            name="ck_provider_call_endpoint_class",
        ),
    )
    op.create_index(
        "ix_provider_call_org_at",
        "provider_call_log",
        ["provider", "organization_id", "at"],
    )


def downgrade():
    op.drop_index("ix_provider_call_org_at", table_name="provider_call_log")
    op.drop_table("provider_call_log")
