"""add tenant_databases — מיפוי ארגון→מסד ייעודי (DB פר-ארגון, שלב 1)

Revision ID: a9b0c1d2e3f4
Revises: e7f8a9b0c1d2
Create Date: 2026-08-09 10:30:00.000000

Additive only. הטבלה נוצרת ריקה: ארגון בלי שורה כאן ממשיך לעבוד מול
המסד המשותף בדיוק כמו היום, ולכן המיגרציה אינה משנה שום התנהגות קיימת.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


_REQUIRED_COLUMNS = {
    "id", "organization_id", "dsn_encrypted", "provider", "status",
    "schema_revision", "last_verified_at", "notes", "created_at", "updated_at",
}


def upgrade() -> None:
    if "tenant_databases" in _tables():
        # קיום שם הטבלה אינו הוכחה שהיא שלמה. טבלה חלקית שנוצרה בריצה
        # שקרסה באמצע הייתה גורמת ל-alembic לסמן את ה-revision כמוצלח,
        # בעוד `compute_missing` (שבודק טבלאות ועמודות בלבד) לא היה תופס
        # אילוץ או אינדקס חסר (Codex QA 09/08). לכן נכשלים במפורש.
        existing = {
            column["name"]
            for column in sa.inspect(op.get_bind()).get_columns("tenant_databases")
        }
        missing = _REQUIRED_COLUMNS - existing
        if missing:
            raise RuntimeError(
                "tenant_databases קיימת אך חסרות בה עמודות: "
                f"{', '.join(sorted(missing))}. יש לתקן ידנית לפני המשך."
            )
        return

    op.create_table(
        "tenant_databases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("dsn_encrypted", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False, server_default="neon"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("schema_revision", sa.String(length=64), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_tenant_databases_status", "tenant_databases", ["status"])


def downgrade() -> None:
    if "tenant_databases" in _tables():
        op.drop_table("tenant_databases")
