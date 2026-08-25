"""Truth Model (בריף-הזהות של הבעלים, 25/08/2026): VERIFIED/CALCULATED/
FORECAST/UNVERIFIED_NEEDS_REVIEW. מיפוי-הארכיטקטורה (Fable, אותו יום)
המליץ על עטיפה בנקודת-החנק הקיימת (_execute_tool_observed) עם שדה
truth_class סטטי על ChatTool + downgrade דינמי מדגלי-אי-ודאות שכבר
קיימים בתוצאות (is_provisional, warning_he, checks, unmatched) —
אדיטיבי בלבד, לא סכימה/DB חדשים.
"""
import asyncio

from cfo.services.ai_chat_tools import TOOLS, ChatTool, infer_truth


def _tool(**overrides):
    base = dict(
        name="fake_tool", description="d", input_schema={"type": "object", "properties": {}},
        category="read", fn=None,
    )
    base.update(overrides)
    return ChatTool(**base)


# ---------------------------------------------------------------------- #
# ברירות מחדל סטטיות
# ---------------------------------------------------------------------- #
def test_default_truth_class_is_calculated():
    tool = _tool()
    assert tool.truth_class == "calculated"


def test_forecast_tools_default_to_forecast_class():
    assert TOOLS["get_cashflow"].truth_class == "forecast"


def test_bank_reconciliation_defaults_to_verified():
    assert TOOLS["get_bank_reconciliation"].truth_class == "verified"


# ---------------------------------------------------------------------- #
# infer_truth — downgrade דינמי מדגלים בתוצאה עצמה
# ---------------------------------------------------------------------- #
def test_clean_result_keeps_the_static_class():
    tool = _tool(truth_class="verified")
    result = {"balance": 1000}

    truth = infer_truth(tool, result)

    assert truth["class"] == "verified"
    assert truth["caveats"] == []


def test_is_provisional_downgrades_to_needs_review():
    tool = _tool(truth_class="verified")
    result = {"transactions": [{"amount": 100, "is_provisional": True}]}

    truth = infer_truth(tool, result)

    assert truth["class"] == "unverified_needs_review"
    assert truth["caveats"]


def test_unmatched_txns_downgrades_to_needs_review():
    tool = _tool(truth_class="verified")
    result = {"matched": [1, 2], "unmatched_txns": [{"id": 9}]}

    truth = infer_truth(tool, result)

    assert truth["class"] == "unverified_needs_review"
    assert "1" in truth["caveats"][0] or "לא הותאמ" in truth["caveats"][0]


def test_failed_check_downgrades_to_needs_review():
    tool = _tool(truth_class="calculated")
    result = {"checks": [{"name": "sum", "status": "pass"}, {"name": "freshness", "status": "fail"}]}

    truth = infer_truth(tool, result)

    assert truth["class"] == "unverified_needs_review"


def test_warning_he_downgrades_to_needs_review():
    tool = _tool(truth_class="calculated")
    result = {"total": 1000, "warning_he": "המספרים אינם עדות לרווחיות בפועל"}

    truth = infer_truth(tool, result)

    assert truth["class"] == "unverified_needs_review"
    assert "רווחיות" in truth["caveats"][0]


def test_forecast_is_never_upgraded_by_a_clean_result():
    """תחזית נשארת תחזית גם כשאין דגלי-אזהרה — לעולם לא 'verified'."""
    tool = _tool(truth_class="forecast")
    result = {"weeks": [{"cumulative_balance": 5000}]}

    truth = infer_truth(tool, result)

    assert truth["class"] == "forecast"


def test_non_dict_result_returns_calculated_with_no_caveats():
    tool = _tool(truth_class="verified")
    truth = infer_truth(tool, ["not", "a", "dict"])
    assert truth["class"] == "calculated"
    assert truth["caveats"] == []


# ---------------------------------------------------------------------- #
# חיווט בפועל — _execute_tool_observed מצרף "truth" לתוצאה
# ---------------------------------------------------------------------- #
def test_execute_tool_observed_attaches_truth_to_the_result(fresh_org):
    from cfo.database import SessionLocal
    from cfo.services.ai_chat_service import AIChatService

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        service = AIChatService(db, org_id, user_id=1, is_super_admin=False)

        async def fake_fn(db, org_id, **kw):
            return {"weeks": [{"cumulative_balance": 100}]}

        tool = _tool(name="get_cashflow", truth_class="forecast", fn=fake_fn)
        result = asyncio.run(service._execute_tool_observed(
            tool=tool, call_kwargs={}, logged_arguments={},
            session_id="s1", message_id=None, propagate=False,
        ))

        assert result["truth"]["class"] == "forecast"
    finally:
        db.close()


def test_turn_protocol_instructs_the_model_to_honor_truth_classification():
    from cfo.services.ai_chat_personas import TURN_PROTOCOL

    assert "verified" in TURN_PROTOCOL
    assert "forecast" in TURN_PROTOCOL
