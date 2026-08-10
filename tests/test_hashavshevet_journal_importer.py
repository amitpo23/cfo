"""קליטת פקודות היומן מייצוא חשבשבת (Journal_PORAT.mdb) — org5.

הרקע: `journal_entries` = 0 בכל הארגונים, וזו "החוליה השבורה" של הלוח.
לעומר ועודד יש היסטוריה מלאה בהנה"ח הקודמת — 15,061 תנועות מ-11/2021 עד
06/2026 — שדווחה בפועל לרשויות. זו הרשומה הנכונה, ולכן היא גוברת על מה
שקיים ב-SUMIT לתקופה החופפת (הכרעת בעלים 10/08/2026).

המקור הוא **`JurnalTrans` + `JurnalTransMoves` מה-MDB**, ולא
`MOVEIN.DAT`. ההבחנה מהותית: `MOVEIN.DAT` הוא fixed-width שהגיע בלי
`Movein.prm`, ולכן פוענח בניחוש ויצא לא מאוזן ב-₪6,691,532.40 — מה
שחסם את הקליטה בתוכנית מ-28/07. ה-MDB מכיל צדדים מפורשים ומאוזן
במדויק: חובה 273,229,334.16 = זכות.
"""
from datetime import date
from decimal import Decimal

import pytest

from cfo.services.hashavshevet_journal_importer import (
    JournalImportError,
    import_journal_entries,
    parse_journal_source,
)


def test_parser_reads_transactions_with_their_sides(mdb_dir):
    entries = parse_journal_source(mdb_dir, strict=False)

    assert len(entries) >= 15_061, "כל תנועה במקור חייבת להיקלט"
    first = entries[0]
    assert first.entry_date
    assert first.lines, "תנועה בלי שורות אינה פקודת יומן"
    for line in first.lines:
        assert line["account_key"]
        assert "debit" in line and "credit" in line


def test_one_sided_entries_are_preserved_not_rejected(mdb_dir):
    """חשבשבת מאפשר תנועה חד-צדית — רישומי מע"מ והעברות יתרות שהצד
    הנגדי שלהן יושב בתנועה אחרת. `TransCredID` ריק בכותרת מעיד על כך.

    כ-4,500 מהתנועות כאן הן כאלה, והן מתקזזות ברמת המערכת. פסילתן
    הייתה מוחקת רבע מהספרים — ולכן הדרישה היא איזון כולל (הטסט הבא)
    ולא איזון פר-תנועה. התוכנית מ-28/07 פירשה אותן כשגיאת פענוח.
    """
    entries = parse_journal_source(mdb_dir, strict=False)

    one_sided = [
        e for e in entries
        if sum(Decimal(str(l["debit"])) for l in e.lines) == 0
        or sum(Decimal(str(l["credit"])) for l in e.lines) == 0
    ]
    assert one_sided, "צפויות תנועות חד-צדיות במקור הזה"
    assert all(e.is_one_sided for e in one_sided), "חד-צדית חייבת להיות מסומנת"


def test_strict_mode_refuses_the_source_because_it_does_not_balance(mdb_dir):
    """המקור המלא אינו מאוזן — פער ₪217,116.65 מ-19 תנועות חד-צדיות
    שכל המידע שלהן בכותרת.

    אפשר היה "לאזן" בהשמטתן, אבל זו מחיקת נתוני אמת כדי שמספר יסתדר.
    ברירת המחדל עוצרת ומדווחת; קליטה מודעת דורשת strict=False.
    """
    with pytest.raises(JournalImportError, match="אינו מאוזן"):
        parse_journal_source(mdb_dir)


def test_non_strict_reports_the_exact_imbalance_instead_of_hiding_it(mdb_dir):
    entries = parse_journal_source(mdb_dir, strict=False)

    debit = sum(Decimal(str(l["debit"])) for e in entries for l in e.lines)
    credit = sum(Decimal(str(l["credit"])) for e in entries for l in e.lines)
    assert debit > 0 and credit > 0
    # הפער מדווח ולא נבלע — זה מה שיוצלב מול מאזן הבוחן של ההנה"ח.
    assert debit - credit == Decimal("217116.65")


def test_cutoff_excludes_anything_after_the_reported_period(mdb_dir):
    """נקלט עד 30/06/2026 — התקופה שדווחה בפועל ע"י ההנה"ח הקודמת.
    מה שאחריה שייך ל-SUMIT ואסור שייכנס פעמיים."""
    entries = parse_journal_source(mdb_dir, cutoff=date(2026, 6, 30), strict=False)

    assert all(e.entry_date <= date(2026, 6, 30) for e in entries)


# ---------------------------------------------------------------------- #
# קליטה למסד
# ---------------------------------------------------------------------- #
def test_import_writes_entries_scoped_to_the_organization(fresh_org, mdb_dir):
    from cfo.database import SessionLocal
    from cfo.models import JournalEntry

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = import_journal_entries(db, org_id, mdb_dir, cutoff=date(2022, 1, 1), strict=False)

        assert result["inserted"] > 0
        rows = db.query(JournalEntry).filter(
            JournalEntry.organization_id == org_id
        ).all()
        assert len(rows) == result["inserted"]
        assert all(r.source == "hashavshevet_mdb" for r in rows)
    finally:
        db.query(JournalEntry).filter(JournalEntry.organization_id == org_id).delete()
        db.commit()
        db.close()


def test_reimport_replaces_instead_of_duplicating(fresh_org, mdb_dir):
    """הכרעת בעלים: חשבשבת הוא הרשומה הנכונה, ולכן הרצה חוזרת דורסת.
    כפל פקודות יומן הוא שגיאה חשבונאית, לא אי-נוחות."""
    from cfo.database import SessionLocal
    from cfo.models import JournalEntry

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        first = import_journal_entries(db, org_id, mdb_dir, cutoff=date(2022, 1, 1), strict=False)
        second = import_journal_entries(db, org_id, mdb_dir, cutoff=date(2022, 1, 1), strict=False)

        total = db.query(JournalEntry).filter(
            JournalEntry.organization_id == org_id
        ).count()
        assert total == first["inserted"]
        assert second["replaced"] == first["inserted"]
    finally:
        db.query(JournalEntry).filter(JournalEntry.organization_id == org_id).delete()
        db.commit()
        db.close()


def test_import_refuses_an_unbalanced_source(tmp_path):
    """honest-null: מקור לא מאוזן נעצר ואינו נקלט חלקית."""
    (tmp_path / "JurnalTrans.csv").write_text(
        "TransID,ValueDate,Description,Referance,BatchNo\n1,2022-01-01T00:00:00,x,R1,1\n",
        encoding="utf-8",
    )
    (tmp_path / "JurnalTransMoves.csv").write_text(
        "ID,TransID,AccountKey,DebitCredit,SuF\n1,1,100000,1,50.00\n",
        encoding="utf-8",
    )
    with pytest.raises(JournalImportError, match="מאוזן"):
        parse_journal_source(tmp_path)
