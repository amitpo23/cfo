"""Generalize existing receipt allocation edges; retain reversal evidence."""
from alembic import op
import sqlalchemy as sa

revision = '84da2f51b937'
down_revision = '73c91e40a826'
branch_labels = None
depends_on = None


def upgrade():
    table = 'collection_payment_allocations'
    constraints = sa.inspect(op.get_bind()).get_unique_constraints(table)
    with op.batch_alter_table(table, naming_convention={'uq': 'uq_%(table_name)s_%(column_0_name)s'}) as batch:
        for constraint in constraints:
            if constraint['column_names'] in [['request_id'], ['payment_id'], ['bank_transaction_id']]:
                name = constraint['name'] or f"uq_{table}_{constraint['column_names'][0]}"
                batch.drop_constraint(name, type_='unique')
        batch.alter_column('request_id', existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column('idempotency_key', sa.String(255), nullable=True))
        batch.add_column(sa.Column('status', sa.String(20), nullable=False, server_default='active'))
        batch.create_index('ix_collection_allocation_org_key', ['organization_id', 'idempotency_key'], unique=True)
        batch.create_index('ix_collection_allocation_org_payment', ['organization_id', 'payment_id'])
        batch.create_index('ix_collection_allocation_org_bank', ['organization_id', 'bank_transaction_id'])
    op.create_table('collection_allocation_reversals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('allocation_id', sa.Integer(), sa.ForeignKey(f'{table}.id'), nullable=False, unique=True),
        sa.Column('decided_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_collection_reversal_org', 'collection_allocation_reversals', ['organization_id'])


def downgrade():
    raise RuntimeError('Split allocations and reversal evidence require an explicit preservation plan; use a forward repair')
