"""קטלוג היכולות כמפת משימות — מה מושקו יכול לבצע בפועל.

הקטלוג (`capability_catalog`) עונה "אילו endpoints קיימים". זה לא מספיק:
מי שמקבל משימה — "תוציא חשבונית", "תבדוק אם ההוצאה שולמה", "תתייק את
זה" — צריך לדעת **איזה כלי מבצע אותה ומה נדרש כדי להפעילו**.

המיפוי כאן הוא בין משימה עסקית לבין יכולת ביצוע: איזו מערכת, איזה כלי,
האם הוא כותב, ומה חוסם אותו בארגון מסוים.
"""
import pytest

from cfo.services.capability_tasks import (
    TASKS,
    executable_tasks_for_organization,
    resolve_task,
)


def test_the_task_map_covers_what_the_owner_asked_for(fresh_org):
    """המשימות שהוגדרו בשיחה: הוצאת מסמך, ביטול, קליטת הוצאה, תיוק,
    תזרים, בדיקת תשלום בבנק, והעברה לספק."""
    for task in (
        "issue_document", "cancel_document", "intake_expense", "file_expense",
        "cashflow", "check_payment_in_bank", "pay_supplier",
    ):
        assert task in TASKS, f"משימה חסרה: {task}"


def test_every_task_declares_system_tool_and_write_status():
    for name, task in TASKS.items():
        assert task["system"] in {"sumit", "open_finance", "rezef"}, name
        assert task["capability"], name
        assert isinstance(task["writes"], bool), name
        assert task["description_he"], name


def test_resolving_a_task_returns_something_actionable():
    resolved = resolve_task("issue_document")

    assert resolved["system"] == "sumit"
    assert resolved["writes"] is True
    assert resolved["requires_approval"] is True


def test_a_read_task_does_not_require_approval():
    assert resolve_task("cashflow")["requires_approval"] is False


def test_unknown_task_returns_none_rather_than_guessing():
    """honest-null: משימה שאינה במפה מחזירה None. ניחוש כלי לפי דמיון
    שם היה מפעיל פעולה לא נכונה על נתוני לקוח."""
    assert resolve_task("תעשה משהו") is None


# ---------------------------------------------------------------------- #
# מה ניתן לביצוע בארגון מסוים
# ---------------------------------------------------------------------- #
def test_tasks_are_blocked_when_the_organization_lacks_the_connection(fresh_org):
    """ארגון בלי חיבור Open Finance אינו יכול לבדוק תשלום בבנק.
    היכולת מוחזרת כחסומה עם הסיבה — לא נעלמת ולא מוחזרת כזמינה.

    זו בדיוק ההנחיה: ארגון בלי חיבור → היכולות שלו null (הבהרת בעלים)."""
    org_id = fresh_org()["org_id"]

    result = executable_tasks_for_organization(org_id)

    bank = next(t for t in result if t["task"] == "check_payment_in_bank")
    assert bank["executable"] is False
    assert "open_finance" in bank["blocked_by"]


def test_rezef_internal_tasks_are_executable_without_any_provider(fresh_org):
    """תיוק להוצאה מול האינדקס הוא פעולה פנימית של רצף — היא לא צריכה
    שום ספק חיצוני, ולכן זמינה גם לארגון בלי חיבורים."""
    org_id = fresh_org()["org_id"]

    result = executable_tasks_for_organization(org_id)

    filing = next(t for t in result if t["task"] == "file_expense")
    assert filing["executable"] is True
    assert filing["blocked_by"] == []


def test_every_task_is_reported_for_the_organization(fresh_org):
    """הרשימה מלאה תמיד — משימה חסומה מופיעה עם הסיבה. השמטה שקטה
    הייתה גורמת למי שקורא לחשוב שהיכולת לא קיימת."""
    org_id = fresh_org()["org_id"]

    result = executable_tasks_for_organization(org_id)

    assert {t["task"] for t in result} == set(TASKS)
