"""Tests for Phases 10-12: Payment, Forecasting, Compliance & Audit."""
from datetime import date
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import Bill, BillStatus, Invoice, Expense
from cfo.services.payment_orchestration import PaymentOrchestrationService
from cfo.services.forecasting_advanced import AdvancedForecastingService


@pytest.fixture(scope="module")
def acc(client):
    reg = client.post("/api/admin/auth/register", json={
        "email": "phase1012@example.com", "password": "secret123", "full_name": "Phase 10-12",
    })
    assert reg.status_code == 201, reg.text
    return {"headers": {"Authorization": f"Bearer {reg.json()['access_token']}"},
            "org_id": reg.json()["user"]["organization_id"]}


# ==================== PHASE 10: Payment Orchestration ====================

def test_suggest_payments(acc):
    """Suggest optimal payments."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = PaymentOrchestrationService(db, org_id)
        result = service.suggest_payments(urgency="normal")

        assert "suggested" in result
        assert "total_amount" in result
        assert isinstance(result["suggested"], list)
    finally:
        db.close()


def test_execute_payment(acc):
    """Execute a payment."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = PaymentOrchestrationService(db, org_id)
        result = service.execute_payment(
            1,
            "bank_transfer",
            Decimal("5000"),
        )

        assert result["status"] == "pending_execution"
        assert result["amount"] == 5000.0
        assert result["method"] == "bank_transfer"
    finally:
        db.close()


def test_payment_status(acc):
    """Get payment status."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = PaymentOrchestrationService(db, org_id)
        status = service.get_payment_status(1)

        assert status["bill_id"] == 1
        assert "original_amount" in status
        assert "remaining_balance" in status
    finally:
        db.close()


# ==================== PHASE 11: Forecasting ====================

def test_forecast_cash_flow(acc):
    """Forecast cash flow."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = AdvancedForecastingService(db, org_id)
        result = service.forecast_cash_flow(days_ahead=30, starting_balance=Decimal("10000"))

        assert result["starting_balance"] == 10000.0
        assert "forecast" in result
        assert len(result["forecast"]) >= 1
        assert "critical_dates" in result
    finally:
        db.close()


def test_budget_vs_actual(acc):
    """Budget vs actual analysis."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = AdvancedForecastingService(db, org_id)
        result = service.budget_vs_actual(period="monthly", year=2026)

        assert result["period"] == "monthly"
        assert result["year"] == 2026
        assert "total_budget" in result
        assert "total_actual" in result
        assert "by_category" in result
    finally:
        db.close()


def test_scenario_analysis(acc):
    """What-if scenario analysis."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = AdvancedForecastingService(db, org_id)
        scenarios = [
            {
                "name": "Conservative",
                "assumptions": {"revenue_increase": 0, "expense_cut": 0.1},
            },
            {
                "name": "Aggressive",
                "assumptions": {"revenue_increase": 0.2, "expense_cut": 0},
            },
        ]
        result = service.scenario_analysis(scenarios)

        assert len(result["scenarios"]) == 2
        assert "recommendation" in result
    finally:
        db.close()


# Phase 12 (Compliance & Audit / ComplianceAuditService) was removed
# 2026-07-04 — see phase10_12.py for why (fabricated data, zero real
# consumers, real twins already exist for the tax reports).

# ==================== API Endpoints ====================

def test_suggest_payments_api(client, acc):
    """Test payment suggestions via API."""
    r = client.post("/api/advanced/payments/suggest", json={
        "urgency": "normal",
    }, headers=acc["headers"])

    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "suggested" in data


def test_forecast_api(client, acc):
    """Test forecasting via API."""
    r = client.get("/api/advanced/forecast/cash-flow?days_ahead=30", headers=acc["headers"])
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "forecast" in data


def test_tax_report_1301_lives_at_annual_reports_not_advanced(client, acc):
    """The real 1301 form is served by annual_reports.py; the old fabricated
    /api/advanced/tax/report-1301 duplicate was removed."""
    r = client.get("/api/advanced/tax/report-1301?year=2026", headers=acc["headers"])
    assert r.status_code == 404

    r2 = client.get("/api/annual-reports/1301?year=2026", headers=acc["headers"])
    assert r2.status_code == 200, r2.text
    assert r2.json()["form"] == "1301"
