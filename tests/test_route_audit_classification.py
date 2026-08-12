"""audit_routes.py סיווג תשובות.

הבעיה שהטסטים האלה נועלים: הכלי תייג כל קוד שאינו 200/401/403/404/422 כ"כשל
(5xx/EXC)". בפועל 37 מתוך 37 ה"כשלים" היו 400 של "not configured" — routes של
SUMIT/Open-Finance בסביבה בלי קרדנשלים. משמעות: כל קורא — אדם או סוכן — קיבל 37
ממצאים מדומים, ו"כשל אמיתי" לא היה ניתן להבחנה מרעש סביבתי.

הסיווג הנכון הוא ארבעה דליים, ו"כשל" שמור לתקלה אמיתית בלבד.
"""
import importlib.util
from pathlib import Path

# נטען המודול הטהור, לא audit_routes.py עצמו — האחרון מייבא את האפליקציה ומשנה
# DATABASE_URL בזמן ייבוא, מה שהיה מזהם את הסוויטה.
spec = importlib.util.spec_from_file_location(
    "route_audit_report", Path(__file__).parent.parent / "scripts" / "route_audit_report.py"
)
audit_routes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_routes)

classify = audit_routes.classify


def test_200_is_ok():
    assert classify(200, "") == "OK"


def test_auth_and_shape_codes_are_warnings_not_failures():
    for code in (401, 403, 404, 422):
        assert classify(code, "") == "WARN", code


def test_400_missing_credentials_is_config_gated_not_a_failure():
    """הדלי החדש: הסביבה חסרה קרדנשלים, ה-route תקין ומחזיר 400 כן."""
    assert classify(400, "SUMIT API key not configured for this organization") == "CONFIG"
    assert classify(
        400,
        "Open Finance not configured: OPEN_FINANCE_CLIENT_ID, OPEN_FINANCE_CLIENT_SECRET",
    ) == "CONFIG"


def test_503_for_an_unconfigured_webhook_is_config_gated_not_a_failure():
    assert classify(503, "ערוץ WhatsApp לא מוגדר") == "CONFIG"
    assert classify(503, "Anthropic upstream timeout") == "FAIL"


def test_400_from_a_real_bug_is_still_a_failure():
    """400 שאינו על תצורה חסרה — למשל ולידציה שבורה — נשאר כשל."""
    assert classify(400, "invalid date range: end before start") == "FAIL"


def test_500_and_exceptions_are_failures():
    assert classify(500, "Internal Server Error") == "FAIL"
    assert classify("EXC:AttributeError", "") == "FAIL"


def test_summary_line_reports_the_four_buckets_separately():
    """שורת הסיכום היא החוזה מול qa_gate — היא חייבת לפרסם 'כשל' נקי
    ובנפרד את מוגדרי-הסביבה, אחרת qa_gate שופט על המספר הלא נכון."""
    line = audit_routes.summary_line(total=248, ok=172, warn=39, config=37, bad=0)
    assert "סהכ: 248" in line
    assert "תקין(200): 172" in line
    assert "אזהרה(4xx): 39" in line
    assert "מוגדר-סביבה: 37" in line
    assert "כשל: 0" in line
