"""add owner/signatory policy and irreversible-action lifecycle

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-07-25 18:40:00.000000

Additive and idempotent because older deployments may have created model
tables through ``create_all`` without recording this Alembic revision.
Existing organizations are intentionally not assigned an owner by guesswork;
an authenticated organization admin must perform the explicit one-time
bootstrap flow.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _indexes(table_name: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    }


def upgrade() -> None:
    tables = _tables()
    if "organization_signing_authorities" not in tables:
        op.create_table(
            "organization_signing_authorities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "organization_id",
                sa.Integer(),
                sa.ForeignKey("organizations.id"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column(
                "authority_type",
                sa.String(length=30),
                nullable=False,
            ),
            sa.Column("action_types", sa.JSON(), nullable=False),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "granted_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column(
                "revoked_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "revoked_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.UniqueConstraint(
                "organization_id",
                "user_id",
                name="uq_signing_authority_org_user",
            ),
        )
        op.create_index(
            "ix_signing_authority_org_active",
            "organization_signing_authorities",
            ["organization_id", "is_active"],
            unique=False,
        )

    tables = _tables()
    if "irreversible_action_requests" not in tables:
        op.create_table(
            "irreversible_action_requests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "organization_id",
                sa.Integer(),
                sa.ForeignKey("organizations.id"),
                nullable=False,
            ),
            sa.Column("action_type", sa.String(length=50), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("payload_sha256", sa.String(length=64), nullable=False),
            sa.Column(
                "idempotency_key",
                sa.String(length=160),
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.String(length=24),
                nullable=False,
                server_default="proposed",
            ),
            sa.Column(
                "proposed_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column(
                "approved_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
            sa.Column("approver_role", sa.String(length=30), nullable=True),
            sa.Column(
                "approved_by_authority_id",
                sa.Integer(),
                sa.ForeignKey("organization_signing_authorities.id"),
                nullable=True,
            ),
            sa.Column(
                "approver_authority_type",
                sa.String(length=30),
                nullable=True,
            ),
            sa.Column("provider_reference", sa.String(length=255), nullable=True),
            sa.Column("execution_result", sa.JSON(), nullable=True),
            sa.Column("verification_evidence", sa.JSON(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column(
                "proposed_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "execution_started_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "organization_id",
                "idempotency_key",
                name="uq_irreversible_action_org_idempotency",
            ),
        )
        op.create_index(
            "ix_irreversible_action_org_status",
            "irreversible_action_requests",
            ["organization_id", "status"],
            unique=False,
        )
    else:
        columns = _columns("irreversible_action_requests")
        if "approved_by_authority_id" not in columns:
            op.add_column(
                "irreversible_action_requests",
                sa.Column(
                    "approved_by_authority_id",
                    sa.Integer(),
                    sa.ForeignKey("organization_signing_authorities.id"),
                    nullable=True,
                ),
            )
        if "approver_authority_type" not in columns:
            op.add_column(
                "irreversible_action_requests",
                sa.Column(
                    "approver_authority_type",
                    sa.String(length=30),
                    nullable=True,
                ),
            )
        indexes = _indexes("irreversible_action_requests")
        if "ix_irreversible_action_org_status" not in indexes:
            op.create_index(
                "ix_irreversible_action_org_status",
                "irreversible_action_requests",
                ["organization_id", "status"],
                unique=False,
            )


def downgrade() -> None:
    tables = _tables()
    if "irreversible_action_requests" in tables:
        op.drop_table("irreversible_action_requests")
    if "organization_signing_authorities" in tables:
        op.drop_table("organization_signing_authorities")
