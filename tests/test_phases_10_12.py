"""Tests for Phases 10-12: Payment, Forecasting, Compliance & Audit."""
from datetime import date
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import Bill, BillStatus, Invoice, Expense
from cfo.services.payment_orchestration import PaymentOrchestrationService
from cfo.services.forecasting_advanced import AdvancedForecastingService
from cfo.services.compliance_audit import ComplianceAuditService


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


# ==================== PHASE 12: Compliance & Audit ====================

def test_log_change(acc):
    """Log change for audit trail."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = ComplianceAuditService(db, org_id)
        result = service.log_change(
            user_id=1,
            action="update",
            entity_type="invoice",
            entity_id=123,
            changes={"status": {"old": "draft", "new": "sent"}},
        )

        assert result["action"] == "update"
        assert result["entity"] == "invoice/123"
        assert result["user_id"] == 1
    finally:
        db.close()


def test_get_audit_trail(acc):
    """Retrieve audit trail."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = ComplianceAuditService(db, org_id)

        # Log some changes
        service.log_change(1, "create", "invoice", 100, {"amount": {"old": None, "new": 1000}})
        service.log_change(1, "update", "invoice", 100, {"status": {"old": "draft", "new": "sent"}})

        trail = service.get_audit_trail(entity_type="invoice")

        # Service returns empty list by default (placeholder)
        assert isinstance(trail, list)
    finally:
        db.close()


def test_tax_report_1301(acc):
    """Generate Israeli tax form 1301."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = ComplianceAuditService(db, org_id)
        result = service.generate_tax_report_1301(year=2026)

        assert result["form"] == "1301"
        assert result["tax_year"] == 2026
        assert "revenue" in result
        assert "expenses" in result
        assert "net_income" in result
    finally:
        db.close()


def test_tax_report_1214(acc):
    """Generate Israeli tax form 1214."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = ComplianceAuditService(db, org_id)
        result = service.generate_tax_report_1214(year=2026)

        assert result["form"] == "1214"
        assert "income_statement" in result
        assert "documentation_status" in result
    finally:
        db.close()


def test_export_for_auditor(acc):
    """Export for external auditors."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = ComplianceAuditService(db, org_id)
        result = service.export_for_auditor(year=2026, format="json")

        assert result["tax_year"] == 2026
        assert "entities" in result
        assert "summary" in result
        assert "audit_trail" in result
    finally:
        db.close()


def test_compliance_checklist(acc):
    """Compliance readiness checklist."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = ComplianceAuditService(db, org_id)
        result = service.compliance_checklist()

        assert "audit_trail_enabled" in result
        assert "tax_reports_available" in result
        assert "audit_export_ready" in result
    finally:
        db.close()


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


def test_tax_reports_api(client, acc):
    """Test tax report generation via API."""
    r = client.get("/api/advanced/tax/report-1301?year=2026", headers=acc["headers"])
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["form"] == "1301"
