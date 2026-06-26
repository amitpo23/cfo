"""End-to-end tests for the payroll module: employees → payslips → 102/126."""
import pytest


@pytest.fixture
def emp(client, owner):
    r = client.post("/api/payroll/employees", headers=owner["headers"], json={
        "name": "דנה כהן", "tax_id": "123456782", "gross_salary": 12000,
        "credit_points": 2.25, "pension_pct": 6.0,
    })
    assert r.status_code == 200, r.text
    return r.json()


def test_payroll_requires_auth(client):
    assert client.get("/api/payroll/employees").status_code == 403


def test_create_and_list_employee(client, owner, emp):
    assert emp["gross_salary"] == 12000
    listing = client.get("/api/payroll/employees", headers=owner["headers"]).json()["employees"]
    assert any(e["id"] == emp["id"] for e in listing)


def test_run_payroll_computes_correct_payslip(client, owner, emp):
    run = client.post("/api/payroll/run?year=2026&month=6", headers=owner["headers"])
    assert run.status_code == 200, run.text
    assert run.json()["employees"] >= 1

    payslips = client.get("/api/payroll/payslips?year=2026&month=6", headers=owner["headers"]).json()["payslips"]
    mine = next(p for p in payslips if p["employee_id"] == emp["id"])
    # Validated against calculators.payslip_components(12000).
    assert mine["net"] == 9694.29
    assert mine["income_tax"] == 733.85
    assert round(mine["ni_employee"] + mine["health_tax"], 2) == 851.86
    assert mine["employer_cost"] == 14173.98


def test_run_payroll_is_idempotent(client, owner, emp):
    client.post("/api/payroll/run?year=2026&month=7", headers=owner["headers"])
    second = client.post("/api/payroll/run?year=2026&month=7", headers=owner["headers"]).json()
    assert second["updated"] >= 1  # refreshed, not duplicated
    payslips = client.get("/api/payroll/payslips?year=2026&month=7", headers=owner["headers"]).json()["payslips"]
    assert len([p for p in payslips if p["employee_id"] == emp["id"]]) == 1


def test_form_102_aggregates_withholding(client, owner, emp):
    client.post("/api/payroll/run?year=2026&month=8", headers=owner["headers"])
    r = client.get("/api/payroll/reports/102?year=2026&month=8", headers=owner["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["report_type"] == "102"
    assert body["employees"] >= 1
    # 102 aggregates every active employee for the month; each contributes 733.85.
    assert body["income_tax"] == round(733.85 * body["employees"], 2)
    assert body["due_date"] == "2026-09-15"


def test_form_126_annual(client, owner, emp):
    client.post("/api/payroll/run?year=2026&month=9", headers=owner["headers"])
    r = client.get("/api/payroll/reports/126?year=2026", headers=owner["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["report_type"] == "126"
    assert body["employee_count"] >= 1
    rec = next(e for e in body["employees"] if e["employee_id"] == emp["id"])
    assert rec["months"] >= 1
    assert rec["gross"] >= 12000


def test_tax_service_102_reads_payroll_data(client, owner, emp):
    """The withholding (102) report in tax_service now sources real payroll data."""
    from cfo.services.tax_service import TaxComplianceService
    from cfo.database import SessionLocal

    org_id = owner["user"]["organization_id"]
    client.post("/api/payroll/run?year=2026&month=10", headers=owner["headers"])
    db = SessionLocal()
    try:
        rows = TaxComplianceService(db, org_id)._get_employee_data(2026, 10)
    finally:
        db.close()
    assert len(rows) >= 1
    assert rows[0]["income_tax"] == 733.85
    assert "social_security_employer" in rows[0]
