"""add contact withholding_rate (form 856 supplier withholding)

Revision ID: 4e5f6a7b8c9d
Revises: 3d4e5f6a7b8c
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa


revision = "4e5f6a7b8c9d"
down_revision = "3d4e5f6a7b8c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("contacts", sa.Column(
        "withholding_rate", sa.Numeric(precision=5, scale=4), nullable=True))


def downgrade():
    op.drop_column("contacts", "withholding_rate")
