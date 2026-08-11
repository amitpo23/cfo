"""תצוגת ספרים לתיק — עבר, הווה, ומה חסר.

הפער שזה סוגר: לעומר ועודד יש בפרוד 15,060 פקודות יומן, 1,004 כרטיסי
אינדקס ו-214 הוצאות — כולם מאומתים ומחוברים — **ואין שום מקום לראות
אותם**. הם נגישים רק בשאילתת SQL ידנית.

התצוגה מפרידה במפורש בין שתי תקופות, כי מקור האמת שלהן שונה:
  * עד קו החיתוך — הספרים שיובאו מההנה"ח הקודמת (חשבשבת), שדווחו כבר
  * מקו החיתוך — התקופה החיה, שמסונכרנת מ-SUMIT
ערבוב שלהן היה מציג את אותה תנועה פעמיים.
"""
from datetime import date

from cfo.services.org_books_view import org_books_view


def test_view_separates_imported_past_from_live_present(fresh_org):
    org_id = fresh_org()["org_id"]

    view = org_books_view(org_id, cutoff=date(2026, 6, 30))

    assert "imported_past" in view
    assert "live_period" in view
    assert view["cutoff"] == "2026-06-30"


def test_past_section_reports_the_journal_that_was_imported(fresh_org):
    org_id = fresh_org()["org_id"]

    past = org_books_view(org_id, cutoff=date(2026, 6, 30))["imported_past"]

    for key in ("journal_entries", "debit_total", "credit_total", "imbalance", "first_date", "last_date"):
        assert key in past


def test_live_section_reports_what_still_needs_work(fresh_org):
    """התקופה החיה היא שם העבודה נמצאת: מה לא מתויק, מה בלי סכום."""
    org_id = fresh_org()["org_id"]

    live = org_books_view(org_id, cutoff=date(2026, 6, 30))["live_period"]

    for key in ("expenses", "unfiled", "zero_sum", "invoices"):
        assert key in live


def test_index_section_reports_the_chart_of_accounts(fresh_org):
    org_id = fresh_org()["org_id"]

    index = org_books_view(org_id, cutoff=date(2026, 6, 30))["index"]

    assert "accounts" in index
    assert "by_sort_code" in index


def test_view_lists_concrete_blockers_rather_than_a_vague_status(fresh_org):
    """מי שקורא צריך לדעת מה לעשות, לא רק שמשהו לא בסדר."""
    org_id = fresh_org()["org_id"]

    view = org_books_view(org_id, cutoff=date(2026, 6, 30))

    assert isinstance(view["blockers"], list)


def test_missing_organization_returns_none(fresh_org):
    assert org_books_view(999_999) is None
