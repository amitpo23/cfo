"""שער כיסוי SUMIT↔מושקו — W3 גל 2 (20/08/2026).

כל מתודה ציבורית (async) של SumitIntegration חייבת להופיע בדיוק באחד
משלושה מקומות במניפסט (services/sumit_tool_manifest.py):

1. TOOL_METHOD_MAP — חשופה ככלי מושקו (ישירות או דרך service);
2. ALREADY_COVERED — בשימוש כלי/שירות/route קיים, לא מכפילים;
3. EXCLUDED_SUMIT_METHODS — הוחלט לא לחשוף, עם סיבה בעברית.

מתודה עתידית שתתווסף לקליינט בלי הכרעה מפורשת — הטסט הראשון כאן ייכשל
וידרוש להכריע. זה השער שמונע את הפער שהיה: 89 מתודות עטופות ורק 11
נגישות למושקו, בלי שאף אחד יודע מה חסר ולמה.
"""
import inspect

from cfo.integrations.sumit_integration import SumitIntegration
from cfo.services import ai_chat_tools
from cfo.services import sumit_tool_manifest as manifest
from cfo.services.ai_chat_tools import TOOLS


def _public_async_methods() -> set[str]:
    return {
        name
        for name, _member in inspect.getmembers(
            SumitIntegration, predicate=inspect.iscoroutinefunction,
        )
        if not name.startswith("_")
    }


def _tool_covered_methods() -> set[str]:
    covered: set[str] = set()
    for methods in manifest.TOOL_METHOD_MAP.values():
        covered.update(methods)
    return covered


def test_every_public_sumit_method_is_dispositioned():
    """הטסט המרכזי: אין מתודה ציבורית ללא הכרעה (כלי/מכוסה/מוחרגת)."""
    methods = _public_async_methods()
    dispositioned = (
        _tool_covered_methods()
        | set(manifest.ALREADY_COVERED)
        | set(manifest.EXCLUDED_SUMIT_METHODS)
    )
    missing = methods - dispositioned
    assert not missing, (
        "מתודות SumitIntegration ללא הכרעה במניפסט — יש להוסיף כל אחת "
        "ל-TOOL_METHOD_MAP (כלי), ל-ALREADY_COVERED (שירות קיים) או "
        f"ל-EXCLUDED_SUMIT_METHODS (עם סיבה): {sorted(missing)}"
    )


def test_manifest_lists_only_real_methods():
    """אין רשומות עבשות — כל שם במניפסט הוא מתודה ציבורית אמיתית."""
    methods = _public_async_methods()
    for name in _tool_covered_methods():
        assert name in methods, f"TOOL_METHOD_MAP מפנה למתודה לא קיימת: {name}"
    for name in manifest.ALREADY_COVERED:
        assert name in methods, f"ALREADY_COVERED מכיל מתודה לא קיימת: {name}"
    for name in manifest.EXCLUDED_SUMIT_METHODS:
        assert name in methods, f"EXCLUDED מכיל מתודה לא קיימת: {name}"


def test_manifest_categories_are_disjoint():
    """מתודה מוכרעת פעם אחת בדיוק — חשופה/מכוסה/מוחרגת, לא שילוב."""
    tool_methods = _tool_covered_methods()
    covered = set(manifest.ALREADY_COVERED)
    excluded = set(manifest.EXCLUDED_SUMIT_METHODS)
    assert not (tool_methods & excluded), sorted(tool_methods & excluded)
    assert not (covered & excluded), sorted(covered & excluded)
    assert not (tool_methods & covered), sorted(tool_methods & covered)


def test_every_mapped_tool_is_registered_and_classified_sumit():
    """כל מפתח ב-TOOL_METHOD_MAP הוא כלי רשום; כלי שאינו office חייב
    להיות מסווג _SUMIT_TOOLS (משמעת עלויות + דיווח target system)."""
    for tool_name in manifest.TOOL_METHOD_MAP:
        assert tool_name in TOOLS, f"כלי לא רשום בקטלוג: {tool_name}"
        if not TOOLS[tool_name].office:
            assert tool_name in ai_chat_tools._SUMIT_TOOLS, (
                f"כלי SUMIT שאינו מסווג ב-_SUMIT_TOOLS: {tool_name}"
            )


