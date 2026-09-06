"""Persist single-use checkout redemptions.

Revision ID: 51a79c28e604
Revises: 3f8c2a1d9e70
"""
from alembic import op
import sqlalchemy as sa
revision = '51a79c28e604'
down_revision = '3f8c2a1d9e70'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('billing_checkouts',
        sa.Column('session_id', sa.String(255), primary_key=True),
        sa.Column('email', sa.String(320), nullable=True),
        sa.Column('selected_plan', sa.String(64), nullable=False),
        sa.Column('payment_status', sa.String(32), nullable=False),
        sa.Column('webhook_created', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('subscription_id', sa.String(255), unique=True, nullable=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False))

    op.create_table('billing_webhook_receipts',
        sa.Column('event_id', sa.String(255), primary_key=True),
        sa.Column('payload_sha256', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))


def downgrade():
    op.drop_table('billing_webhook_receipts')
    op.drop_table('billing_checkouts')
