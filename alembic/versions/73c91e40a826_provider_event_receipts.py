"""Preserve distinct authenticated provider observations and conflicting events."""
from alembic import op
import sqlalchemy as sa

revision = '73c91e40a826'
down_revision = '62b80d39f715'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('provider_event_receipts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('source', sa.String(50), nullable=False),
        sa.Column('entity_type', sa.String(40), nullable=False),
        sa.Column('external_id', sa.String(255), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('disposition', sa.String(40), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.Column('observed_at', sa.DateTime(), nullable=False))
    op.create_index('ix_provider_event_org_fingerprint', 'provider_event_receipts',
        ['organization_id', 'source', 'fingerprint'], unique=True)
    op.create_index('ix_provider_event_org_entity', 'provider_event_receipts',
        ['organization_id', 'source', 'entity_type', 'external_id'])


def downgrade():
    op.drop_table('provider_event_receipts')
