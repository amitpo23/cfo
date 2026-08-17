"""Add the organization-scoped Moshko quality review queue.

Revision ID: 04b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa


revision = "04b5c6d7e8f9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "moshko_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False,
                  server_default="web"),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="open"),
        sa.Column("correction", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("promoted_memory_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "category IN ('helpful','inaccurate','unknown','unsafe')",
            name="ck_moshko_feedback_category",
        ),
        sa.CheckConstraint(
            "status IN ('open','reviewed','resolved','dismissed')",
            name="ck_moshko_feedback_status",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["ai_chat_messages.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["promoted_memory_id"], ["moshko_memory.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "message_id", name="uq_moshko_feedback_user_message",
        ),
    )
    op.create_index(
        "ix_moshko_feedback_org_status_created", "moshko_feedback",
        ["organization_id", "status", "created_at"],
    )
    op.create_index(
        "ix_moshko_feedback_category_created", "moshko_feedback",
        ["category", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_moshko_feedback_category_created", table_name="moshko_feedback",
    )
    op.drop_index(
        "ix_moshko_feedback_org_status_created", table_name="moshko_feedback",
    )
    op.drop_table("moshko_feedback")
