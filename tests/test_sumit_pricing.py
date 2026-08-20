"""מנוע המחירון של SUMIT — "שנדע תמיד בקאונטר אם חורגים מה העלות".

מקור: מאמר 5507895 ("איך עובד המחירון", docs/sumit_help_kb/02):
- קריאות API כלולות = פי 5 ממכסת הפעולות של המסלול.
- חריגת קריאת API = 25% ממחיר פעולה.
- חריגת אחסון = 5 ש"ח ל-GB לחודש.
- פעולה משולבת (מסמך+סליקה) = 2 פעולות.

honest-null: מחיר הפעולה עצמו נמצא בדף מחירון חיצוני פר-מסלול ואינו
בתיעוד — בלי מחיר מוגדר, הקאונטר מציג חריגה בכמויות + נוסחה, לא שקלים
מומצאים.
"""
import pytest

from cfo.services import sumit_pricing


def test_included_api_calls_are_five_times_included_actions():
    assert sumit_pricing.included_api_calls(included_actions=100) == 500


def test_overage_cost_with_configured_price():
    est = sumit_pricing.estimate_costs(
        actions_used=120, actions_included=100,
        api_calls_used=520, action_price_ils=2.0,
    )
    assert est["actions_overage"] == 20
    assert est["actions_overage_cost_ils"] == 40.0
    # חריגת קריאות: 520 - 500 = 20 קריאות × (25% × 2 ש"ח) = 10 ש"ח
    assert est["api_calls_overage"] == 20
    assert est["api_calls_overage_cost_ils"] == 10.0
    assert est["total_estimated_overage_ils"] == 50.0
    assert est["priced"] is True


def test_overage_without_price_is_honest_null():
    est = sumit_pricing.estimate_costs(
        actions_used=120, actions_included=100,
        api_calls_used=0, action_price_ils=None,
    )
    assert est["actions_overage"] == 20
    assert est["actions_overage_cost_ils"] is None
    assert est["total_estimated_overage_ils"] is None
    assert est["priced"] is False
    assert "reason" in est


def test_no_overage_costs_nothing():
    est = sumit_pricing.estimate_costs(
        actions_used=30, actions_included=100,
        api_calls_used=100, action_price_ils=2.0,
    )
    assert est["actions_overage"] == 0
    assert est["api_calls_overage"] == 0
    assert est["total_estimated_overage_ils"] == 0.0


def test_budget_status_tool_includes_cost_section(client, fresh_org):
    """הקאונטר של מושקו מציג את שכבת העלות — כולל honest-null על מחיר."""
    import asyncio

    from cfo.database import SessionLocal
    from cfo.services.ai_chat_tools import TOOLS

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["get_sumit_budget_status"].fn(db, org_id))
    finally:
        db.close()
    assert "cost" in result
    cost = result["cost"]
    assert "pricing_model" in cost
    assert "פי 5" in cost["pricing_model"]["included_api_calls_rule"]


def test_cost_section_prices_overage_when_measurement_and_price_exist(client, fresh_org, monkeypatch):
    """עם מדידה טרייה + מחיר מוגדר — הקאונטר מציג שקלים אמיתיים."""
    import asyncio
    from datetime import datetime, timezone

    from cfo.config import settings
    from cfo.database import SessionLocal
    from cfo.services import sumit_quota
    from cfo.services.ai_chat_tools import TOOLS

    org_id = fresh_org()["org_id"]
    monkeypatch.setattr(settings, "sumit_plan_action_price_ils", 2.0)
    db = SessionLocal()
    try:
        sumit_quota.store_measurement(db, sumit_quota.QuotaSnapshot(
            organization_id=org_id, used=60, limit=50,
            measured_at=datetime.now(timezone.utc),
        ))
        db.commit()
        result = asyncio.run(TOOLS["get_sumit_budget_status"].fn(db, org_id))
    finally:
        db.close()
    cost = result["cost"]
    assert cost["provider_measurement"]["used"] == 60
    assert cost["estimate"]["actions_overage"] == 10
    assert cost["estimate"]["actions_overage_cost_ils"] == 20.0
    assert "warning" in cost
