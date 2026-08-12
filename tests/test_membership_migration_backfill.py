"""המיגרציה שומרת משתמשים קיימים — ואינה מנחשת בעלות.

זהו הטסט המסוכן ביותר בשלב הזה. מיגרציה שמעניקה חברות או סמכות חתימה
בניחוש היא הענקת גישה לכספים של לקוח, בלי שאיש אישר אותה, ובלי שאיש
ישים לב — כי מיגרציות רצות פעם אחת ובשקט.

הבדיקה מריצה את שרשרת ה-Alembic על מסד ריק, זורעת נתונים במצב שקדם
למודל, ואז מריצה את המיגרציה הבודדת ובודקת מה נוצר.
"""
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


REVISION = "d2e3f4a5b6c7"
PREVIOUS = "b0c1d2e3f4a5"
REPO = Path(__file__).resolve().parents[1]


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
def migrated_db(tmp_path):
    """מסד במצב שלפני המיגרציה, עם נתוני משתמשים אמיתיים."""
    db_path = tmp_path / "backfill.db"
    _alembic(db_path, "upgrade", PREVIOUS)

    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO organizations (id, name, is_active) VALUES (1, 'אלפא', 1)")
    conn.execute("INSERT INTO organizations (id, name, is_active) VALUES (2, 'בטא', 1)")
    users = [
        # (id, org, email, role, is_active)
        (10, 1, "admin@alpha.co.il", "ADMIN", 1),
        (11, 1, "viewer@alpha.co.il", "VIEWER", 1),
        (12, 2, "acct@beta.co.il", "ACCOUNTANT", 1),
        (13, 1, "gone@alpha.co.il", "ADMIN", 0),     # מושבת — לא אמור לעבור
        (14, None, "super@rezef.local", "SUPER_ADMIN", 1),  # בלי ארגון
    ]
    for uid, org, email, role, active in users:
        conn.execute(
            "INSERT INTO users (id, organization_id, email, password_hash, "
            "full_name, role, is_active) VALUES (?,?,?,?,?,?,?)",
            (uid, org, email, "x", email, role, active),
        )
    conn.commit()
    conn.close()

    _alembic(db_path, "upgrade", REVISION)
    return db_path


def _memberships(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT user_id, organization_id, role, status, invited_by_user_id "
            "FROM organization_memberships ORDER BY user_id"
        ).fetchall()
    finally:
        conn.close()


def test_existing_users_keep_their_organization_and_role(migrated_db):
    rows = {r[0]: r for r in _memberships(migrated_db)}

    assert rows[10][1:4] == (1, "ADMIN", "active")
    assert rows[11][1:4] == (1, "VIEWER", "active")
    assert rows[12][1:4] == (2, "ACCOUNTANT", "active")


def test_no_role_is_upgraded_by_the_migration(migrated_db):
    """שדרוג תפקיד במיגרציה הוא הענקת הרשאה בלי אישור."""
    for user_id, _org, role, _status, _by in _memberships(migrated_db):
        original = {10: "ADMIN", 11: "VIEWER", 12: "ACCOUNTANT"}[user_id]
        assert role == original, f"תפקיד המשתמש {user_id} שונה: {original} → {role}"


def test_disabled_user_gets_no_membership(migrated_db):
    """משתמש מושבת אינו מקבל גישה חדשה דרך הדלת האחורית של המיגרציה."""
    assert 13 not in {r[0] for r in _memberships(migrated_db)}


def test_orgless_super_admin_gets_no_membership(migrated_db):
    """אין ארגון להעתיק ממנו — ולכן אין חברות. הוא בוחר מפורשות."""
    assert 14 not in {r[0] for r in _memberships(migrated_db)}


def test_migration_does_not_grant_signing_authority(migrated_db):
    """הבדיקה החשובה: בעלות עסקית אינה נגזרת ממיגרציה בשום מקרה.

    `OrganizationSigningAuthority` היא מי שרשאי לאשר תשלום, שידור וסגירת
    תקופה. הענקתה בניחוש היא הפער החמור ביותר שמיגרציה יכולה לייצר."""
    conn = sqlite3.connect(migrated_db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM organization_signing_authorities"
        ).fetchone()[0]
    finally:
        conn.close()

    assert count == 0, "המיגרציה יצרה סמכות חתימה — אסור בשום מקרה"


def test_backfilled_membership_records_no_fake_inviter(migrated_db):
    """אף אדם לא הזמין את החברויות האלה. NULL הוא התיעוד הכן;
    שיוך למשתמש שרירותי היה מייצר אחריות מזויפת."""
    for _uid, _org, _role, _status, invited_by in _memberships(migrated_db):
        assert invited_by is None


def test_users_organization_id_is_preserved(migrated_db):
    """העמודה הישנה נשארת — היא מקור ה-backfill ו-fallback לקריאה."""
    conn = sqlite3.connect(migrated_db)
    try:
        rows = dict(conn.execute(
            "SELECT id, organization_id FROM users WHERE id IN (10,11,12)"
        ).fetchall())
    finally:
        conn.close()

    assert rows == {10: 1, 11: 1, 12: 2}


def test_downgrade_restores_the_previous_state(migrated_db):
    """rollback חייב להיות אמיתי: הטבלה יורדת ו-`users` שלמה."""
    _alembic(migrated_db, "downgrade", PREVIOUS)

    conn = sqlite3.connect(migrated_db)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()

    assert "organization_memberships" not in tables
    assert users == 5, "משתמשים אבדו ב-downgrade"


def test_migration_is_rerunnable_after_downgrade(migrated_db):
    """הרצה חוזרת אינה מכפילה חברויות."""
    _alembic(migrated_db, "downgrade", PREVIOUS)
    _alembic(migrated_db, "upgrade", REVISION)

    rows = _memberships(migrated_db)
    pairs = [(r[0], r[1]) for r in rows]

    assert len(pairs) == len(set(pairs)), f"חברות כפולה נוצרה: {pairs}"
