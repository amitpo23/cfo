"""מיגרציית החברות מול PostgreSQL — ושלמות ה-backfill.

שני סוגי כשל שאף בדיקה על SQLite אינה יכולה לתפוס:

**1. `CREATE TYPE userrole` כפול.** `sa.Enum(...)` ב-`create_table` גורם
ל-Alembic להנפיק `CREATE TYPE` ב-PostgreSQL. הטיפוס כבר קיים שם מהמיגרציה
שיצרה את `users`, ולכן ההרצה נופלת על `DuplicateObject` — **באמצע
המיגרציה, בפרוד, אחרי שהטבלה כבר נוצרה.** SQLite אינו מכיר טיפוסי enum
ולכן עובר בשקט.

**2. backfill שמשאיר חור.** משתמש מושבת דולג לגמרי, ולכן אין לו רשומת
חברות. ברגע שמישהו יפעיל אותו מחדש (`is_active=True`) הוא ייפול חזרה
ל-`users.organization_id` — כלומר **הפעלה מחדש מחזירה גישה בשקט**.
המצב הנכון הוא חברות `suspended`: הרשומה קיימת, הגישה חסומה, וההחזרה
דורשת פעולה מפורשת.

הבדיקה מנפיקה SQL אופליין (`--sql`) ולכן אינה נוגעת ב-PostgreSQL חי.
"""
import re
import subprocess
import sqlite3
import sys
from pathlib import Path

import pytest


REVISION = "d2e3f4a5b6c7"
PREVIOUS = "b0c1d2e3f4a5"
REPO = Path(__file__).resolve().parents[1]


def _offline_sql(dialect_url: str, span: str) -> str:
    """SQL אופליין — Alembic מייצר את ה-DDL בלי להתחבר לשום מסד."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", span, "--sql"],
        cwd=REPO,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "DATABASE_URL": dialect_url,
            "HOME": str(Path.home()),
        },
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stdout


@pytest.fixture(scope="module")
def postgres_sql() -> str:
    # כתובת פיקטיבית: `--sql` אינו מתחבר. אין כאן גישה לפרוד.
    return _offline_sql(
        "postgresql://offline:offline@localhost:1/offline",
        f"{PREVIOUS}:{REVISION}",
    )


def test_migration_does_not_recreate_the_userrole_type(postgres_sql):
    """`CREATE TYPE userrole` היה מפיל את המיגרציה על DuplicateObject —
    אחרי שהטבלה כבר נוצרה, כלומר במצב חצי-מיגרציה."""
    offenders = re.findall(r"CREATE TYPE\s+\S*userrole", postgres_sql, re.I)

    assert not offenders, f"המיגרציה מנסה ליצור מחדש את userrole: {offenders}"


def test_migration_creates_the_table_in_postgres(postgres_sql):
    """שער נגדי: אם ה-SQL ריק, הטסט למעלה עובר מהסיבה הלא-נכונה."""
    assert re.search(r"CREATE TABLE\s+organization_memberships", postgres_sql, re.I)


def test_postgres_backfill_is_present(postgres_sql):
    assert "INSERT INTO organization_memberships" in postgres_sql


# --------------------------------------------------------------------- #
# שלמות ה-backfill — postconditions סמנטיים
# --------------------------------------------------------------------- #
def _alembic(db_path: Path, *args: str):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "DATABASE_URL": f"sqlite:///{db_path}",
            "HOME": str(Path.home()),
        },
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result


@pytest.fixture
def legacy_db(tmp_path):
    db_path = tmp_path / "legacy.db"
    _alembic(db_path, "upgrade", PREVIOUS)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO organizations (id, name, is_active) VALUES (1,'אלפא',1)")
    conn.execute("INSERT INTO organizations (id, name, is_active) VALUES (2,'בטא',1)")
    for uid, org, email, role, active in [
        (10, 1, "admin@alpha", "ADMIN", 1),
        (11, 1, "viewer@alpha", "VIEWER", 1),
        (12, 2, "acct@beta", "ACCOUNTANT", 1),
        (13, 1, "disabled@alpha", "ADMIN", 0),
        (14, None, "super@rezef", "SUPER_ADMIN", 1),
    ]:
        conn.execute(
            "INSERT INTO users (id, organization_id, email, password_hash, "
            "full_name, role, is_active) VALUES (?,?,?,?,?,?,?)",
            (uid, org, email, "x", email, role, active),
        )
    conn.commit()
    conn.close()
    _alembic(db_path, "upgrade", REVISION)
    return db_path


def _rows(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return {
            r[0]: r for r in conn.execute(
                "SELECT user_id, organization_id, role, status "
                "FROM organization_memberships"
            )
        }
    finally:
        conn.close()


def test_disabled_user_gets_a_suspended_membership_not_nothing(legacy_db):
    """הליבה: משתמש מושבת חייב לקבל רשומה **מושעית**.

    דילוג מוחלט משאיר אותו בלי חברות, ולכן הפעלה מחדש הייתה מפילה אותו
    חזרה ל-`users.organization_id` ומחזירה גישה בשקט."""
    rows = _rows(legacy_db)

    assert 13 in rows, "משתמש מושבת נותר בלי רשומת חברות"
    assert rows[13][3] == "suspended", f"סטטוס שגוי: {rows[13][3]}"
    assert rows[13][1] == 1


def test_every_eligible_legacy_user_got_exactly_one_membership(legacy_db):
    """postcondition סמנטי: אחת בדיוק לכל משתמש עם ארגון."""
    conn = sqlite3.connect(legacy_db)
    try:
        expected = {r[0] for r in conn.execute(
            "SELECT id FROM users WHERE organization_id IS NOT NULL"
        )}
        counts = dict(conn.execute(
            "SELECT user_id, COUNT(*) FROM organization_memberships GROUP BY user_id"
        ))
    finally:
        conn.close()

    assert set(counts) == expected
    assert all(c == 1 for c in counts.values()), counts


def test_role_and_organization_are_preserved_exactly(legacy_db):
    rows = _rows(legacy_db)
    assert rows[10][1:3] == (1, "ADMIN")
    assert rows[11][1:3] == (1, "VIEWER")
    assert rows[12][1:3] == (2, "ACCOUNTANT")


def test_active_users_are_active_and_disabled_are_not(legacy_db):
    rows = _rows(legacy_db)
    assert {rows[u][3] for u in (10, 11, 12)} == {"active"}
    assert rows[13][3] != "active"


def test_orgless_super_admin_is_still_skipped(legacy_db):
    """אין ארגון להעתיק ממנו — ולכן אין רשומה. הוא בוחר מפורשות."""
    assert 14 not in _rows(legacy_db)


def test_no_signing_authority_is_ever_created(legacy_db):
    conn = sqlite3.connect(legacy_db)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM organization_signing_authorities"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_rerun_after_downgrade_does_not_duplicate(legacy_db):
    _alembic(legacy_db, "downgrade", PREVIOUS)
    _alembic(legacy_db, "upgrade", REVISION)

    pairs = [(r[0], r[1]) for r in _rows(legacy_db).values()]

    assert len(pairs) == len(set(pairs))
