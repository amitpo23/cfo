"""תיקון מבני אינו מספיק כדי לסמן head כשנדרש גם backfill.

`reconcile_schema_to_head` מריץ `apply_additive` (שיוצר טבלאות ועמודות
חסרות), בודק `compute_missing`, ואם ריק — מסמן `head`.

זה נכון כל עוד המיגרציה היחידה שנעקפה היא מבנית. `organization_memberships`
אינה כזו: המיגרציה שלה נושאת **backfill** שממיר את `users.organization_id`
לרשומות חברות. `apply_additive` יוצר טבלה **ריקה** ומסמן head — ומכאן
המערכת מאמינה שהמיגרציה רצה כשהנתונים מעולם לא הועברו.

שתי תוצאות בפרוד:
- כל משתמש קיים נופל למסלול התאימות `legacy_column`, שאמור להיות זמני.
- **הבטחת ה-`suspended` מתבטלת**: משתמש מושבת אינו מקבל רשומה, ולכן
  הפעלתו מחדש מחזירה גישה בשקט — בדיוק מה שהמיגרציה נועדה למנוע.

הכלל: אם נדרש backfill, מבצעים אותו ומאמתים אותו סמנטית — או **לא
מסמנים head**.
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


PREVIOUS = "b0c1d2e3f4a5"
REPO = Path(__file__).resolve().parents[1]


def _alembic(db_path: Path, *args: str):
    r = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin",
             "DATABASE_URL": f"sqlite:///{db_path}", "HOME": str(Path.home())},
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr[-2000:]


@pytest.fixture
def legacy_engine(tmp_path):
    """מסד במצב שלפני מיגרציית החברות, עם משתמשים אמיתיים,
    ובלי `alembic_version` — כלומר "legacy" לפי ההגדרה בשירות."""
    db_path = tmp_path / "legacy-stamp.db"
    _alembic(db_path, "upgrade", PREVIOUS)

    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO organizations (id,name,is_active) VALUES (1,'א',1)")
    conn.execute("INSERT INTO organizations (id,name,is_active) VALUES (2,'ב',1)")
    for uid, org, email, role, active in [
        (10, 1, "a@x", "ADMIN", 1),
        (11, 1, "b@x", "VIEWER", 1),
        (12, 2, "c@x", "ACCOUNTANT", 1),
        (13, 1, "off@x", "ADMIN", 0),
    ]:
        conn.execute(
            "INSERT INTO users (id,organization_id,email,password_hash,"
            "full_name,role,is_active) VALUES (?,?,?,?,?,?,?)",
            (uid, org, email, "x", email, role, active))
    # מצב legacy: אין טבלת גרסאות
    conn.execute("DROP TABLE IF EXISTS alembic_version")
    conn.commit()
    conn.close()
    return sa.create_engine(f"sqlite:///{db_path}"), db_path


class _Recorder:
    def __init__(self):
        self.stamped = []

    def __call__(self, cfg, rev):
        self.stamped.append(rev)


def _memberships(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT user_id, organization_id, role, status "
            "FROM organization_memberships ORDER BY user_id").fetchall()
    finally:
        conn.close()


# ==================================================================== #
def test_structural_repair_alone_does_not_stamp(legacy_engine, monkeypatch):
    """אם ה-backfill לא בוצע, אסור לסמן head.

    זהו הלב: `apply_additive` יוצר את הטבלה ריקה, `compute_missing`
    מרוצה, וללא הבדיקה הסמנטית — head היה נחתם על נתונים שלא הועברו."""
    engine, db_path = legacy_engine
    stamp = _Recorder()

    from cfo.services import schema_deployment as sd
    monkeypatch.setattr(sd, "backfill_memberships", lambda _e: None)

    with pytest.raises(SchemaDeploymentError) as err:
        reconcile_schema_to_head(
            engine, alembic_config=object(), upgrade=lambda *a: None, stamp=stamp)

    assert not stamp.stamped, "head נחתם למרות ש-backfill לא בוצע"
    assert "backfill" in str(err.value).lower()


def test_reconciliation_runs_the_backfill_and_then_stamps(legacy_engine):
    engine, db_path = legacy_engine
    stamp = _Recorder()

    result = reconcile_schema_to_head(
        engine, alembic_config=object(), upgrade=lambda *a: None, stamp=stamp)

    assert stamp.stamped == ["head"], f"לא נחתם head: {stamp.stamped}"
    rows = {r[0]: r for r in _memberships(db_path)}
    assert set(rows) == {10, 11, 12, 13}
    assert result["membership_backfill"]["created"] == 4


def test_every_eligible_user_gets_exactly_one_membership(legacy_engine):
    engine, db_path = legacy_engine
    reconcile_schema_to_head(
        engine, alembic_config=object(), upgrade=lambda *a: None,
        stamp=_Recorder())

    pairs = [(r[0], r[1]) for r in _memberships(db_path)]
    assert len(pairs) == len(set(pairs))


def test_role_and_org_are_preserved(legacy_engine):
    engine, db_path = legacy_engine
    reconcile_schema_to_head(
        engine, alembic_config=object(), upgrade=lambda *a: None,
        stamp=_Recorder())

    rows = {r[0]: r for r in _memberships(db_path)}
    assert rows[10][1:3] == (1, "ADMIN")
    assert rows[11][1:3] == (1, "VIEWER")
    assert rows[12][1:3] == (2, "ACCOUNTANT")


def test_inactive_user_becomes_suspended_not_active(legacy_engine):
    engine, db_path = legacy_engine
    reconcile_schema_to_head(
        engine, alembic_config=object(), upgrade=lambda *a: None,
        stamp=_Recorder())

    rows = {r[0]: r for r in _memberships(db_path)}
    assert rows[13][3] == "suspended"
    assert {rows[u][3] for u in (10, 11, 12)} == {"active"}


def test_no_signing_authority_is_created_by_reconciliation(legacy_engine):
    """התיקון אינו מעניק בעלות עסקית. אם ייווצר מורשה חתימה בדרך —
    זו הענקת סמכות לאשר תשלומים, בלי שאיש ביקש."""
    engine, db_path = legacy_engine
    reconcile_schema_to_head(
        engine, alembic_config=object(), upgrade=lambda *a: None,
        stamp=_Recorder())

    conn = sqlite3.connect(db_path)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM organization_signing_authorities").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_a_semantically_broken_backfill_blocks_the_stamp(legacy_engine, monkeypatch):
    """גם backfill שרץ אך הותיר משתמש בלי חברות — עוצר את החתימה."""
    engine, db_path = legacy_engine
    stamp = _Recorder()

    from cfo.services import schema_deployment as sd
    real = sd.backfill_memberships

    def _partial(e):
        real(e)
        with e.begin() as conn:
            conn.execute(sa.text(
                "DELETE FROM organization_memberships WHERE user_id = 11"))

    monkeypatch.setattr(sd, "backfill_memberships", _partial)

    with pytest.raises(SchemaDeploymentError):
        reconcile_schema_to_head(
            engine, alembic_config=object(), upgrade=lambda *a: None, stamp=stamp)

    assert not stamp.stamped


def test_rerunning_reconciliation_does_not_duplicate(legacy_engine):
    engine, db_path = legacy_engine
    for _ in range(2):
        reconcile_schema_to_head(
            engine, alembic_config=object(), upgrade=lambda *a: None,
            stamp=_Recorder())

    pairs = [(r[0], r[1]) for r in _memberships(db_path)]
    assert len(pairs) == len(set(pairs)) == 4
