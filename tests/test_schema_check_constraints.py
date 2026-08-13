"""חוזה הסכימה כולל CheckConstraints — ואי-אפשר לסמן head בלעדיהם.

`compute_schema_drift` בודק טבלאות, עמודות, טיפוסים, nullability, PK/FK,
unique ואינדקסים. הוא **אינו** בודק CheckConstraints.

זה חשוב במיוחד ל-`ck_membership_role_not_super_admin`: הוא מה שמונע
ממנהל ארגון להעניק חברות `SUPER_ADMIN` בתיק שלו ולעקוף את ההפרדה בין
מפעיל מערכת לבעל עסק. מסלול ה-repair יוצר טבלאות חסרות דרך
`apply_additive`, ואם ה-CHECK אינו נבדק — המסד מסומן `head` בעוד
ההגנה אינה קיימת בו בפועל.

הכלל: אילוץ CHECK חסר הוא drift, ו-drift חוסם את החתימה.
"""
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

from cfo.services.schema_deployment import (
    SchemaDeploymentError, reconcile_schema_to_head,
)
from cfo.services.schema_sync import compute_check_constraint_drift


REPO = Path(__file__).resolve().parents[1]
REQUIRED = ("organization_memberships", "ck_membership_role_not_super_admin")


def _alembic(db_path: Path, *args: str):
    r = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=REPO,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin",
             "DATABASE_URL": f"sqlite:///{db_path}", "HOME": str(Path.home())},
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]


@pytest.fixture
def fresh_db(tmp_path):
    p = tmp_path / "checks.db"
    _alembic(p, "upgrade", "head")
    return sa.create_engine(f"sqlite:///{p}"), p


def test_a_complete_database_reports_no_check_drift(fresh_db):
    engine, _ = fresh_db

    assert compute_check_constraint_drift(engine) == []


def test_the_membership_role_constraint_is_part_of_the_contract(fresh_db):
    """שער נגדי: אם האילוץ אינו בחוזה, הבדיקה למטה עוברת ריקה."""
    from cfo.services.schema_sync import expected_check_constraints

    table, name = REQUIRED
    assert name in expected_check_constraints().get(table, set())


def test_a_missing_check_constraint_is_reported_as_drift(fresh_db):
    """מסד שנוצר בלי האילוץ — למשל דרך `apply_additive` על טבלה שכבר
    הייתה קיימת — חייב להיראות כ-drift."""
    engine, path = fresh_db
    conn = sqlite3.connect(path)
    try:
        # SQLite אינו תומך ב-DROP CONSTRAINT; משחזרים את הטבלה בלעדיו.
        conn.executescript("""
            DROP TABLE organization_memberships;
            CREATE TABLE organization_memberships (
                id INTEGER NOT NULL PRIMARY KEY,
                organization_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role VARCHAR(11) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'invited',
                invited_by_user_id INTEGER,
                verified_at DATETIME,
                expires_at DATETIME,
                revoked_by_user_id INTEGER,
                revoked_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CONSTRAINT uq_membership_user_org UNIQUE (user_id, organization_id)
            );
        """)
        conn.commit()
    finally:
        conn.close()

    drift = compute_check_constraint_drift(engine)

    assert any(REQUIRED[1] in str(d) for d in drift), drift


def test_reconciliation_refuses_to_stamp_when_the_constraint_is_missing(fresh_db):
    """הליבה: בלי האילוץ אין `stamp`.

    מסד מסומן `head` הוא הצהרה שההגנות של הגרסה קיימות בו. אם
    `ck_membership_role_not_super_admin` חסר, ההצהרה שקרית."""
    engine, path = fresh_db
    conn = sqlite3.connect(path)
    try:
        conn.executescript("""
            DROP TABLE organization_memberships;
            CREATE TABLE organization_memberships (
                id INTEGER NOT NULL PRIMARY KEY,
                organization_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role VARCHAR(11) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'invited',
                invited_by_user_id INTEGER,
                verified_at DATETIME,
                expires_at DATETIME,
                revoked_by_user_id INTEGER,
                revoked_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CONSTRAINT uq_membership_user_org UNIQUE (user_id, organization_id),
                FOREIGN KEY(organization_id) REFERENCES organizations (id),
                FOREIGN KEY(user_id) REFERENCES users (id),
                FOREIGN KEY(invited_by_user_id) REFERENCES users (id),
                FOREIGN KEY(revoked_by_user_id) REFERENCES users (id)
            );
            CREATE INDEX ix_membership_user_status
                ON organization_memberships (user_id, status);
            CREATE INDEX ix_membership_org_status
                ON organization_memberships (organization_id, status);
            DROP TABLE alembic_version;
        """)
        conn.commit()
    finally:
        conn.close()

    stamped = []

    with pytest.raises(SchemaDeploymentError) as err:
        reconcile_schema_to_head(
            engine, alembic_config=object(), upgrade=lambda *a: None,
            stamp=lambda cfg, rev: stamped.append(rev))

    assert not stamped, "head נחתם למרות שאילוץ ה-CHECK חסר"
    assert "check" in str(err.value).lower()
