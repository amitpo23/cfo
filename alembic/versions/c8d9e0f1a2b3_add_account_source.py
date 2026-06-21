"""add source column + unique index to accounts (SUMIT/Open Finance coexistence)

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-06-16 07:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8d9e0f1a2b3'
down_revision: Union[str, None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('accounts', sa.Column('source', sa.String(length=50),
                                        nullable=True, server_default='manual'))
    op.execute("UPDATE accounts SET source = 'manual' WHERE source IS NULL")
    op.create_index(
        'ix_account_org_ext_source', 'accounts',
        ['organization_id', 'external_id', 'source'], unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_account_org_ext_source', table_name='accounts')
    op.drop_column('accounts', 'source')
