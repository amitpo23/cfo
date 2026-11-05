"""bank_match_decisions + bank_match_documents — the owner's bank match decisions.

Additive: two new tables, no change to an existing column. Replaces the
``bankMatchDecisions`` key that PR #103 kept in the dashboard plan JSON
(never merged, so there is no plan data to move).

Not applied to production. Apply with POST /api/admin/db/migrate after a pg_dump
restore point (docs/GATE0_DEPLOYMENT_RUNBOOK.md).

Revision ID: m50b2c3d4e5f
Revises: k40a1b2c3d4e
"""
from alembic import op
import sqlalchemy as sa

revision = "m50b2c3d4e5f"
down_revision = "k40a1b2c3d4e"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bank_match_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("bank_transaction_id", sa.Integer(), sa.ForeignKey("bank_transactions.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(20), nullable=True),
        sa.Column("category", sa.String(30), nullable=True),
        sa.Column("target_account", sa.String(40), nullable=True),
        sa.Column("fee_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("decided_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_bank_match_decision_txn", "bank_match_decisions",
                    ["organization_id", "bank_transaction_id"], unique=True)
    op.create_table(
        "bank_match_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("decision_id", sa.Integer(),
                  sa.ForeignKey("bank_match_decisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bank_transaction_id", sa.Integer(), sa.ForeignKey("bank_transactions.id"), nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
    )
    op.create_index("ix_bank_match_document_entity", "bank_match_documents",
                    ["organization_id", "entity_type", "entity_id"], unique=True)
    op.create_index("ix_bank_match_document_decision", "bank_match_documents", ["decision_id"])


def downgrade():
    op.drop_index("ix_bank_match_document_decision", table_name="bank_match_documents")
    op.drop_index("ix_bank_match_document_entity", table_name="bank_match_documents")
    op.drop_table("bank_match_documents")
    op.drop_index("ix_bank_match_decision_txn", table_name="bank_match_decisions")
    op.drop_table("bank_match_decisions")
