"""Coverage boundary and one active Open Finance connection per org.

Not applied to production. Gate 0 still requires an owner-approved repair.
SQLite cannot ALTER a foreign key, so superseded_by_id is an audit pointer
with no database constraint. The external-id check is added in batch mode.
"""
from alembic import op
import sqlalchemy as sa

revision = "e03f5b21c7d4"
down_revision = "d92e4a10b6c3"
branch_labels = None
depends_on = None

_ACTIVE_OF = "source = 'open_finance' AND status IN ('ACTIVE', 'CONNECTED', 'COMPLETED')"


def upgrade():
    with op.batch_alter_table("bank_transactions") as batch:
        batch.add_column(sa.Column("superseded_by_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("content_fingerprint", sa.String(length=64), nullable=True))
        batch.create_check_constraint(
            "ck_banktx_source_external_id",
            "source = 'manual' OR external_id IS NOT NULL",
        )
    op.create_index(
        "uq_bankconn_source_connection_id",
        "bank_connections",
        ["source", "connection_id"],
        unique=True,
        postgresql_where=sa.text("connection_id IS NOT NULL"),
        sqlite_where=sa.text("connection_id IS NOT NULL"),
    )
    op.create_index(
        "uq_bankconn_one_active_open_finance",
        "bank_connections",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_OF),
        sqlite_where=sa.text(_ACTIVE_OF),
    )
    op.create_table(
        "account_source_coverage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("local_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("covers_from", sa.Date(), nullable=False),
        sa.Column("bank_account_suffix", sa.String(length=20), nullable=True),
        sa.Column("superseded_by_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "organization_id", "local_account_id", "source",
            name="uq_account_source_coverage",
        ),
    )
    op.create_index(
        "ix_account_source_coverage_org",
        "account_source_coverage",
        ["organization_id"],
    )


def downgrade():
    op.drop_index("ix_account_source_coverage_org", table_name="account_source_coverage")
    op.drop_table("account_source_coverage")
    op.drop_index("uq_bankconn_one_active_open_finance", table_name="bank_connections")
    op.drop_index("uq_bankconn_source_connection_id", table_name="bank_connections")
    with op.batch_alter_table("bank_transactions") as batch:
        batch.drop_constraint("ck_banktx_source_external_id", type_="check")
        batch.drop_column("content_fingerprint")
        batch.drop_column("superseded_by_id")
