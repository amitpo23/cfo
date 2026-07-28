"""סיווג ודיווח עבור audit_routes.py — מודול טהור, בלי תופעות לוואי.

מופרד מ-`audit_routes.py` (שמייבא את האפליקציה ומשנה משתני סביבה בזמן ייבוא) כדי
שיהיה ניתן לבדיקה ישירה.

למה ארבעה דליים ולא שלושה: הגרסה הקודמת תייגה כל קוד שאינו 200/401/403/404/422
כ"כשל (5xx/EXC)". בפועל כל 37 ה"כשלים" היו 400 של "not configured" — routes של
SUMIT/Open-Finance בסביבה בלי קרדנשלים, כלומר התנהגות נכונה. התוצאה הייתה 37
ממצאים מדומים לכל קורא, וכשל אמיתי שלא ניתן להבחנה מרעש סביבתי.
"""

# חתימות של 400 שמשמעותו "הסביבה חסרה תצורה", לא "ה-route שבור"
_CONFIG_MARKERS = (
    "not configured",
    "לא מוגדר",
    "credentials missing",
    "missing credentials",
)


def classify(code, detail: str = "") -> str:
    """OK | WARN | CONFIG | FAIL.

    CONFIG = 400 שנובע מהיעדר קרדנשלים/תצורה בסביבת הבדיקה. תקין, לא ממצא.
    FAIL   = כל השאר: 5xx, חריגות, ו-400 שאינו על תצורה (למשל ולידציה שבורה).
    """
    if code == 200:
        return "OK"
    if isinstance(code, int) and code in (401, 403, 404, 422):
        return "WARN"
    if code == 400 and any(m in (detail or "").lower() for m in
                           (m.lower() for m in _CONFIG_MARKERS)):
        return "CONFIG"
    return "FAIL"


def summary_line(*, total: int, ok: int, warn: int, config: int, bad: int) -> str:
    """שורת הסיכום. זהו החוזה מול `qa_gate.py`, שמחלץ ממנה את מספר הכשלים —
    ולכן 'כשל' חייב להיות נקי ממוגדרי-סביבה."""
    return (
        f"סהכ: {total} | תקין(200): {ok} | אזהרה(4xx): {warn} | "
        f"מוגדר-סביבה(400): {config} | כשל: {bad}"
    )
