"""add morning_briefs table + org morning-brief opt-in columns (PR5 of bookkeeper daily-cycle plan)

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-07-20 00:00:00.000002

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'morning_briefs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('brief_date', sa.Date(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=10), nullable=True),
        sa.Column('delivered_channels', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_unique_constraint(
        'uq_morning_brief_org_date', 'morning_briefs', ['organization_id', 'brief_date'],
    )
    op.add_column('organizations', sa.Column(
        'morning_brief_email_enabled', sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column('organizations', sa.Column('morning_brief_recipients', sa.String(length=500), nullable=True))
    op.add_column('organizations', sa.Column(
        'morning_brief_sms_enabled', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column('organizations', 'morning_brief_sms_enabled')
    op.drop_column('organizations', 'morning_brief_recipients')
    op.drop_column('organizations', 'morning_brief_email_enabled')
    op.drop_constraint('uq_morning_brief_org_date', 'morning_briefs', type_='unique')
    op.drop_table('morning_briefs')
