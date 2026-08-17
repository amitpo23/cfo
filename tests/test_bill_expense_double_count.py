"""אותו מסמך SUMIT יושב בשתי טבלאות — ונרשם פעמיים לספרים.

**הממצא (17/08/2026), נמדד בפרוד.** `build_journal` מריץ שתי לולאות
נפרדות: אחת על `Bill` (`post_bill` → DR 5000) ואחת על `Expense`
(`post_expense` → DR 5000). אין ביניהן שום דה-דופליקציה.

אבל אותו מסמך SUMIT נקלט לשתי הטבלאות. ההוכחה אינה סכומים שווים אלא
מזהה משותף:

    org 1 — 893 מסמכים עם external_id זהה · ₪804,928
    org 2 — 320 מסמכים · ₪665,272     (שף אליהב כהן)
    org 5 —  83 מסמכים · ₪645,021
    ────────────────────────────────
    סה"כ  ₪2,115,221 נספרים פעמיים

ב-org2: 320 מתוך 320 חשבונות הספק חולקים `external_id` עם הוצאה, ושניהם
`source='sumit'`. כלומר **כל** ההוצאות של התיק מוכפלות.

## מה זה שובר

רווח והפסד. השאלה "מה הרווח וההפסד של אליהב כהן" מחזירה היום הוצאות
כפולות — כלומר רווח נמוך בהרבה מהאמת. זה לא עיגול; זה פי שניים.

## ההכרעה: החשבון גובר על ההוצאה

שתי הרשומות אינן טענה כלכלית זהה — `post_bill` זוקף לספקים (CR 2100),
`post_expense` זוקף לבנק (CR 1200, כלומר "שולם"). ב-org2 יש 9 תשלומים
בלבד מול 320 חשבונות, ולכן רישום 320 מסמכים כמשולמים-מהבנק היה מזכה את
העו"ש בסכום שאין לו כיסוי בתנועות.

לכן: כשקיים מזהה משותף — נרשם ה-`Bill`, וההוצאה הכפולה מדולגת. הסילוק
נרשם בנפרד דרך `Payment`.
"""
from datetime import date

import pytest

from cfo.database import SessionLocal
from cfo.models import Bill, BillStatus, Expense
from cfo.services import ledger_service


