"""פקודות יומן מיובאות נכנסות למאזן — מסומנות, ומאוזנות בכרטיס השהיה.

**הממצא (17/08/2026).** `build_journal` קורא `JournalEntry` דרך
`_entries_by_source`, אבל **רק** עבור `source IN ('manual','payroll')`.
נמדד בפרוד: ה-source **היחיד** בטבלת `journal_entries` הוא
`hashavshevet_mdb` — 15,060 שורות של org5 (עומר ועודד), 25/11/2021 עד
30/06/2026. כלומר כל היבוא סונן בשקט, והמאזן של התיק היה חסר לגמרי.

(תיקון: קודם נטען כאן שהמנוע "אינו קורא `JournalEntry`". זה היה שגוי —
הוא קורא, אבל מסנן. ההבדל משנה את גודל התיקון.)

## שתי הכרעות הבעלים (17/08/2026)

**1. הכללה לניתוח בלבד, מסומן בנפרד.** ההנה"ח החיצונית כבר דיווחה
לרשויות על התקופה עד 30/06. לכן הפקודות נכנסות למאזן ולדוחות הניתוח של
רצף, אבל כל פלט דיווח **חייב** לשאת סימון מפורש שהתקופה דווחה בעבר.
דיווח חוזר עליה הוא עבירה — ולכן זה נאכף בטסט, לא בהערה.

**2. פער ₪217,116.65 לכרטיס השהיה מפורש.** 19 תנועות חד-צדדיות (חובה
בלי זכות או להפך). מאזן שאינו מתאזן אינו מאזן — אבל השמטת התנועות
הייתה מעלימה ₪217K בלי עקבה, וזה בדיוק מה ש-honest-null אוסר. הצד החסר
נרשם לכרטיס "הפרשי יבוא לבירור": המאזן מתאזן, הפער גלוי ובר-מעקב, ואף
סכום לא נעלם.
"""
from datetime import date

import pytest

from cfo.database import SessionLocal
from cfo.models import JournalEntry
from cfo.services import ledger_service


AS_OF = date(2026, 6, 30)


