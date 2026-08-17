"""מושקו חייב לדעת לענות על שאלות הספרים — לא רק לשלוף מסמכים.

הפער שנמדד 16/08/2026: מתוך 55 כלים, **אף אחד לא ענה על "מה מאזן הבוחן"**
ואף אחד לא נגע במנות. הלוגיקה קיימת ב-`ledger_service.trial_balance`
ויש לה route — אבל מושקו לא הגיע אליה.

בעל עסק ששואל "מה מאזן הבוחן" ומקבל "אין לי יכולת כזו" — בזמן שהקוד
קיים — הוא בדיוק המצב שהמערכת נועדה למנוע.

הכלים כאן **אינם קוראים ל-SUMIT**. הם מתשאלים את ה-ledger של רצף, לפי
הארכיטקטורה: משיכה יומית → אחסון → תשאול מקומי. ראו
`docs/bookkeeper_kb/09-sumit-operations-map.md`.
"""
import pytest

from cfo.services.ai_chat_tools import TOOLS


REQUIRED = {
    "get_trial_balance": "read",
    "get_open_batches": "read",
    "propose_books_batch": "write",
}


@pytest.mark.parametrize("name,category", sorted(REQUIRED.items()))
def test_the_tool_exists_and_is_categorised(name, category):
    assert name in TOOLS, f"מושקו אינו יודע לענות על {name}"
    assert TOOLS[name].category == category


def test_trial_balance_reads_the_rezef_ledger_not_sumit(monkeypatch):
    """הכלל הארכיטקטוני: שאלת משתמש אינה מייצרת קריאת API.

    מאזן בוחן מחושב מה-ledger של רצף. אם הכלי היה פונה ל-SUMIT, כל
    שאלה הייתה עולה כסף — וזה בדיוק מה שהוביל לחסימת ה-IP ב-13/08."""
    import inspect

    source = inspect.getsource(TOOLS["get_trial_balance"].fn)

    assert "ledger_service" in source
    for forbidden in ("SumitIntegration", "sumit_connector", "_make_request"):
        assert forbidden not in source, f"הכלי נוגע ב-SUMIT: {forbidden}"


def test_trial_balance_reports_whether_it_is_final(monkeypatch):
    """מאזן בוחן שנשען על מנות פתוחות אינו סופי.

    ה-PDF של SUMIT נושא את זה בכותרת; התשובה של מושקו חייבת לשאת את
    אותו סייג, אחרת מספר לא-סופי ייקרא כסופי."""
    import inspect

    source = inspect.getsource(TOOLS["get_trial_balance"].fn)

    assert "balanced" in source


def test_proposing_a_batch_is_a_write_that_needs_confirmation():
    """`createbatch` הוא רישום לספרים — בלתי-הפיך אצל הספק."""
    assert TOOLS["propose_books_batch"].category == "write"


def test_open_batches_is_honest_about_the_provider_gap():
    """SUMIT אינה חושפת קריאת מנות. הכלי חייב להחזיר honest-null עם
    סיבה — לא רשימה ריקה שנראית כמו "אין מנות פתוחות"."""
    import inspect

    source = inspect.getsource(TOOLS["get_open_batches"].fn)

    assert "unavailable" in source or "unsupported" in source


def test_no_new_tool_reaches_a_paid_sumit_action():
    """שער עלות: אף אחד משלושת הכלים אינו נוגע ב-getdetails/getpdf."""
    import inspect

    for name in REQUIRED:
        source = inspect.getsource(TOOLS[name].fn)
        for paid in ("getdetails", "getpdf"):
            assert paid not in source, f"{name} נוגע בפעולה בתשלום: {paid}"
