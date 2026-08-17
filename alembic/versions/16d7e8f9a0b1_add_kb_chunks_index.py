"""אינדקס מרכז הידע (kb_chunks) — אחזור למושקו ולתצוגה.

Revision ID: 16d7e8f9a0b1
Revises: 05c6d7e8f9a0
Create Date: 2026-08-17

הטבלה נזרעת מ-`kb_loader.KB_CENTERS` (מקור אמת יחיד, לא רישום שני) ומחליפה
סריקת regex על קבצי markdown בכל בקשה.

**אין עמודת embedding.** `vector` אמנם זמין ב-Neon, אבל ל-Anthropic אין API
של embeddings וספק נוסף הוא עלות שלא אושרה. עמודה ריקה בלי כותב נקראת
כיכולת קיימת בזמן שאינה — אם ייבחר ספק, זו revision נפרדת.

**האינדקס הטריגרמי הוא PostgreSQL בלבד.** ל-SQLite (סביבת הטסטים) אין
`pg_trgm`, ולכן הוא נוצר רק בדיאלקט PostgreSQL. גם `CREATE EXTENSION` עטוף
ב-try: אם ה-role של האפליקציה ב-Neon אינו רשאי ליצור הרחבות, המיגרציה
ממשיכה והאחזור נשען על ה-ILIKE + הדירוג בפייתון — פחות מהיר, לא שבור.
"""
from alembic import op
import sqlalchemy as sa


revision = "16d7e8f9a0b1"
down_revision = "05c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kb_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("center_key", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("section_index", sa.Integer(), nullable=False),
        sa.Column("heading", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("title_he", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        # זריעה חוזרת חייבת להיות upsert. בלי האילוץ הזה האינדקס היה גדל
        # בכל פריסה וכל חיפוש היה מחזיר את אותה פסקה שוב ושוב.
        sa.UniqueConstraint(
            "center_key", "filename", "section_index",
            name="uq_kb_chunk_center_file_section",
        ),
    )
    op.create_index(
        "ix_kb_chunk_center_file", "kb_chunks", ["center_key", "filename"],
    )

    if op.get_context().dialect.name == "postgresql":
        try:
            op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            op.execute(
                "CREATE INDEX IF NOT EXISTS ix_kb_chunk_content_trgm "
                "ON kb_chunks USING gin (content gin_trgm_ops)"
            )
        except Exception:  # pragma: no cover - תלוי בהרשאות ה-role ב-Neon
            # ההרחבה אינה זמינה ל-role הזה. האחזור עדיין עובד (ILIKE +
            # דירוג בפייתון); רק איטי יותר על אינדקס גדול.
            pass


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_kb_chunk_content_trgm")
    op.drop_index("ix_kb_chunk_center_file", table_name="kb_chunks")
    op.drop_table("kb_chunks")
