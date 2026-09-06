"""Persist reviewed invoice, receipt and bank allocations.
Revision ID: 62b80d39f715
Revises: 51a79c28e604
"""
from alembic import op
import sqlalchemy as sa
revision = '62b80d39f715'
down_revision = '51a79c28e604'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('collection_payment_allocations',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('organization_id',sa.Integer(),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('request_id',sa.Integer(),sa.ForeignKey('irreversible_action_requests.id'),nullable=False,unique=True),
        sa.Column('invoice_id',sa.Integer(),sa.ForeignKey('invoices.id'),nullable=False),
        sa.Column('payment_id',sa.Integer(),sa.ForeignKey('payments.id'),nullable=False,unique=True),
        sa.Column('bank_transaction_id',sa.Integer(),sa.ForeignKey('bank_transactions.id'),nullable=False,unique=True),
        sa.Column('amount',sa.Numeric(12,2),nullable=False),
        sa.Column('currency',sa.String(10),nullable=False),
        sa.Column('document_external_id',sa.String(255),nullable=False),
        sa.Column('decided_by_user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('evidence',sa.JSON(),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False))
    op.create_index('ix_collection_allocation_org_invoice','collection_payment_allocations',['organization_id','invoice_id'])


def downgrade():
    op.drop_table('collection_payment_allocations')
