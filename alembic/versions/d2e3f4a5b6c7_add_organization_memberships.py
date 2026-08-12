"""חברות רב-ארגונית — organization_memberships

`User.organization_id` הוא FK יחיד, ולכן אדם יכול היה להשתייך לארגון אחד
בלבד. הטבלה הזו מפרידה בין מי האדם לבין במה הוא חבר ובאיזה תפקיד.

**ה-backfill אינו מנחש בעלות.** הוא מעתיק אך ורק את מה שכבר רשום בפועל:
לכל משתמש פעיל עם `organization_id`, נוצרת חברות `active` עם **אותו
תפקיד** שכבר יש לו. זו העברה של מצב קיים, לא הענקת הרשאה חדשה.

מה שה-backfill **אינו** עושה, במכוון:
- אינו נוגע ב-`organization_signing_authorities`. בעלות עסקית נשארת
  פעולת bootstrap מפורשת (`I_AM_AUTHORIZED_OWNER`) — מיגרציה שמעניקה
  סמכות חתימה היא בדיוק מה שאסור.
- אינו משייך משתמשים לפי מייל, דומיין או נתון מ-SUMIT.
- אינו נוגע ב-SUPER_ADMIN חסרי ארגון: אין להם ארגון להעתיק ממנו, והם
  בוחרים ארגון מפורשות (409 `active_organization_required`).

`users.organization_id` **נשאר** ואינו נמחק — הוא מקור ה-backfill ונשאר
fallback לקריאה עד שכל הקוראים יעברו.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-08-11
"""
from alembic import op
import sqlalchemy as sa


revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "SUPER_ADMIN", "ADMIN", "ACCOUNTANT", "MANAGER", "USER", "VIEWER",
                name="userrole",
            ),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="invited"),
        sa.Column("invited_by_user_id", sa.Integer(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.Integer(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "organization_id",
                            name="uq_membership_user_org"),
    )
    op.create_index("ix_membership_user_status", "organization_memberships",
                    ["user_id", "status"])
    op.create_index("ix_membership_org_status", "organization_memberships",
                    ["organization_id", "status"])

    # --- backfill: מצב קיים בלבד ------------------------------------- #
    # `invited_by_user_id` נשאר NULL במכוון: אף אדם לא הזמין את החברויות
    # האלה — הן נגזרות ממצב שקדם למודל. NULL כאן הוא התיעוד הכן; שיוך
    # למשתמש שרירותי היה מייצר אחריות מזויפת.
    op.execute(
        """
        INSERT INTO organization_memberships
            (organization_id, user_id, role, status, verified_at,
             created_at, updated_at)
        SELECT u.organization_id, u.id, u.role, 'active',
               CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM users u
        WHERE u.organization_id IS NOT NULL
          AND u.is_active = true
        """
    )


def downgrade() -> None:
    # `users.organization_id` לא נגעה, ולכן הסרת הטבלה מחזירה את
    # ההתנהגות הקודמת בדיוק.
    op.drop_index("ix_membership_org_status", table_name="organization_memberships")
    op.drop_index("ix_membership_user_status", table_name="organization_memberships")
    op.drop_table("organization_memberships")
