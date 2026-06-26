"""פאזה 1 (השלמה) — מסמכים שאינם סופיים (חשבונית מבוטלת/טיוטה, הוצאת pending)
לא נספרים כהכנסה/הוצאה/מע"מ. אחרת מסמך מבוטל מנפח דוחות ודיווח מע"מ.
"""
from datetime import date

import pytest

from cfo.services.financial_reports_service import FinancialReportsService
from cfo.services.tax_service import TaxComplianceService
from cfo.services.financial_synthesis import compute_vat_position


@pytest.fixture
def org_mixed_status(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import (
        Contact, ContactType, Invoice, InvoiceStatus, Expense,
    )

    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        cust = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="לקוח")
        db.add(cust); db.flush()
        db.add_all([
            Invoice(organization_id=org_id, contact_id=cust.id, invoice_number="OK",
                    issue_date=date(2026, 3, 5), due_date=date(2026, 3, 5),
                    subtotal=1000, tax=180, total=1180, status=InvoiceStatus.SENT),
            Invoice(organization_id=org_id, contact_id=cust.id, invoice_number="CANCELLED",
                    issue_date=date(2026, 3, 6), due_date=date(2026, 3, 6),
                    subtotal=9999, tax=1800, total=11799, status=InvoiceStatus.CANCELLED),
            Expense(organization_id=org_id, supplier_name="ספק filed",
                    amount=200, vat_amount=36, total=236,
                    expense_date=date(2026, 3, 7), status="filed"),
            Expense(organization_id=org_id, supplier_name="ספק pending (טיוטה)",
                    amount=500, vat_amount=90, total=590,
                    expense_date=date(2026, 3, 8), status="pending"),
        ])
        db.commit()
        return {"org_id": org_id}
    finally:
        db.close()


def test_pl_excludes_cancelled_and_pending(org_mixed_status):
    from cfo.database import SessionLocal
    db = SessionLocal()
    try:
        rep = FinancialReportsService(db).generate_profit_loss(
            org_mixed_status["org_id"], date(2026, 3, 1), date(2026, 3, 31), compare_previous=False)
        assert rep.total_revenue == 1000.0       # חשבונית מבוטלת לא נספרת
        assert rep.total_expenses == 200.0        # הוצאת pending לא נספרת
    finally:
        db.close()


def test_vat_excludes_cancelled_and_pending(org_mixed_status):
    from cfo.database import SessionLocal
    db = SessionLocal()
    try:
        org_id = org_mixed_status["org_id"]
        rep = TaxComplianceService(db, organization_id=org_id).generate_vat_report(2026, 3)
        assert rep.output_vat == 180.0            # לא 1980
        assert rep.total_input_vat == 36.0        # לא 126
        cvp = compute_vat_position(db, org_id, start=date(2026, 3, 1), end=date(2026, 3, 31))
        assert cvp["output_vat"] == 180.0
        assert cvp["input_vat"] == 36.0
    finally:
        db.close()
