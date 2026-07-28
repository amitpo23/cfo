"""add channel identity, link code, and processed-update dedupe tables

Revision ID: f2a3b4c5d6e7
Revises: e6f7a8b9c0d1
Create Date: 2026-07-26 09:00:00.000000

Conversational channels (Telegram first) package 3 — decision 6/7 in
docs/superpowers/plans/2026-07-26-conversational-channels-personas.md.
Additive and idempotent, matching the convention set by
d5e6f7a8b9c0_add_irreversible_action_control.py: a table is created only if
missing, so a database that already has these tables via ``create_all``
(pre-Alembic drift) is left alone.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()

    if "channel_identities" not in tables:
        op.create_table(
            "channel_identities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "organization_id", sa.Integer(),
                sa.ForeignKey("organizations.id"), nullable=False,
            ),
            sa.Column(
                "user_id", sa.Integer(),
                sa.ForeignKey("users.id"), nullable=False,
            ),
            sa.Column("provider", sa.String(length=20), nullable=False),
            sa.Column("external_id", sa.String(length=64), nullable=False),
            sa.Column("display_name", sa.String(length=120), nullable=True),
            sa.Column(
                "default_persona", sa.String(length=20),
                nullable=True, server_default="cfo",
            ),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "provider", "external_id",
                name="uq_channel_identity_provider_external",
            ),
        )
        op.create_index(
            "ix_channel_identities_organization_id",
            "channel_identities", ["organization_id"], unique=False,
        )

    if "channel_link_codes" not in tables:
        op.create_table(
            "channel_link_codes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "organization_id", sa.Integer(),
                sa.ForeignKey("organizations.id"), nullable=False,
            ),
            sa.Column(
                "user_id", sa.Integer(),
                sa.ForeignKey("users.id"), nullable=False,
            ),
            sa.Column("code_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "ix_channel_link_codes_code_hash",
            "channel_link_codes", ["code_hash"], unique=False,
        )

    if "channel_processed_updates" not in tables:
        op.create_table(
            "channel_processed_updates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("provider", sa.String(length=20), nullable=False),
            sa.Column("update_id", sa.String(length=64), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "provider", "update_id",
                name="uq_channel_processed_update",
            ),
        )


def downgrade() -> None:
    tables = _tables()
    if "channel_processed_updates" in tables:
        op.drop_table("channel_processed_updates")
    if "channel_link_codes" in tables:
        op.drop_table("channel_link_codes")
    if "channel_identities" in tables:
        op.drop_table("channel_identities")
