"""Tests for daily-cumulative reports + aging."""
from datetime import date

from cfo.database import SessionLocal
from cfo.models import Invoice, Bill, InvoiceStatus, BillStatus
from cfo.services import daily_reports_service


def _seed(org_id):
    db = SessionLocal()
    try:
        for model in (Bill, Invoice):
            db.query(model).filter(model.organization_id == org_id,
                                   model.source == "dr-test").delete()
        db.commit()
        # Two invoices in June 2026, one overdue (due in the past).
        db.add(Invoice(organization_id=org_id, external_id="DR-INV-1", source="dr-test",
                       invoice_number="1", issue_date=date(2026, 6, 5),
                       due_date=date(2026, 6, 5), status=InvoiceStatus.OVERDUE,
                       subtotal=1000, tax=180, total=1180, balance=1180))
        db.add(Invoice(organization_id=org_id, external_id="DR-INV-2", source="dr-test",
                       invoice_number="2", issue_date=date(2026, 6, 20),
                       due_date=date(2026, 7, 20), status=InvoiceStatus.SENT,
                       subtotal=2000, tax=360, total=2360, balance=2360))
        db.add(Bill(organization_id=org_id, external_id="DR-BILL-1", source="dr-test",
                    bill_number="B1", issue_date=date(2026, 6, 10),
                    due_date=date(2026, 6, 10), status=BillStatus.RECEIVED,
                    subtotal=500, tax=90, total=590, balance=590))
        db.commit()
    finally:
        db.close()


def test_cumulative_pl_accumulates(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        rep = daily_reports_service.cumulative_pl(db, org_id, 2026, 6)
        assert len(rep["days"]) == 30
        # Revenue accrues on day 5 (1000) then day 20 (+2000) = 3000 by month end.
        assert rep["totals"]["revenue"] == 3000.0
        assert rep["totals"]["expense"] == 500.0
        assert rep["totals"]["profit"] == 2500.0
        # Monotonic non-decreasing cumulative revenue.
        rev = [d["revenue_cum"] for d in rep["days"]]
        assert rev == sorted(rev)
        assert rep["days"][4]["revenue_cum"] == 1000.0   # day 5 (index 4)
    finally:
        db.close()


def test_ar_aging_buckets(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        aging = daily_reports_service.ar_aging(db, org_id, as_of=date(2026, 6, 30))
        # INV-1 due 6/5 -> 25 days overdue (1_30); INV-2 due 7/20 -> current.
        assert aging["buckets"]["1_30"] == 1180.0
        assert aging["buckets"]["current"] == 2360.0
        assert aging["total"] == 3540.0
    finally:
        db.close()


def test_daily_reports_routes_require_auth(client):
    for path in ["/api/daily-reports/cumulative-pl?year=2026&month=6",
                 "/api/daily-reports/ar-aging", "/api/daily-reports/ap-aging",
                 "/api/daily-reports/suppliers?year=2026&month=6"]:
        assert client.get(path).status_code == 403, path


def test_vat_report_period(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        rep = daily_reports_service.vat_report(db, org_id, 2026, 6)
        # Two sales invoices in June (subtotal 1000+2000), one bill (subtotal 500).
        assert rep["output_vat"] == 540.0    # 18% of 3000
        assert rep["input_vat"] == 90.0      # 18% of 500
        assert rep["net_vat"] == 450.0
        assert rep["direction"] == "לתשלום"
        assert rep["amount_to_report"] == 450.0
        assert rep["sales_documents"] == 2
        assert rep["due_date"] == "2026-07-15"
    finally:
        db.close()
