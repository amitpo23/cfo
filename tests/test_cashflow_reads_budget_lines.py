"""Cash forecast expected flows come from plan.budgetLines, the /budget store.

No budget stays missing. A filled line is not reported as zero.
"""
from datetime import date

from cfo.database import SessionLocal
from cfo.services.dashboards import cash_forecast
from cfo.services.dashboard_service import DashboardService


def _drivers(month: str):
    return [
        {
            "id": "del_revenue", "label": "הכנסות משלוחים", "kind": "income", "custom": True,
            "division": "משלוחים", "month": month, "status": "filled",
            "qty": 10, "unit_price": 1500, "amount": 15000,
        },
        {
            "id": "del_ops", "label": "תפעול משלוחים", "kind": "expense", "custom": True,
            "division": "משלוחים", "month": month, "status": "filled",
            "qty": 1, "unit_price": 4000, "amount": 4000,
        },
    ]


def test_projection_without_a_budget_is_missing_not_zero(client, fresh_org):
    org = fresh_org()
    db = SessionLocal()
    try:
        weeks = DashboardService(db, org["org_id"]).get_cashflow_projection(weeks=4)
    finally:
        db.close()
    assert len(weeks) == 4
    assert all(week["expected_inflows"] is None for week in weeks)
    assert all(week["expected_outflows"] is None for week in weeks)
    assert all(week["expected_inflows"] != 0 for week in weeks)


def test_projection_uses_the_same_budget_lines_as_budget_entry(client, fresh_org):
    org = fresh_org()
    created = client.post("/api/dashboards", headers=org["headers"], json={
        "primary_organization_id": org["org_id"],
        "slug": f"forecast-budget-{org['org_id']}",
        "title": "תזרים",
        "access_mode": "members",
    })
    assert created.status_code == 201, created.text
    saved = client.put("/api/financial/budget/lines", headers=org["headers"], json={"updates": _drivers("2026-11")})
    assert saved.status_code == 200, saved.text

    response = client.get("/api/dashboard/cashflow?weeks=8", headers=org["headers"])
    assert response.status_code == 200, response.text
    weeks = response.json()
    assert any(week.get("source") == "plan.budgetLines" for week in weeks)
    inflows = [week["expected_inflows"] for week in weeks if week["expected_inflows"]]
    outflows = [week["expected_outflows"] for week in weeks if week["expected_outflows"]]
    assert inflows, weeks
    assert outflows, weeks
    assert sum(inflows) > 0
    assert sum(outflows) > 0


def test_thirteen_week_forecast_keeps_known_budget_flows():
    from cfo.services.dashboards.budget_fill import apply_updates

    plan = apply_updates({"budgetLines": []}, _drivers("2026-11"))
    view = {
        "liquidity": {"position": {"balance": 1000, "as_of": "2026-10-31", "limit": 5000}, "checks": [], "upcoming": [], "debt_service": []},
        "cash_statement": {"months": [], "lines": []},
        "pnl": {},
        "budget_vs_actual": {"status": "unknown", "months": []},
    }
    forecast = cash_forecast.build_entity_forecast(
        view, plan=plan, organization_id=6, label="פוד", today=date(2026, 11, 1),
    )
    ins = [week["in"] for week in forecast["weeks"] if week["in"]]
    outs = [week["out"] for week in forecast["weeks"] if week["out"]]
    assert sum(ins) > 0
    assert sum(outs) < 0
    labels = [item.get("label") for week in forecast["weeks"] for item in week["items"]]
    assert "תפעול משלוחים" in labels
