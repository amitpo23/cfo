"""סימני מע"מ אחרי נרמול הסימנים (12-13/07/2026): מסמך הוצאה רגיל שמור
חיובי; **שלילי = זיכוי ספק** שמקטין תשומות (לא abs() — קיזוז ביתר אסור בחוק).
מקור אמת אחד: tax_service.generate_vat_report נגזר מאותו select_vat_documents
כמו compute_vat_position/pcn874, כולל דה-דופ והחרגת קבלות.
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
        # מסמך הוצאה רגיל — מנורמל חיובי (tax=+72)
        db.add(Bill(organization_id=org_id, vendor_id=vend.id, bill_number="B1",
                    issue_date=date(2026, 5, 3), due_date=date(2026, 6, 3),
                    subtotal=400, tax=72, total=472, paid_amount=472, balance=0,
                    status=BillStatus.PAID))
        # זיכוי ספק — שלילי, מקטין תשומות
        db.add(Bill(organization_id=org_id, vendor_id=vend.id, bill_number="B1-CR",
                    issue_date=date(2026, 5, 8), due_date=None,
                    subtotal=-100, tax=-18, total=-118, paid_amount=-118, balance=0,
                    status=BillStatus.PAID))
        db.commit()
        return {"org_id": org_id}
    finally:
        db.close()


def test_supplier_credit_reduces_input_vat_signed(org_with_negative_bill):
    """72 (מסמך רגיל) − 18 (זיכוי ספק) = 54. זיכוי לעולם לא מגדיל תשומות."""
    from cfo.database import SessionLocal
    from cfo.services.financial_synthesis import compute_vat_position

    db = SessionLocal()
    try:
        pos = compute_vat_position(db, org_with_negative_bill["org_id"],
                                   start=date(2026, 5, 1), end=date(2026, 5, 31))
        assert pos["output_vat"] == 180.0
        assert pos["input_vat"] == 54.0      # 72 − 18, לא 90
        assert pos["net_vat"] == 126.0       # 180 − 54
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


@pytest.fixture
def org_with_bill_expense_twin(fresh_org):
    """אותו מסמך SUMIT מסונכרן גם כ-Bill וגם כ-Expense (external_id משותף)."""
    from cfo.database import SessionLocal
    from cfo.models import Contact, ContactType, Bill, BillStatus, Expense

    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        vend = Contact(organization_id=org_id, contact_type=ContactType.VENDOR, name="ספק")
        db.add(vend); db.flush()
        # מסמך SUMIT-1: קיים גם כ-Bill וגם כ-Expense — חייב להיספר פעם אחת (Bill קנוני)
        db.add(Bill(organization_id=org_id, vendor_id=vend.id, bill_number="B-1",
                    external_id="SUMIT-1", issue_date=date(2026, 5, 3),
                    subtotal=100, tax=18, total=118, paid_amount=0, balance=118,
                    status=BillStatus.APPROVED))
        db.add(Expense(organization_id=org_id, external_id="SUMIT-1",
                       supplier_name="ספק", amount=100, vat_amount=18, total=118,
                       expense_date=date(2026, 5, 3), status="filed"))
        # מסמך שקיים רק כ-Expense — נספר
        db.add(Expense(organization_id=org_id, external_id="SUMIT-2",
                       supplier_name="ספק", amount=50, vat_amount=9, total=59,
                       expense_date=date(2026, 5, 4), status="filed"))
        # מסמך שקיים רק כ-Bill (בלי external_id) — נספר
        db.add(Bill(organization_id=org_id, vendor_id=vend.id, bill_number="B-2",
                    issue_date=date(2026, 5, 5),
                    subtotal=150, tax=27, total=177, paid_amount=0, balance=177,
                    status=BillStatus.APPROVED))
        db.commit()
        return {"org_id": org_id}
    finally:
        db.close()


def test_input_vat_counts_each_document_once(org_with_bill_expense_twin):
    """מסמך המסונכרן גם כ-Bill וגם כ-Expense נספר פעם אחת — לא כפל תשומות."""
    from cfo.database import SessionLocal
    from cfo.services.financial_synthesis import compute_vat_position

    db = SessionLocal()
    try:
        pos = compute_vat_position(db, org_with_bill_expense_twin["org_id"],
                                   start=date(2026, 5, 1), end=date(2026, 5, 31))
        # 18 (התאום, פעם אחת) + 9 (Expense בלבד) + 27 (Bill בלבד) = 54, לא 72
        assert pos["input_vat"] == 54.0
    finally:
        db.close()
