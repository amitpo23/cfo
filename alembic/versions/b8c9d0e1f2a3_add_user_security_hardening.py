"""W6.7 — הקשחת ניהול משתמשים: נעילת login, איפוס סיסמה וביטול טוקנים.

- users.failed_login_attempts + users.locked_until — נעילה אחרי 5 כישלונות.
- password_reset_tokens — טוקן איפוס חד-פעמי (sha256, תוקף 30 דקות).
- revoked_tokens — denylist של jti לטוקנים שבוטלו ב-logout.

Revision ID: b8c9d0e1f2a3
Revises: 9a8b7c6d5e4f
Create Date: 2026-08-21
"""
import sqlalchemy as sa
from alembic import op

revision = "b8c9d0e1f2a3"
down_revision = "9a8b7c6d5e4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "failed_login_attempts", sa.Integer(),
            nullable=False, server_default="0",
        ),
    )
    op.add_column("users", sa.Column("locked_until", sa.DateTime(), nullable=True))

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id"), nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"],
    )
    op.create_index(
        "ix_password_reset_tokens_token_hash",
        "password_reset_tokens", ["token_hash"], unique=True,
    )

    op.create_table(
        "revoked_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_revoked_tokens_jti", "revoked_tokens", ["jti"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_revoked_tokens_jti", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
    op.drop_index(
        "ix_password_reset_tokens_token_hash", table_name="password_reset_tokens",
    )
    op.drop_index(
        "ix_password_reset_tokens_user_id", table_name="password_reset_tokens",
    )
    op.drop_table("password_reset_tokens")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