def test_excluded_reasons_are_meaningful():
    for name, reason in manifest.EXCLUDED_SUMIT_METHODS.items():
        assert isinstance(reason, str) and len(reason.strip()) >= 15, (
            f"סיבת אי-חשיפה חסרה/דלה עבור {name}"
        )


def test_already_covered_names_a_real_consumer():
    for name, consumer in manifest.ALREADY_COVERED.items():
        assert isinstance(consumer, str) and len(consumer.strip()) >= 5, (
            f"ALREADY_COVERED חייב לנקוב בכלי/שירות שמשתמש ב-{name}"
        )


def test_card_data_methods_are_hard_excluded():
    """נעילת בטיחות: מתודות שמקבלות פרטי כרטיס גולמיים (PAN/CVV/תוקף)
    לעולם אינן נחשפות למושקו — באמצעי שמור/טוקן בלבד."""
    card_methods = {
        "tokenize_card", "tokenize_single_use", "tokenize_single_use_json",
        "create_card_transaction",
    }
    for name in card_methods:
        assert name in manifest.EXCLUDED_SUMIT_METHODS, name
        assert name not in _tool_covered_methods(), name


# ------------------------------------------------------------------ #
# התנהגות גל 2 — שערי קלט לפני רשת ומיסוך פלט
# ------------------------------------------------------------------ #

def _forbid_network(monkeypatch):
    """כל בנייה של קליינט SUMIT בטסט הזה = כשל (הכלי חייב לחסום קודם)."""
    from cfo.services import recurring_billing_service

    async def _boom(*_a, **_k):
        raise AssertionError("client was built despite invalid input")

    monkeypatch.setattr(recurring_billing_service, "_client_for_org", _boom)


def test_charge_customer_rejects_non_positive_amount_before_network(monkeypatch):
    import asyncio
    _forbid_network(monkeypatch)
    result = asyncio.run(TOOLS["charge_customer"].fn(
        None, 1, customer_id="7", amount=0,
    ))
    assert "error" in result


def test_subscribe_trigger_requires_https_before_network(monkeypatch):
    import asyncio
    _forbid_network(monkeypatch)
    result = asyncio.run(TOOLS["subscribe_trigger"].fn(
        None, 1, trigger_type="DocumentCreated", webhook_url="http://insecure",
    ))
    assert "error" in result and "https" in result["error"]


def test_send_multiple_sms_requires_regulatory_optin(fresh_org, monkeypatch):
    """בלי opt-in (collection_reminders_enabled) — אין רשת ואין שליחה."""
    import asyncio
    from cfo.database import SessionLocal

    _forbid_network(monkeypatch)
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["send_multiple_sms"].fn(
            db, org_id,
            messages=[{"phone": "0501234567", "message": "בדיקה"}],
        ))
    finally:
        db.close()
    assert "error" in result


def test_get_payment_methods_output_is_masked(monkeypatch):
    """הפלט מוגבל לשדות ממוסכים — לעולם לא מספר כרטיס מלא."""
    import asyncio
    from cfo.integrations.sumit_models import PaymentMethodResponse

    async def _fake_call(_db, _org_id, _call):
        return [PaymentMethodResponse(
            payment_method_id="55", type="CreditCard",
            last_4_digits="1234", expiry_date="01/2030", is_default=True,
        )]

    monkeypatch.setattr(ai_chat_tools, "_sumit_call", _fake_call)
    result = asyncio.run(TOOLS["get_payment_methods"].fn(None, 1, customer_id="7"))
    assert result["payment_methods"] == [{
        "payment_method_id": "55", "type": "CreditCard",
        "last_4_digits": "1234", "expiry_date": "01/2030", "is_default": True,
    }]


def test_not_supported_methods_are_excluded():
    """מתודות שמסומנות NOT SUPPORTED בקוד הקליינט (זורקות תמיד) אינן
    נחשפות — כלי שתמיד נכשל מפר honest-null."""
    for name in (
        "get_entities_html", "charge_recurring", "send_letter_by_click",
        "get_letter_tracking_code", "open_upay_terminal",
    ):
        assert name in manifest.EXCLUDED_SUMIT_METHODS, name
