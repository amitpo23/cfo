"""add sync_checkpoints (M1a call-protection watermarks/circuit-breaker)"""
from alembic import op
import sqlalchemy as sa

revision = "a3b4c5d6e7f8"
down_revision = "d7ec33b9ee1e"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sync_checkpoints",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("last_success_at", sa.DateTime, nullable=True),
        sa.Column("cursor", sa.String(500), nullable=True),
        sa.Column("cooldown_until", sa.DateTime, nullable=True),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("circuit_open_until", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint(
            "organization_id", "source", "entity_type",
            name="uq_sync_checkpoint_org_source_entity",
        ),
    )


def downgrade():
    op.drop_table("sync_checkpoints")
