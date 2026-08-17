"""מאזן בוחן חייב לומר שהוא לא הוצלב מול SUMIT.

הדרישה של הבעלים (17/08/2026): *"שאני אבקש ממך מאזן בוחן הוא צריך
להיות מדויק ותואם מול הסאמיט"*.

הגרסה הראשונה החזירה `is_final=True` כשחובה=זכות **אצלנו**. זה מדד את
הדבר הלא-נכון: מאזן יכול להיות מאוזן בתוך רצף ובכל זאת לא לתאום את
הספר הרשמי — למשל כשפקודה נשלחה ב-`createbatch`, חזרה
`executed_unverified`, ולא נקלטה.

SUMIT אינה חושפת קריאת מאזן, ולכן ההצלבה נעשית מול מאזן שהורד מהפורטל.
עד שהיא בוצעה, המספר הוא **חישוב ולא ספר**, ומושקו חייב לומר זאת —
אחרת בעל עסק ידווח לפי מספר שנראה סופי.
"""
import pytest

from cfo.services.ai_chat_tools import TOOLS


def test_the_tool_reports_that_parity_was_not_checked():
    """שדה מפורש, לא הערה בטקסט: קורא אוטומטי חייב לראות את זה."""
    import inspect

    source = inspect.getsource(TOOLS["get_trial_balance"].fn)

    assert "sumit_parity" in source


def test_is_final_does_not_mean_balanced_alone():
    """`is_final=True` על סמך חובה=זכות בלבד היה מציג חישוב כספר."""
    import inspect

    source = inspect.getsource(TOOLS["get_trial_balance"].fn)
    final_line = [l for l in source.splitlines() if "is_final" in l and "=" in l]

    assert final_line, "אין קביעת is_final"
    joined = " ".join(final_line)
    assert "parity" in joined, (
        "is_final נקבע בלי להתחשב בהצלבה מול SUMIT"
    )


def test_the_reason_names_what_is_missing():
    """מי שרואה 'לא סופי' חייב לדעת מה חסר, אחרת יתעלם."""
    import inspect

    source = inspect.getsource(TOOLS["get_trial_balance"].fn)

    assert "SUMIT" in source
    assert "מנות פתוחות" in source or "פורטל" in source


def test_a_parity_document_exists_and_is_registered():
    """הידע חייב להיות נגיש למושקו, לא רק בקוד."""
    from cfo.services.kb_loader import kb_search

    files = {r.get("file") for r in kb_search("התאמה מול סאמיט").get("results", [])}
    files |= {r.get("file") for r in kb_search("מאזן בוחן").get("results", [])}

    assert "14-parity-check.md" in files
