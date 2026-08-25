"""S6 (ספרינט זהות-מושקו, 25/08/2026) — פרוטוקול-תור סדור.

הפער: BASE_SYSTEM_PROMPT אומר *מה* מושקו יודע (כלים, ערנות-חשבונאית,
honest-null) אבל לא *באיזה סדר* לעבוד בכל תור. תוסף מפורש — לא שכתוב
— כדי שאפס תוכן קיים יאבד: כל המחרוזות הקודמות שהיו ב-BASE_SYSTEM_PROMPT
(נבדק ב-test_content_preserved) חייבות להישאר, מילה במילה.
"""
from cfo.services.ai_chat_personas import BASE_SYSTEM_PROMPT, TURN_PROTOCOL

# תוכן שהיה קיים ב-BASE_SYSTEM_PROMPT לפני S6 (25/08/2026) — קטעים
# ייצוגיים מכל חלק: זהות, כלים, זיכרון, ערנות-חשבונאית, honest-null.
# אם אחד מהם נעלם — S6 איבד תוכן, לא רק הוסיף מבנה.
_PRE_S6_FRAGMENTS = (
    "אתה מושקו, ה-CFO הדיגיטלי של רצף",
    "rezef_help",
    "יש לך גם זיכרון לומד דרך כלי memory",
    "ערנות חשבונאית תמידית",
    "get_bank_reconciliation ו/או get_ap_aging",
    "לעצור ולשאול לפני שמבקשים עליה מע\"מ",
    "honest-null גובר תמיד",
)


def test_content_preserved_nothing_lost():
    for fragment in _PRE_S6_FRAGMENTS:
        assert fragment in BASE_SYSTEM_PROMPT, f"תוכן קיים נעלם: {fragment!r}"


def test_turn_protocol_defines_the_four_ordered_steps():
    for step in ("זהה כוונה", "בחר כובע", "הצלב מול בנק", "תבנית תשובה"):
        assert step in TURN_PROTOCOL, f"שלב חסר בפרוטוקול: {step!r}"


def test_turn_protocol_step_order_matches_the_declared_sequence():
    positions = [TURN_PROTOCOL.index(step) for step in
                 ("זהה כוונה", "בחר כובע", "הצלב מול בנק", "תבנית תשובה")]
    assert positions == sorted(positions), "סדר השלבים בטקסט לא תואם את הרצף המוצהר"


def test_turn_protocol_is_actually_injected_into_the_composed_prompt():
    from cfo.services.ai_chat_personas import build_system_prompt, resolve_persona

    prompt = build_system_prompt(resolve_persona("cfo"), include_office=False)
    assert "זהה כוונה" in prompt
