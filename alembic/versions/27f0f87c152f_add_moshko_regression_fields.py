"""W1.5 — regression runner: תוצאת ריצה אחרונה על moshko_gaps.

מקרה רגרסיה אינו טבלה נפרדת — כל שורת moshko_gaps עם promoted_memory_id
לא-ריק *היא* מקרה רגרסיה (השאלה המקורית + הזיכרון שקודם ממנה). שתי
עמודות בלבד: תוצאת ההרצה האחרונה ומועדה.

Revision ID: 27f0f87c152f
Revises: 7f6e5d4c3b2a
Create Date: 2026-08-22
"""
import sqlalchemy as sa
from alembic import op

revision = "27f0f87c152f"
down_revision = "7f6e5d4c3b2a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("moshko_gaps") as batch:
        batch.add_column(sa.Column("regression_status", sa.String(length=10), nullable=True))
        batch.add_column(sa.Column("regression_checked_at", sa.DateTime(), nullable=True))
        batch.create_check_constraint(
            "ck_moshko_gaps_regression_status",
            "regression_status IN ('passed','failed')",
        )


def downgrade() -> None:
    with op.batch_alter_table("moshko_gaps") as batch:
        batch.drop_constraint("ck_moshko_gaps_regression_status", type_="check")
        batch.drop_column("regression_checked_at")
        batch.drop_column("regression_status")
