"""add collection reminders + org opt-in"""
from alembic import op
import sqlalchemy as sa

revision = "c0ffee010203"
down_revision = "5f6a7b8c9d0e"  # a current head; run `alembic merge heads` if needed
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "collection_reminders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id"), nullable=True),
        sa.Column("invoice_numbers", sa.String(500), nullable=True),
        sa.Column("reminder_type", sa.String(20), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), server_default="0"),
        sa.Column("days_overdue", sa.Integer, server_default="0"),
        sa.Column("status", sa.String(20), server_default="sent"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("sent_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_collreminder_org_contact", "collection_reminders",
                    ["organization_id", "contact_id"])
    op.add_column("organizations", sa.Column(
        "collection_reminders_enabled", sa.Boolean, server_default=sa.false(), nullable=False))
    op.add_column("organizations", sa.Column("collection_sms_sender", sa.String(20), nullable=True))

def downgrade():
    op.drop_column("organizations", "collection_sms_sender")
    op.drop_column("organizations", "collection_reminders_enabled")
    op.drop_index("ix_collreminder_org_contact", table_name="collection_reminders")
    op.drop_table("collection_reminders")
