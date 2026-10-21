"""Explicit Open Finance account classification against local imports.

Not applied to production. Gate 0 still requires an owner-approved repair.
``UNCLASSIFIED`` is the absence of a row. ``BOUND`` and ``INDEPENDENT``
are written here.
"""
from alembic import op
import sqlalchemy as sa

revision = "h26c8e54f1b2"
down_revision = "e03f5b21c7d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "of_account_classifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("coverage_id", sa.Integer(), sa.ForeignKey("account_source_coverage.id"), nullable=True),
        sa.Column("classified_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("classified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("account_id", name="uq_of_class_account"),
        sa.CheckConstraint(
            "state IN ('BOUND', 'INDEPENDENT', 'UNCLASSIFIED')",
            name="ck_of_class_state",
        ),
        sa.CheckConstraint(
            "(state = 'BOUND') = (coverage_id IS NOT NULL)",
            name="ck_of_class_bound_coverage",
        ),
        sa.CheckConstraint(
            "state <> 'INDEPENDENT' OR classified_by_user_id IS NOT NULL",
            name="ck_of_class_independent_actor",
        ),
    )
    op.create_index("ix_of_class_org", "of_account_classifications", ["organization_id"])


def downgrade():
    op.drop_index("ix_of_class_org", table_name="of_account_classifications")
    op.drop_table("of_account_classifications")
