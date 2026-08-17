"""add durable state for atomic AI-chat action confirmation

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-08-09 18:30:00.000000

Additive only.  Existing pending actions retain NULL action_status and are
treated by the service as legacy "pending" rows; no production data is
rewritten and no external action is triggered by this migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b0c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("ai_chat_messages")
    }


def _indexes() -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes("ai_chat_messages")
    }


def upgrade() -> None:
    columns = _columns()
    additions = (
        sa.Column("action_status", sa.String(length=20), nullable=True),
        sa.Column("action_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("action_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("action_error", sa.Text(), nullable=True),
    )
    for column in additions:
        if column.name not in columns:
            op.add_column("ai_chat_messages", column)

    if "ix_aichat_org_action_status" not in _indexes():
        op.create_index(
            "ix_aichat_org_action_status",
            "ai_chat_messages",
            ["organization_id", "action_status"],
        )


def downgrade() -> None:
    if "ix_aichat_org_action_status" in _indexes():
        op.drop_index("ix_aichat_org_action_status", table_name="ai_chat_messages")
    columns = _columns()
    for name in (
        "action_error",
        "action_completed_at",
        "action_claimed_at",
        "action_status",
    ):
        if name in columns:
            op.drop_column("ai_chat_messages", name)
