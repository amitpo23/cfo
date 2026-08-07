"""add Moshko observability tables and WhatsApp service-window clock

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-08-01 10:00:00.000000

Additive only. No backfill and no provider or production access.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    if "llm_usage" not in _tables():
        op.create_table(
            "llm_usage",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("session_id", sa.String(length=128), nullable=True),
            sa.Column("provider", sa.String(length=30), nullable=False),
            sa.Column("model", sa.String(length=120), nullable=False),
            sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cache_read_input_tokens", sa.Integer(), nullable=True),
            sa.Column("cache_creation_input_tokens", sa.Integer(), nullable=True),
            sa.Column("cost_usd", sa.Numeric(18, 8), nullable=True),
            sa.Column("purpose", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_llm_usage_org_created", "llm_usage", ["organization_id", "created_at"])
        op.create_index("ix_llm_usage_session", "llm_usage", ["session_id"])

    if "moshko_tool_calls" not in _tables():
        op.create_table(
            "moshko_tool_calls",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("session_id", sa.String(length=128), nullable=False),
            sa.Column("message_id", sa.Integer(), sa.ForeignKey("ai_chat_messages.id"), nullable=True),
            sa.Column("tool_name", sa.String(length=100), nullable=False),
            sa.Column("target_system", sa.String(length=30), nullable=False),
            sa.Column("arguments", sa.JSON(), nullable=False),
            sa.Column("succeeded", sa.Boolean(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("result_size_bytes", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_moshko_tool_calls_org_created", "moshko_tool_calls", ["organization_id", "created_at"]
        )
        op.create_index("ix_moshko_tool_calls_session", "moshko_tool_calls", ["session_id"])
        op.create_index(
            "ix_moshko_tool_calls_target_success", "moshko_tool_calls", ["target_system", "succeeded"]
        )

    if "last_inbound_at" not in _columns("channel_identities"):
        op.add_column(
            "channel_identities",
            sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if "last_inbound_at" in _columns("channel_identities"):
        op.drop_column("channel_identities", "last_inbound_at")
    if "moshko_tool_calls" in _tables():
        op.drop_table("moshko_tool_calls")
    if "llm_usage" in _tables():
        op.drop_table("llm_usage")
