"""One BOUND classification per coverage.

Not applied to production. Gate 0 still requires an owner-approved repair.
``h26c8e54f1b2`` is already applied on review databases, so the partial
unique index is its own revision rather than an edit of that upgrade.
"""
from alembic import op
import sqlalchemy as sa


revision = "i27c9e65a3d4"
down_revision = "h26c8e54f1b2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "uq_of_class_coverage",
        "of_account_classifications",
        ["coverage_id"],
        unique=True,
        postgresql_where=sa.text("state = 'BOUND'"),
        sqlite_where=sa.text("state = 'BOUND'"),
    )


def downgrade():
    op.drop_index("uq_of_class_coverage", table_name="of_account_classifications")
