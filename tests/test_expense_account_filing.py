"""תיוק הוצאה לכרטיס באינדקס החשבונות המיובא.

זו החוליה שחסרה כדי שהתיק של עומר ועודד יהיה שמיש: 1,004 כרטיסי חשבשבת
יושבים ב-`accounts`, 15,060 פקודות יומן ב-`journal_entries` — אבל
`expenses` החזיק רק `category` כמחרוזת חופשית, בלי שום דרך להצביע לכרטיס.

המשמעות המעשית (הבהרת בעלים 10/08/2026): הוצאה שנכנסת דרך מודול העסק
צריכה להיות ניתנת לתיוק **לתוך האינדקס המיובא**, וכך להפיק דוחות מול
אותם כרטיסים שההנה"ח הקודמת עבדה מולם.
"""
import pytest

from cfo.services.expense_account_filing import (
    ExpenseFilingError,
    file_expense_to_account,
    suggest_accounts_for_expense,
)


def _account(db, org_id, code, name, sort_code="700"):
    from cfo.models import Account, AccountType

    row = Account(
        organization_id=org_id,
        name=name,
        account_type=AccountType.EXPENSE,
        source="hashavshevet_mdb",
        source_account_code=code,
        sort_code=sort_code,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _expense(db, org_id, supplier="ספק בדיקה", amount=100):
    from datetime import date
    from decimal import Decimal

    from cfo.models import Expense

    row = Expense(
        organization_id=org_id,
        supplier_name=supplier,
        amount=Decimal(str(amount)),
        total=Decimal(str(amount)),
        expense_date=date(2026, 7, 1),
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_filing_links_the_expense_to_the_index_account(fresh_org):
    from cfo.database import SessionLocal

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        account = _account(db, org_id, "701600", "אנרגיה רפת")
        expense = _expense(db, org_id)

        result = file_expense_to_account(db, org_id, expense.id, account.id)

        db.refresh(expense)
        assert expense.account_id == account.id
        assert expense.status == "filed"
        assert result["source_account_code"] == "701600"
    finally:
        db.close()


def test_filing_refuses_an_account_from_another_organization(fresh_org):
    """בידוד ארגוני: תיוק לכרטיס של תיק אחר הוא ערבוב ספרים של
    שני לקוחות."""
    from cfo.database import SessionLocal

    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        foreign = _account(db, org_b, "701600", "כרטיס של תיק אחר")
        expense = _expense(db, org_a)

        with pytest.raises(ExpenseFilingError, match="ארגון"):
            file_expense_to_account(db, org_a, expense.id, foreign.id)

        db.refresh(expense)
        assert expense.account_id is None
        assert expense.status == "pending"
    finally:
        db.close()


def test_filing_an_unknown_expense_fails_without_touching_anything(fresh_org):
    from cfo.database import SessionLocal

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        account = _account(db, org_id, "701600", "אנרגיה רפת")
        with pytest.raises(ExpenseFilingError):
            file_expense_to_account(db, org_id, 999_999, account.id)
    finally:
        db.close()


def test_refiling_moves_the_expense_to_the_new_account(fresh_org):
    """תיקון תיוק שגוי חייב להיות אפשרי — זו פעולה יומיומית של
    מנהל חשבונות, לא חריג."""
    from cfo.database import SessionLocal

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        first = _account(db, org_id, "701600", "אנרגיה רפת")
        second = _account(db, org_id, "703100", "אחזקת רכב")
        expense = _expense(db, org_id)

        file_expense_to_account(db, org_id, expense.id, first.id)
        file_expense_to_account(db, org_id, expense.id, second.id)

        db.refresh(expense)
        assert expense.account_id == second.id
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# הצעות תיוק
# ---------------------------------------------------------------------- #
def test_suggestions_match_the_supplier_name_against_the_index(fresh_org):
    """מנהל חשבונות לא זוכר 1,004 קודים בעל-פה. ההצעה מחפשת את הספק
    באינדקס לפי שם."""
    from cfo.database import SessionLocal

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _account(db, org_id, "400001", "עדי דלקים ושמנים בעמ", sort_code="400")
        _account(db, org_id, "400650", "אגרות ואגודות", sort_code="400")
        expense = _expense(db, org_id, supplier="עדי דלקים")

        suggestions = suggest_accounts_for_expense(db, org_id, expense.id)

        assert suggestions
        assert suggestions[0]["source_account_code"] == "400001"
    finally:
        db.close()


def test_suggestions_are_empty_rather_than_arbitrary_when_nothing_matches(fresh_org):
    """honest-null: אין התאמה = רשימה ריקה. הצעה שרירותית תגרום
    לתיוק שגוי שאיש לא יבחין בו."""
    from cfo.database import SessionLocal

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _account(db, org_id, "400001", "עדי דלקים ושמנים בעמ", sort_code="400")
        expense = _expense(db, org_id, supplier="זבחזבחזבח")

        assert suggest_accounts_for_expense(db, org_id, expense.id) == []
    finally:
        db.close()


def test_suggestions_never_cross_organizations(fresh_org):
    from cfo.database import SessionLocal

    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _account(db, org_b, "400001", "עדי דלקים ושמנים בעמ", sort_code="400")
        expense = _expense(db, org_a, supplier="עדי דלקים")

        assert suggest_accounts_for_expense(db, org_a, expense.id) == []
    finally:
        db.close()


def test_a_single_generic_word_is_not_enough_for_a_suggestion(fresh_org):
    """נתפס בהרצה על נתוני org5: "ספק מספוא" הוצע לכרטיס "אלון תבור-ספק"
    על סמך המילה "ספק" בלבד — מילה שמופיעה בעשרות כרטיסים.

    התאמה חלשה גרועה מאין התאמה: היא נראית מכוונת, ומנהל חשבונות
    שמאשר אותה מתייק להוצאה לכרטיס של ספק אחר לגמרי.
    """
    from cfo.database import SessionLocal

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _account(db, org_id, "400271", "אלון תבור-ספק", sort_code="400")
        expense = _expense(db, org_id, supplier="ספק מספוא")

        assert suggest_accounts_for_expense(db, org_id, expense.id) == []
    finally:
        db.close()


def test_a_distinctive_single_word_still_matches(fresh_org):
    """מילה בודדת אך ייחודית כן מספיקה — אחרת נאבד התאמות אמיתיות."""
    from cfo.database import SessionLocal

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _account(db, org_id, "400016", "קיבוץ מעלה גלבוע", sort_code="400")
        expense = _expense(db, org_id, supplier="גלבוע")

        suggestions = suggest_accounts_for_expense(db, org_id, expense.id)
        assert suggestions and suggestions[0]["source_account_code"] == "400016"
    finally:
        db.close()
