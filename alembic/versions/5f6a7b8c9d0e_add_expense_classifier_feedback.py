"""add expense classifier_feedback (Phase 7 — classifier learning loop)

Revision ID: 5f6a7b8c9d0e
Revises: 4e5f6a7b8c9d
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa


revision = "5f6a7b8c9d0e"
down_revision = "4e5f6a7b8c9d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("expenses", sa.Column("classifier_feedback", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("expenses", "classifier_feedback")
