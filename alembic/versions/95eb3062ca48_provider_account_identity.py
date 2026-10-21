"""Preserve the exact provider account number for connected payment parties."""
from alembic import op
import sqlalchemy as sa

revision = '95eb3062ca48'
down_revision = '84da2f51b937'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('accounts', sa.Column('provider_account_number', sa.String(255), nullable=True))


def downgrade():
    raise RuntimeError('Provider identity evidence requires an explicit preservation plan; use a forward repair')
