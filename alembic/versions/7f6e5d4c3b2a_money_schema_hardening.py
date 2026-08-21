"""W6.4 — חיזוק סכימת הכסף: NOT NULL+default, אינדקסים, ייחודיות הוצאות.

Revision ID: 7f6e5d4c3b2a
Revises: b8c9d0e1f2a3
Create Date: 2026-08-21

לפני האילוץ — עדכון NULL→0 (נתוני פרוד חייבים לעמוד באילוץ לפני אכיפתו).
אין אילוצי סימן בכוונה: זיכוי ספק שלילי לגיטימי.
"""
import sqlalchemy as sa
from alembic import op

revision = "7f6e5d4c3b2a"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None

_MONEY = ("subtotal", "tax", "total", "paid_amount", "balance")


def upgrade() -> None:
    for table in ("invoices", "bills"):
        for col in _MONEY:
            op.execute(f"UPDATE {table} SET {col} = 0 WHERE {col} IS NULL")
        # batch: על SQLite‏ ALTER COLUMN לא נתמך — הטבלה נבנית מחדש
        with op.batch_alter_table(table) as batch:
            for col in _MONEY:
                batch.alter_column(
                    col,
                    existing_type=sa.Numeric(12, 2),
                    nullable=False,
                    server_default=sa.text("0"),
                )

    op.create_index(
        "ix_je_org_entry_date", "journal_entries",
        ["organization_id", "entry_date"],
    )
    op.create_index("ix_payment_invoice", "payments", ["invoice_id"])
    op.create_index("ix_payment_bill", "payments", ["bill_id"])
    op.create_index(
        "ix_payment_org_date", "payments", ["organization_id", "payment_date"],
    )
    op.create_index("ix_transaction_org", "transactions", ["organization_id"])

    # ההוצאות: האינדקס הקיים לא היה unique — מוחלף ב-partial unique.
    op.drop_index("ix_expense_org_ext", table_name="expenses")
    op.create_index(
        "ix_expense_org_ext", "expenses",
        ["organization_id", "external_id", "source"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
        sqlite_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_expense_org_ext", table_name="expenses")
    op.create_index(
        "ix_expense_org_ext", "expenses",
        ["organization_id", "external_id", "source"],
    )
    op.drop_index("ix_transaction_org", table_name="transactions")
    op.drop_index("ix_payment_org_date", table_name="payments")
    op.drop_index("ix_payment_bill", table_name="payments")
    op.drop_index("ix_payment_invoice", table_name="payments")
    op.drop_index("ix_je_org_entry_date", table_name="journal_entries")
    for table in ("invoices", "bills"):
        with op.batch_alter_table(table) as batch:
            for col in _MONEY:
                batch.alter_column(
                    col,
                    existing_type=sa.Numeric(12, 2),
                    nullable=True,
                    server_default=None,
                )
