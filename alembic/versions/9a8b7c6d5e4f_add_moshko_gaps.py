"""W1.1 — תור הכישלונות/פערי-היכולת של מושקו (moshko_gaps).

Revision ID: 9a8b7c6d5e4f
Revises: a2b3c4d5e6f7
Create Date: 2026-08-20
"""
import sqlalchemy as sa
from alembic import op

revision = "9a8b7c6d5e4f"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "moshko_gaps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id", sa.Integer(),
            sa.ForeignKey("organizations.id"), nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column(
            "message_id", sa.Integer(),
            sa.ForeignKey("ai_chat_messages.id"), nullable=True,
        ),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("gap_kind", sa.String(length=30), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column(
            "promoted_memory_id", sa.Integer(),
            sa.ForeignKey("moshko_memory.id"), nullable=True,
        ),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "gap_kind IN ('tool_failed','model_gave_up','user_flagged')",
            name="ck_moshko_gaps_kind",
        ),
        sa.CheckConstraint(
            "status IN ('open','answered','dismissed')",
            name="ck_moshko_gaps_status",
        ),
    )
    op.create_index(
        "ix_moshko_gaps_org_status_created",
        "moshko_gaps",
        ["organization_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_moshko_gaps_org_status_created", table_name="moshko_gaps")
    op.drop_table("moshko_gaps")
