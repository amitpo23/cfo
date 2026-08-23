"""Add the JWT session-revocation version to users.

Existing users start at version 0. Consequently, legacy JWTs without a
``token_version`` claim remain valid only until that user's first password
change or reset; every such operation increments the stored version.

Revision ID: 3f8c2a1d9e70
Revises: 27f0f87c152f
Create Date: 2026-08-23
"""
import sqlalchemy as sa
from alembic import op

revision = "3f8c2a1d9e70"
down_revision = "27f0f87c152f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column(
            "token_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("token_version")