@pytest.fixture
def org_with_duplicate(fresh_org):
    """מסמך אחד משתי טבלאות — בדיוק הצורה שנמדדה בפרוד."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]

    db.add(Bill(
        organization_id=org_id, external_id="SUMIT-DOC-777", source="sumit",
        bill_number="777", issue_date=date(2026, 5, 3),
        subtotal=1000.0, tax=170.0, status=BillStatus.RECEIVED,
    ))
    db.add(Expense(
        organization_id=org_id, external_id="SUMIT-DOC-777", source="sumit",
        supplier_name="ספק בדיקה", expense_date=date(2026, 5, 3),
        amount=1000.0, vat_amount=170.0,
    ))
    # הוצאה עצמאית — אין לה חשבון ספק מקביל. חייבת להישאר.
    db.add(Expense(
        organization_id=org_id, external_id="SUMIT-DOC-888", source="sumit",
        supplier_name="ספק אחר", expense_date=date(2026, 5, 4),
        amount=400.0, vat_amount=68.0,
    ))
    db.commit()
    return org_id


def test_the_shared_document_is_posted_once(org_with_duplicate):
    """הלב: ₪1,000 פעם אחת, לא פעמיים."""
    db = SessionLocal()

    tb = ledger_service.trial_balance(db, org_with_duplicate)
    expenses = next(a for a in tb["accounts"] if a["account"] == "5000")

    # 1,000 מהמסמך המשותף + 400 מההוצאה העצמאית
    assert round(expenses["debit"], 2) == 1400.0, (
        f"כרטיס ההוצאות = {expenses['debit']} — צפוי 1,400. "
        "2,400 פירושו שהמסמך המשותף נספר פעמיים."
    )


def test_the_bill_is_the_one_that_survives(org_with_duplicate):
    """ההכרעה: החשבון גובר. רישום ההוצאה במקומו היה מזכה את העו"ש
    בסכום שאין לו כיסוי בתנועות בנק."""
    db = SessionLocal()

    entries = ledger_service.build_journal(db, org_with_duplicate)
    refs = [e.source_ref for e in entries]

    assert any(r.startswith("bill:") for r in refs)
    shared = [e for e in entries if "SUMIT-DOC-777" in e.source_ref
              or e.source_ref.startswith("bill:")]
    assert shared


def test_an_expense_without_a_matching_bill_still_posts(org_with_duplicate):
    """**שער נגדי, והוא קריטי.** דה-דופליקציה גסה מדי הייתה מוחקת הוצאות
    אמיתיות שאין להן חשבון ספק — כלומר מתקנת ניפוח ויוצרת חֶסֶר."""
    db = SessionLocal()

    tb = ledger_service.trial_balance(db, org_with_duplicate)
    expenses = next(a for a in tb["accounts"] if a["account"] == "5000")

    assert expenses["debit"] >= 400.0, "ההוצאה העצמאית נמחקה בטעות"


def test_the_bank_account_is_not_credited_for_the_shared_document(org_with_duplicate):
    """הצד השני של הכפילות, והוא החמור יותר: `post_expense` מזכה את
    העו"ש כאילו שולם. 320 מסמכים מול 9 תשלומים בפרוד — זיכוי כזה מנפח
    ירידת מזומן שלא קרתה."""
    db = SessionLocal()

    tb = ledger_service.trial_balance(db, org_with_duplicate)
    bank = next((a for a in tb["accounts"] if a["account"] == "1200"), None)

    credited = bank["credit"] if bank else 0.0
    # רק ההוצאה העצמאית (400+68) מזכה בנק; המסמך המשותף הולך לספקים.
    assert round(credited, 2) == 468.0, (
        f"העו\"ש זוכה ב-{credited} — צפוי 468 מההוצאה העצמאית בלבד"
    )


def test_the_trial_balance_still_balances(org_with_duplicate):
    db = SessionLocal()

    tb = ledger_service.trial_balance(db, org_with_duplicate)

    assert round(tb["total_debit"], 2) == round(tb["total_credit"], 2)


def test_the_deduplication_is_visible_not_silent(org_with_duplicate):
    """honest-null: תיקון שמשנה מספרים בשקט הוא תיקון שאיש לא יכול
    לבקר. המאזן מדווח כמה מסמכים אוחדו."""
    db = SessionLocal()

    tb = ledger_service.trial_balance(db, org_with_duplicate)

    assert tb.get("deduplicated_documents") == 1


def test_documents_without_an_external_id_are_never_merged(fresh_org):
    """שער נגדי: `external_id` ריק אינו מזהה. איחוד לפי NULL היה מכווץ
    את כל המסמכים חסרי-המזהה לאחד — נזק חמור בהרבה מהכפילות."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]

    for amount in (100.0, 200.0):
        db.add(Expense(
            organization_id=org_id, external_id=None, source="manual",
            supplier_name="ללא מזהה", expense_date=date(2026, 5, 5),
            amount=amount, vat_amount=0.0,
        ))
    db.add(Bill(
        organization_id=org_id, external_id=None, source="manual",
        bill_number="X", issue_date=date(2026, 5, 5),
        subtotal=50.0, tax=0.0, status=BillStatus.RECEIVED,
    ))
    db.commit()

    tb = ledger_service.trial_balance(db, org_id)
    expenses = next(a for a in tb["accounts"] if a["account"] == "5000")

    assert round(expenses["debit"], 2) == 350.0, (
        "מסמכים בלי external_id אוחדו — 100+200+50 חייבים להישמר"
    )
