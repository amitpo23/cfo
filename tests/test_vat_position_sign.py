"""compute_vat_position חייב להחזיר מע"מ תשומות חיובי גם כש-bills/expenses
שמורים בסימן שלילי (מוסכמת 'כסף יוצא'). מקור אמת אחד עם tax_service.generate_vat_report.
"""
from datetime import date

import pytest


@pytest.fixture
def org_with_negative_bill(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Contact, ContactType, Invoice, InvoiceStatus, Bill, BillStatus

    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        cust = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="לקוח")
        vend = Contact(organization_id=org_id, contact_type=ContactType.VENDOR, name="ספק")
        db.add_all([cust, vend]); db.flush()
        db.add(Invoice(organization_id=org_id, contact_id=cust.id, invoice_number="I1",
                       issue_date=date(2026, 5, 5), due_date=date(2026, 6, 5),
                       subtotal=1000, tax=180, total=1180, paid_amount=0, balance=1180,
                       status=InvoiceStatus.SENT))
        # ספק שמור שלילי (כסף יוצא) — tax=-72
        db.add(Bill(organization_id=org_id, vendor_id=vend.id, bill_number="B1",
                    issue_date=date(2026, 5, 3), due_date=date(2026, 6, 3),
                    subtotal=-400, tax=-72, total=-472, paid_amount=0, balance=-472,
                    status=BillStatus.APPROVED))
        db.commit()
        return {"org_id": org_id}
    finally:
        db.close()


def test_input_vat_is_positive_for_negative_bill(org_with_negative_bill):
    from cfo.database import SessionLocal
    from cfo.services.financial_synthesis import compute_vat_position

    db = SessionLocal()
    try:
        pos = compute_vat_position(db, org_with_negative_bill["org_id"],
                                   start=date(2026, 5, 1), end=date(2026, 5, 31))
        assert pos["output_vat"] == 180.0
        assert pos["input_vat"] == 72.0      # חיובי, לא -72
        assert pos["net_vat"] == 108.0       # 180 - 72
    finally:
        db.close()


def test_two_vat_engines_agree_single_source_of_truth(org_with_negative_bill):
    """tax_service.generate_vat_report ו-compute_vat_position מסכימים — מקור אמת אחד."""
    from cfo.database import SessionLocal
    from cfo.services.tax_service import TaxComplianceService
    from cfo.services.financial_synthesis import compute_vat_position

    db = SessionLocal()
    try:
        org_id = org_with_negative_bill["org_id"]
        rep = TaxComplianceService(db, organization_id=org_id).generate_vat_report(2026, 5)
        cvp = compute_vat_position(db, org_id, start=date(2026, 5, 1), end=date(2026, 5, 31))
        assert round(rep.output_vat, 2) == round(cvp["output_vat"], 2)
        assert round(rep.total_input_vat, 2) == round(cvp["input_vat"], 2)
        assert round(rep.net_vat, 2) == round(cvp["net_vat"], 2)
    finally:
        db.close()
