"""Persist report configuration and result evidence within each organization."""
from alembic import op
import sqlalchemy as sa

revision = 'b70d5284ec60'
down_revision = 'a6fc4173db59'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('report_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('reference', sa.String(255), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('deleted', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('organization_id', 'kind', 'reference', name='uq_report_record_org_kind_ref'))


def downgrade():
    raise RuntimeError('Report evidence requires a preservation plan; use a forward repair')
