"""add ai_chat_messages table (Step 9 AI chatbot)

Revision ID: 3a8a9532010b
Revises: e4d8b1f6a2c9
Create Date: 2026-07-03 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3a8a9532010b'
down_revision: Union[str, None] = 'e4d8b1f6a2c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ai_chat_messages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('pending_action', sa.JSON(), nullable=True),
        sa.Column('executed', sa.Boolean(), server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_aichat_org_session', 'ai_chat_messages', ['organization_id', 'session_id'])


def downgrade() -> None:
    op.drop_index('ix_aichat_org_session', table_name='ai_chat_messages')
    op.drop_table('ai_chat_messages')
