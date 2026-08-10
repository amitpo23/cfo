"""add expenses.account_id — תיוק הוצאה לכרטיס באינדקס

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-08-10 10:50:00.000000

Additive only. העמודה nullable ומתחילה ריקה, ולכן אינה משנה שום
התנהגות קיימת: הוצאה בלי תיוק ממשיכה לעבוד בדיוק כמו היום.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, None] = "a9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("expenses")}


def upgrade() -> None:
    if "account_id" in _columns():
        return
    op.add_column("expenses", sa.Column("account_id", sa.Integer(), nullable=True))
    op.create_index("ix_expenses_account", "expenses", ["account_id"])
    # SQLite אינו תומך בהוספת FK ב-ALTER; בדיאלקטים אחרים האילוץ נאכף.
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_expenses_account", "expenses", "accounts", ["account_id"], ["id"]
        )


def downgrade() -> None:
    if "account_id" not in _columns():
        return
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_expenses_account", "expenses", type_="foreignkey")
    op.drop_index("ix_expenses_account", table_name="expenses")
    op.drop_column("expenses", "account_id")
