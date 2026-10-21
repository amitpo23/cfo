"""Preserve original documents independently from extracted expenses."""
from alembic import op
import sqlalchemy as sa

revision = 'a6fc4173db59'
down_revision = '95eb3062ca48'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('document_intakes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('content_base64', sa.Text(), nullable=False),
        sa.Column('media_type', sa.String(100), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('sources', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('result', sa.JSON()),
        sa.Column('expense_id', sa.Integer(), sa.ForeignKey('expenses.id')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('organization_id', 'content_hash', name='uq_document_intake_org_hash'))
    op.create_index('ix_document_intake_org_status', 'document_intakes', ['organization_id', 'status'])


def downgrade():
    raise RuntimeError('Source documents require a preservation plan; use a forward repair')
