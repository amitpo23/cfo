"""חוזה הסכימה כולל CheckConstraints — ואי-אפשר לסמן head בלעדיהם.

`compute_schema_drift` בודק גם CheckConstraints כחלק מאותו חוזה מרכזי.

זה חשוב במיוחד ל-`ck_membership_role_not_super_admin`: הוא מה שמונע
ממנהל ארגון להעניק חברות `SUPER_ADMIN` בתיק שלו ולעקוף את ההפרדה בין
מפעיל מערכת לבעל עסק. מסלול ה-repair יוצר טבלאות חסרות דרך
`apply_additive`, ואם ה-CHECK אינו נבדק — המסד מסומן `head` בעוד
ההגנה אינה קיימת בו בפועל.

הכלל: אילוץ CHECK חסר הוא drift. תיקון additive מחזיר אילוץ שאין
שורות שסותרות אותו, ואז מותר לחתום. שורה שסותרת את האילוץ משאירה
את השער סגור.
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
from cfo.services.schema_sync import (
    compute_check_constraint_drift,
    compute_schema_drift,
    has_schema_drift,
)


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

    full_drift = compute_schema_drift(engine)
    assert REQUIRED[1] in full_drift["check_constraints"][REQUIRED[0]]
    assert has_schema_drift(full_drift)


def _strip_membership_check(path):
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


def test_reconciliation_restores_a_missing_check_before_stamping(fresh_db):
    """A missing allow-listed CHECK is repaired before head is stamped."""
    engine, path = fresh_db
    _strip_membership_check(path)
    stamped = []

    reconcile_schema_to_head(
        engine, alembic_config=object(), upgrade=lambda *a: None,
        stamp=lambda cfg, rev: stamped.append(rev))

    assert stamped == ["head"]
    present = {
        row.get("name")
        for row in sa.inspect(engine).get_check_constraints("organization_memberships")
    }
    assert REQUIRED[1] in present


def test_reconciliation_refuses_to_stamp_when_rows_violate_the_check(fresh_db):
    """A row that already breaks the rule blocks the stamp."""
    engine, path = fresh_db
    _strip_membership_check(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO organization_memberships "
            "(id, organization_id, user_id, role, status, created_at, updated_at) "
            "VALUES (1, 1, 1, 'SUPER_ADMIN', 'active', '2026-01-01', '2026-01-01')"
        )
        conn.commit()
    finally:
        conn.close()

    stamped = []
    with pytest.raises(Exception):
        reconcile_schema_to_head(
            engine, alembic_config=object(), upgrade=lambda *a: None,
            stamp=lambda cfg, rev: stamped.append(rev))

    assert not stamped
    assert REQUIRED[1] not in {
        row.get("name")
        for row in sa.inspect(engine).get_check_constraints("organization_memberships")
    }


def test_check_repair_skips_names_outside_the_allow_list(fresh_db, monkeypatch):
    engine, path = fresh_db
    _strip_membership_check(path)
    from cfo.services import schema_sync

    monkeypatch.setattr(schema_sync, "CHECK_REPAIR_ALLOW_LIST", frozenset())
    applied = schema_sync._apply_missing_check_constraints(engine)

    assert applied == {}
    assert REQUIRED[1] not in {
        row.get("name")
        for row in sa.inspect(engine).get_check_constraints("organization_memberships")
    }


def test_postgres_check_repair_does_not_use_not_valid():
    import inspect

    from cfo.services.schema_sync import _add_postgres_checks

    source = inspect.getsource(_add_postgres_checks)
    assert "NOT VALID" not in source
    assert "VALIDATE CONSTRAINT" not in source
    assert "ADD CONSTRAINT" in source
