"""קטלוג היכולות — כל מה ש-SUMIT ו-Open Finance יודעים לעשות, במקום אחד.

הבעיה שזה פותר: 116 מתודות ב-SUMIT ו-100 ב-Open Finance נבנו, אבל למושקו
נגישים 50 כלים בלבד. שתי השכבות לא מדברות, ואין שום מקום שבו אפשר לשאול
"איזו יכולת משרתת את המשימה הזו".

הקטלוג נגזר מהקוד ב-introspection ולא נכתב ביד — אחרת הוא מתיישן ברגע
שמישהו מוסיף מתודה.
"""
import pytest

from cfo.services.capability_catalog import (
    build_catalog,
    classify_kind,
    find_capabilities,
)


def test_catalog_covers_both_systems():
    catalog = build_catalog()

    assert set(catalog) == {"sumit", "open_finance"}


def test_catalog_includes_public_methods_and_excludes_private_plumbing():
    """מתודה ציבורית אמיתית נכנסת; עוזרי HTTP פרטיים ו-dunder לא —
    הם אינם 'יכולת' שאפשר להטיל עליה משימה."""
    catalog = build_catalog()
    sumit = {entry["name"] for entry in catalog["sumit"]}
    open_finance = {entry["name"] for entry in catalog["open_finance"]}

    assert "create_customer_remark" in sumit
    assert "test_connection" in sumit
    assert "_make_request" not in sumit
    assert "_post" not in sumit
    assert "__aenter__" not in sumit

    assert not any(name.startswith("_") for name in sumit | open_finance)


def test_every_entry_carries_the_fields_a_task_router_needs():
    """כל רשומה חייבת לשאת מספיק כדי שמושקו יבחר כלי בלי לנחש:
    למי היא שייכת, מה החתימה, ומה היא עושה."""
    catalog = build_catalog()

    for system, entries in catalog.items():
        assert entries, f"{system} החזיר קטלוג ריק"
        for entry in entries:
            assert entry["system"] == system
            assert entry["name"]
            assert isinstance(entry["parameters"], list)
            assert "summary" in entry


# ---------------------------------------------------------------------- #
# סיווג read/write — הבסיס ל"אפס אוטונומיה בבלתי-הפיך"
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name, summary, expected",
    [
        ("get_balance", "Get balance (GET /x/)", "read"),
        ("list_invoices", "", "read"),
        ("fetch_documents", "", "read"),
        ("search_customers", "", "read"),
        ("create_customer", "Create customer (POST /x/)", "write"),
        ("add_expense", "Add expense (POST /accounting/documents/addexpense/)", "write"),
        ("update_customer", "", "write"),
        ("delete_connection", "", "write"),
        ("send_document", "", "write"),
        ("cancel_payment", "", "write"),
    ],
)
def test_classify_kind_separates_reads_from_writes(name, summary, expected):
    assert classify_kind(name, summary) == expected


def test_ambiguous_name_is_unknown_not_guessed_as_read():
    """honest-null: שם שאינו מעיד על כיוון מסווג `unknown` ולא `read`.
    ניחוש לכיוון `read` הוא המסוכן — הוא מתיר קריאה אוטומטית לכלי שכותב."""
    assert classify_kind("process", "") == "unknown"
    assert classify_kind("begin_redirect", "") == "unknown"


def test_every_catalog_entry_is_classified():
    catalog = build_catalog()

    for entries in catalog.values():
        for entry in entries:
            assert entry["kind"] in {"read", "write", "unknown"}


def test_writes_are_flagged_as_requiring_approval():
    """כל יכולת כותבת נושאת דגל אישור — הדוקטרינה של אפס אוטונומיה
    בבלתי-הפיך חייבת להיות קריאה מהקטלוג, לא נזכרת בעל-פה."""
    catalog = build_catalog()
    entries = [entry for group in catalog.values() for entry in group]

    writes = [entry for entry in entries if entry["kind"] == "write"]
    assert writes, "לא זוהתה אף יכולת כותבת — הסיווג שבור"
    assert all(entry["requires_approval"] for entry in writes)
    assert not any(entry["requires_approval"] for entry in entries if entry["kind"] == "read")


# ---------------------------------------------------------------------- #
# חיפוש לפי משימה — "תשלח משימה, קבל את הכלים שמשרתים אותה"
# ---------------------------------------------------------------------- #
def test_find_capabilities_returns_matches_across_both_systems():
    """משימה על תנועות בנק צריכה להחזיר יכולות משתי המערכות אם לשתיהן
    יש מה לתרום — זו בדיוק ה"יכולת המקבילה"."""
    results = find_capabilities("transactions")

    assert results
    assert {entry["system"] for entry in results} == {"sumit", "open_finance"}


def test_find_capabilities_ranks_name_matches_above_summary_matches():
    """התאמה בשם היא אות חזק יותר מאזכור מקרי ב-docstring."""
    results = find_capabilities("expense")

    assert results
    assert "expense" in results[0]["name"].lower()


def test_find_capabilities_can_exclude_writes_for_safe_exploration():
    """מושקו שרק חוקר צריך לקבל יכולות קוראות בלבד — בלי סיכון
    להפעיל פעולה בלתי-הפיכה אצל הספק."""
    results = find_capabilities("customer", reads_only=True)

    assert results
    assert all(entry["kind"] == "read" for entry in results)
    assert not any(entry["requires_approval"] for entry in results)


def test_find_capabilities_returns_empty_for_nonsense_rather_than_guessing():
    assert find_capabilities("זבחזבחזבח") == []
