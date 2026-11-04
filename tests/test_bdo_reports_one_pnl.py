"""The bank report and the executive dashboard show the /pnl figures.

Both read /cashflow/period books for the same range. The net margin is a
percent (48.7, not 4870). Nothing known is 0: an empty org is חסר. Gross and
operating profit are not separable in the books, so they stay null. Made-up
documents only.
"""
from datetime import date
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Bill, BillStatus, Invoice, InvoiceStatus

RANGE = {"start_date": "2026-10-01", "end_date": "2026-10-31"}


def _seed(org_id: int) -> None:
    db = SessionLocal()
    db.add(Invoice(
        organization_id=org_id, invoice_number="R-IN-1", status=InvoiceStatus.SENT,
        issue_date=date(2026, 10, 5), subtotal=Decimal("1000"), tax=Decimal("180"),
        total=Decimal("1180"), balance=Decimal("1180"),
    ))
    db.add(Bill(
        organization_id=org_id, bill_number="R-B-1", status=BillStatus.RECEIVED,
        issue_date=date(2026, 10, 7), subtotal=Decimal("513"), tax=Decimal("92.34"),
        total=Decimal("605.34"), balance=Decimal("605.34"),
    ))
    db.commit()
    db.close()


def _period_books(client, headers):
    r = client.get("/api/cashflow/period", headers=headers, params={
        "grain": "month", "start": RANGE["start_date"], "end": RANGE["end_date"],
    })
    assert r.status_code == 200, r.text
    return r.json()["totals"]["books"]


def test_bank_report_and_executive_match_pnl(client, fresh_org):
    owner = fresh_org()
    _seed(owner["org_id"])
    headers = owner["headers"]
    books = _period_books(client, headers)
    assert books["net"]["amount"] == 487

    bank = client.get("/api/reports/bank-status", headers=headers, params=RANGE)
    assert bank.status_code == 200, bank.text
    executive = client.get("/api/dashboard/executive", headers=headers, params=RANGE)
    assert executive.status_code == 200, executive.text
    panel = executive.json()["data"]["panels"]["profit_loss"]
    assert panel["ok"], panel

    for pl in (bank.json()["data"]["profit_loss"], panel["data"]):
        assert pl["total_revenue"] == books["revenue"]["amount"] == 1000
        assert pl["total_expenses"] == books["costs"]["amount"] == 513
        assert pl["net_income"] == books["net"]["amount"]
        assert pl["net_margin"] == 48.7
        assert pl["gross_profit"] is None and pl["operating_income"] is None
        assert pl["source"] == "cashflow.period"


def test_empty_org_reports_are_missing_not_zero(client, fresh_org):
    headers = fresh_org()["headers"]
    bank = client.get("/api/reports/bank-status", headers=headers, params=RANGE).json()["data"]
    panel = client.get("/api/dashboard/executive", headers=headers, params=RANGE).json()["data"]["panels"]
    for pl in (bank["profit_loss"], panel["profit_loss"]["data"]):
        assert pl["total_revenue"] is None
        assert pl["net_income"] is None
        assert pl["net_margin"] is None
        assert pl["missing_label_he"]


def test_bank_report_excel_writes_the_margin_as_a_fraction(client, fresh_org):
    from io import BytesIO

    import openpyxl

    owner = fresh_org()
    _seed(owner["org_id"])
    r = client.get("/api/reports/bank-status/export", headers=owner["headers"], params=RANGE)
    assert r.status_code == 200, r.text
    ws = openpyxl.load_workbook(BytesIO(r.content)).active
    margin = [row[1] for row in ws.iter_rows(values_only=True) if row[0] == "שולי רווח נקי"]
    assert margin == [0.487]


def test_budget_variance_with_no_actual_is_missing_not_100_percent():
    from cfo.services.budget_service import BudgetCategory, BudgetStatus, BudgetSummary
    from cfo.services.executive_dashboard_service import budget_panel

    def cat(name, budget, actual):
        variance = budget - actual
        return BudgetCategory(
            category_id=name, category_name=name, category_hebrew=name, budget_amount=budget,
            actual_amount=actual, variance=variance, variance_percentage=variance / budget * 100,
            status=BudgetStatus.ON_TRACK, forecast_end_of_period=actual,
        )

    def summary(categories):
        budget = sum(c.budget_amount for c in categories)
        actual = sum(c.actual_amount for c in categories)
        return BudgetSummary(
            period="2026-11", period_start="2026-11-01", period_end="2026-12-01",
            total_budget=budget, total_actual=actual, total_variance=budget - actual,
            variance_percentage=(budget - actual) / budget * 100, status=BudgetStatus.ON_TRACK,
            categories=categories, alerts=[],
        )

    empty = budget_panel(summary([cat("rent", 5000.0, 0.0)]))
    assert empty["total_budget"] == 5000.0
    assert empty["total_actual"] is None and empty["variance_percentage"] is None
    assert empty["missing_label_he"]
    assert empty["categories"][0]["variance_percentage"] is None

    partial = budget_panel(summary([cat("rent", 5000.0, 4000.0), cat("ads", 1000.0, 0.0)]))
    assert partial["total_actual"] == 4000.0
    assert partial["variance_percentage"] == 1 / 3 * 100
    assert partial["categories"][0]["variance_percentage"] == 20.0
    assert partial["categories"][1]["variance_percentage"] is None


def test_executive_computes_insights_once_and_times_each_panel(client, fresh_org, monkeypatch):
    from cfo.services import ai_analytics_service

    calls = []
    original = ai_analytics_service.AdvancedAIService.generate_insights

    def counted(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ai_analytics_service.AdvancedAIService, "generate_insights", counted)
    owner = fresh_org()
    _seed(owner["org_id"])
    r = client.get("/api/dashboard/executive", headers=owner["headers"], params=RANGE)
    assert r.status_code == 200, r.text
    panels = r.json()["data"]["panels"]
    assert len(calls) == 1
    assert all(isinstance(panel["elapsed_ms"], int) for panel in panels.values())
    timings = sorted(((p["elapsed_ms"], name) for name, p in panels.items()), reverse=True)
    print("PANEL_MS", timings)
