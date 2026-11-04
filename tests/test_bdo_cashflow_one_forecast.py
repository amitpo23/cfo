"""/dashboard/cashflow reads the same 13-week forecast as /cashflow/weekly.

That forecast carries loans, payroll, cards and the operating run-rate, and keeps
cheque discounting as financing. A week with no known outflow is missing, never
0. Made-up amounts only.
"""
from datetime import date

from cfo.database import SessionLocal
from cfo.services import dashboard_service as ds
from cfo.services.dashboard_service import DashboardService

TODAY = date(2026, 11, 4)

FORECAST = {
    "status": "ready",
    "opening": {"amount": -20000.0, "as_of": "2026-11-03"},
    "missing": [],
    "weeks": [
        {"start": "2026-11-04", "end": "2026-11-10", "in": 9000.0, "out": -15000.0, "net": -6000.0,
         "closing": -26000.0, "limit": 30000.0, "headroom": 4000.0, "unknown": [],
         "items": [{"label": "שכר", "amount": -12000.0}, {"label": "קרן הלוואה", "amount": -3000.0}]},
        {"start": "2026-11-11", "end": "2026-11-17", "in": 0.0, "out": 0.0, "net": 0.0,
         "closing": -26000.0, "limit": 30000.0, "headroom": 4000.0, "unknown": [], "items": []},
        {"start": "2026-11-18", "end": "2026-11-24", "in": 5000.0, "out": -4000.0, "net": None,
         "closing": None, "limit": 30000.0, "headroom": None, "unknown": ["מע״מ לא ידוע"], "items": []},
    ],
}


def test_dashboard_cashflow_is_the_13_week_forecast(fresh_org, monkeypatch):
    owner = fresh_org()
    monkeypatch.setattr(ds, "published_cash_forecast", lambda db, org_id, today: FORECAST)
    with SessionLocal() as db:
        rows = DashboardService(db, owner["org_id"]).get_cashflow_projection(weeks=4, today=TODAY)
    assert len(rows) == 4
    first, quiet, partial, beyond = rows
    assert first["week"] == "2026-11-04"
    assert (first["expected_inflows"], first["expected_outflows"], first["net_flow"]) == (9000.0, 15000.0, -6000.0)
    assert first["cumulative_balance"] == -26000.0
    assert first["limit"] == 30000.0 and first["headroom"] == 4000.0
    assert first["source"] == "cash_forecast_13w"
    # Nothing known that week is missing, not a 0 outflow.
    assert quiet["expected_outflows"] is None and quiet["expected_inflows"] is None
    assert quiet["net_flow"] is None
    assert partial["unknown"] == ["מע״מ לא ידוע"]
    assert partial["net_flow"] is None and partial["cumulative_balance"] is None
    # Past the forecast horizon nothing is invented.
    assert beyond["expected_outflows"] is None and beyond["cumulative_balance"] is None


def test_no_forecast_and_no_open_documents_is_missing_not_zero(fresh_org, monkeypatch):
    owner = fresh_org()
    monkeypatch.setattr(ds, "published_cash_forecast", lambda db, org_id, today: None)
    with SessionLocal() as db:
        rows = DashboardService(db, owner["org_id"]).get_cashflow_projection(weeks=2, today=TODAY)
    assert [row["expected_outflows"] for row in rows] == [None, None]
    assert [row["expected_inflows"] for row in rows] == [None, None]


def test_weekly_route_carries_credit_lines_and_the_freshness_banner(client, fresh_org):
    owner = fresh_org()
    body = client.get("/api/cashflow/weekly", headers=owner["headers"]).json()
    assert "credit_lines" in body["snapshot"]
    assert "בנק עד" in body["snapshot"]["partial_banner"]["text_he"]
    assert body["provider_calls"] == 0