@pytest.fixture
def org_with_import(fresh_org):
    """ארגון עם פקודות מיובאות — אחת מאוזנת ואחת חד-צדדית."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]

    db.add(JournalEntry(
        organization_id=org_id, source="hashavshevet_mdb",
        external_id="imp-1", entry_date=date(2026, 5, 10),
        memo="חשבונית ספק מיובאת",
        lines=[
            {"account": "5100", "debit": 1000.0, "credit": 0.0, "description": "הוצאה"},
            {"account": "2100", "debit": 0.0, "credit": 1000.0, "description": "ספק"},
        ],
    ))
    # תנועה חד-צדדית — חובה בלי זכות. זו הצורה של 19 התנועות בפרוד.
    db.add(JournalEntry(
        organization_id=org_id, source="hashavshevet_mdb",
        external_id="imp-2", entry_date=date(2026, 5, 11),
        memo="תנועה חד-צדדית מהיבוא",
        lines=[
            {"account": "5200", "debit": 250.0, "credit": 0.0, "description": "ללא צד נגדי"},
        ],
    ))
    db.commit()
    return org_id


# ==================================================================== #
# ההכללה
# ==================================================================== #
def test_imported_entries_reach_the_journal(org_with_import):
    """הלב: הפקודות שסוננו בשקט חייבות להופיע."""
    db = SessionLocal()

    entries = ledger_service.build_journal(db, org_with_import)

    refs = [e.source_ref for e in entries]
    assert any("hashavshevet_mdb" in r for r in refs), (
        f"פקודות היבוא עדיין מסוננות. source_refs: {refs}"
    )


def test_imported_entries_are_marked_as_imported(org_with_import):
    """הכרעת הבעלים: 'לניתוח בלבד, **מסומן בנפרד**'. בלי סימון אי-אפשר
    להפריד אותן בפלט דיווח, וההכרעה מתרוקנת מתוכן."""
    db = SessionLocal()

    entries = ledger_service.build_journal(db, org_with_import)
    imported = [e for e in entries if "hashavshevet_mdb" in e.source_ref]

    assert imported
    assert all(getattr(e, "is_imported", False) is True for e in imported)


def test_documents_are_not_marked_imported(org_with_import):
    """שער נגדי: אם הכול היה מסומן כיבוא, הסימון לא היה מפריד דבר."""
    db = SessionLocal()

    entries = ledger_service.build_journal(db, org_with_import)
    non_imported = [e for e in entries if "hashavshevet_mdb" not in e.source_ref]

    assert all(getattr(e, "is_imported", False) is False for e in non_imported)


# ==================================================================== #
# כרטיס ההשהיה
# ==================================================================== #
def test_a_one_sided_entry_is_balanced_by_the_suspense_account(org_with_import):
    """₪250 חובה בלי זכות ⇒ ₪250 זכות בכרטיס ההשהיה. הסכום אינו נעלם
    ואינו שובר את המאזן."""
    db = SessionLocal()

    entries = ledger_service.build_journal(db, org_with_import)
    one_sided = [e for e in entries if e.source_ref.endswith("imp-2")
                 or "חד-צדדית" in e.memo]

    assert one_sided, "התנועה החד-צדדית לא נמצאה"
    entry = one_sided[0]
    accounts = {l.account for l in entry.lines}

    assert ledger_service.IMPORT_SUSPENSE_ACCOUNT in accounts
    assert entry.total_debit == entry.total_credit


def test_the_trial_balance_balances_with_imported_entries(org_with_import):
    """מאזן שאינו מתאזן אינו מאזן. זו הבדיקה שההכרעה נועדה להבטיח."""
    db = SessionLocal()

    tb = ledger_service.trial_balance(db, org_with_import)

    assert round(tb["total_debit"], 2) == round(tb["total_credit"], 2), (
        f"חובה {tb['total_debit']} ≠ זכות {tb['total_credit']}"
    )


def test_the_suspense_amount_is_visible_not_hidden(org_with_import):
    """honest-null: הפער חייב להיות בר-מעקב. אם הוא נבלע בכרטיס קיים,
    ₪217K נעלמים בלי עקבה — בדיוק מה שההכרעה דחתה."""
    db = SessionLocal()

    tb = ledger_service.trial_balance(db, org_with_import)
    suspense = [a for a in tb["accounts"]
                if a["account"] == ledger_service.IMPORT_SUSPENSE_ACCOUNT]

    assert suspense, "כרטיס ההשהיה אינו מופיע במאזן"
    assert round(suspense[0]["credit"], 2) == 250.0


def test_a_balanced_import_does_not_touch_the_suspense_account(org_with_import):
    """שער נגדי: רק תנועה חסרת-צד נוגעת בהשהיה. אחרת הכרטיס היה מתמלא
    ברעש ומאבד את משמעותו כרשימת הפריטים לבירור."""
    db = SessionLocal()

    entries = ledger_service.build_journal(db, org_with_import)
    balanced = [e for e in entries if e.source_ref.endswith("imp-1")]

    assert balanced
    accounts = {l.account for l in balanced[0].lines}
    assert ledger_service.IMPORT_SUSPENSE_ACCOUNT not in accounts


# ==================================================================== #
# השער הרגולטורי — ההכרעה נאכפת, לא מתועדת
# ==================================================================== #
def test_imported_periods_are_flagged_in_reporting_output(org_with_import):
    """**זה השער שמונע עבירה.** התקופה עד 30/06 דווחה כבר לרשויות ע"י
    ההנה"ח החיצונית. פלט שמכיל פקודות מיובאות חייב לשאת אזהרה מפורשת —
    אחרת מישהו ידווח עליהן שוב."""
    db = SessionLocal()

    tb = ledger_service.trial_balance(db, org_with_import, end=AS_OF)

    assert tb.get("includes_imported") is True
    assert tb.get("imported_warning_he"), "אין אזהרה — ההכרעה אינה נאכפת"
    assert "דווח" in tb["imported_warning_he"]


def test_an_org_without_imports_carries_no_warning(fresh_org):
    """שער נגדי: אזהרה שמופיעה תמיד היא אזהרה שאיש אינו קורא."""
    db = SessionLocal()

    tb = ledger_service.trial_balance(db, fresh_org()["org_id"])

    assert tb.get("includes_imported") is False
    assert not tb.get("imported_warning_he")
