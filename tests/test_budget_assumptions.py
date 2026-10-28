"""Owner acceptance: one editable assumption list, the same budget in the forecast,
missing labelled with a date and never stored as 0.
"""
from datetime import date

from cfo.services.dashboards import cash_forecast, forecast_rules
from cfo.services.dashboards.budget_assumptions import (
    bank_pack, comparison_allowed, list_assumptions, missing_label, upsert_assumption,
)


AS_OF = date(2026, 10, 28)


def _view():
    return {
        "liquidity": {"position": {"balance": -12000.0, "as_of": "2026-10-28", "limit": 50000.0, "balance_source": "accounts"},
                      "checks": [], "upcoming": [], "debt_service": []},
        "cash_statement": {"months": [], "lines": []},
        "pnl": {"total_revenue": None, "total_expenses": None},
        "budget_vs_actual": {"status": "unknown", "months": []},
    }


def test_every_working_assumption_is_listed_and_missing_is_not_zero():
    rows = list_assumptions(None, ["2026-12"], as_of=AS_OF)
    kinds = {row["kind"] for row in rows}
    assert kinds == {
        "income", "payroll", "headcount", "suppliers", "vehicle", "interest", "loan_repayment", "opening_balance",
    }
    income = next(row for row in rows if row["kind"] == "income")
    assert income["amount"] is None
    assert income["missing_label"] == "חסר נכון ל-2026-10-28"
    assert income["amount"] != 0
    assert missing_label(AS_OF) == "חסר נכון ל-2026-10-28"


def test_the_owner_can_add_change_and_delete_an_assumption():
    plan = upsert_assumption(None, kind="income", month="2026-12", amount=50000, as_of=AS_OF)
    plan = upsert_assumption(plan, kind="income", month="2026-12", amount=62000, as_of=AS_OF)
    shown = next(row for row in list_assumptions(plan, ["2026-12"], as_of=AS_OF) if row["kind"] == "income")
    assert shown["amount"] == 62000
    assert shown["source"] == "owner"
    assert shown["status"] == "assumption"
    plan = upsert_assumption(plan, kind="income", month="2026-12", amount=None, as_of=AS_OF)
    cleared = next(row for row in list_assumptions(plan, ["2026-12"], as_of=AS_OF) if row["kind"] == "income")
    assert cleared["amount"] is None
    assert cleared["missing_label"] == "חסר נכון ל-2026-10-28"


def test_december_budget_shows_up_in_the_forecast_outflows():
    plan = {"budgetLines": []}
    plan = upsert_assumption(plan, kind="income", month="2026-12", amount=80000, as_of=AS_OF)
    plan = upsert_assumption(plan, kind="payroll", month="2026-12", amount=18000, as_of=AS_OF)
    plan = upsert_assumption(plan, kind="suppliers", month="2026-11", amount=30000, as_of=AS_OF)
    plan = upsert_assumption(plan, kind="loan_repayment", month="2026-12", amount=5000, as_of=AS_OF)
    plan = upsert_assumption(plan, kind="interest", month="2026-12", amount=900, as_of=AS_OF)
    plan = upsert_assumption(plan, kind="vehicle", month="2026-12", amount=2400, as_of=AS_OF)
    forecast = cash_forecast.build_entity_forecast(
        _view(), plan=plan, organization_id=7, label="בדיקה", today=AS_OF,
    )
    labels = [item.get("label") or "" for week in forecast["weeks"] for item in week["items"]]
    assert any("החזר קרן" in label for label in labels)
    assert any("ריבית לפי התקציב" in label for label in labels)
    assert any("רכב לפי התקציב" in label for label in labels)
    assert any("שכר" in label for label in labels)
    december_income = forecast_rules.income_amount(forecast_rules.load_lines(plan), "2026-12")
    assert december_income == 80000


def test_a_primary_budget_is_not_compared_with_consolidated_actuals():
    allowed, reason = comparison_allowed({"budgetScope": "primary"}, "combined")
    assert allowed is False
    assert reason
    assert comparison_allowed({"budgetScope": "combined"}, "combined")[0] is True
    assert comparison_allowed({}, "combined")[0] is True


def test_the_bank_pack_lists_assumptions_and_does_not_zero_a_missing_pnl():
    assumptions = list_assumptions(None, ["2026-12"], as_of=AS_OF)
    pack = bank_pack(_view(), assumptions, as_of=AS_OF)
    assert pack["pnl"]["revenue"]["amount"] is None
    assert pack["pnl"]["revenue"]["missing_label"] == "חסר נכון ל-2026-10-28"
    assert pack["assumptions"]
    assert pack["provider_calls"] == 0
