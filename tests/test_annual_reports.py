"""Tests for annual report DRAFTS (1301/1214) — derived from the ledger."""
from datetime import date

from cfo.database import SessionLocal
from cfo.models import Invoice, Bill, InvoiceStatus, BillStatus
from cfo.services import annual_report_service


def _seed(org_id):
    db = SessionLocal()
    try:
        for model in (Bill, Invoice):
            db.query(model).filter(model.organization_id == org_id,
                                   model.source == "ar-test").delete()
        db.commit()
        # Revenue 100000 (subtotal), expenses 40000 -> net profit 60000.
        db.add(Invoice(organization_id=org_id, external_id="AR-INV-1", source="ar-test",
                       invoice_number="1", issue_date=date(2025, 3, 1),
                       status=InvoiceStatus.PAID, subtotal=100000, tax=18000, total=118000))
        db.add(Bill(organization_id=org_id, external_id="AR-BILL-1", source="ar-test",
                    bill_number="B1", issue_date=date(2025, 4, 1),
                    status=BillStatus.PAID, subtotal=40000, tax=7200, total=47200))
        db.commit()
    finally:
        db.close()


def test_form_1214_company_tax(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        rep = annual_report_service.form_1214(db, org_id, 2025)
        assert rep["draft"] is True
        f = rep["fields"]
        assert f["revenue"] == 100000.0
        assert f["expenses"] == 40000.0
        assert f["net_profit_before_tax"] == 60000.0
        assert f["corporate_tax_due"] == round(60000 * 0.23, 2)  # 13800
    finally:
        db.close()


def test_form_1301_individual_progressive(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        rep = annual_report_service.form_1301(db, org_id, 2025, credit_points=2.25)
        assert rep["draft"] is True
        f = rep["fields"]
        assert f["business_income"] == 60000.0
        # Progressive on 60000: first 84120 @10% -> 6000 gross.
        assert f["gross_income_tax"] == 6000.0
        # Credit 2.25 * 2904 = 6534 > gross -> net tax 0.
        assert f["income_tax_due"] == 0.0
    finally:
        db.close()


def test_annual_report_routes_require_auth(client):
    for path in ["/api/annual-reports/1301?year=2025", "/api/annual-reports/1214?year=2025"]:
        assert client.get(path).status_code == 403, path
