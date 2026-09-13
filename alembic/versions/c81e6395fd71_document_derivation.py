"""Preserve explicit PDF page recipes and their source identities."""
from alembic import op
import sqlalchemy as sa

revision = 'c81e6395fd71'
down_revision = 'b70d5284ec60'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('document_derivations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('recipe_hash', sa.String(64), nullable=False),
        sa.Column('recipe', sa.JSON(), nullable=False),
        sa.Column('outputs', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('organization_id', 'recipe_hash', name='uq_document_derivation_recipe'))


def downgrade():
    raise RuntimeError('Page provenance requires preservation; use a forward repair')
