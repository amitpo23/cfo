"""Regression: overdue-invoice total must exclude non-final invoices (draft/void/cancelled).

Bug: FinancialControlService._overdue_invoice_total summed Invoice.balance with no
status filter, so a DRAFT (or VOID/CANCELLED) invoice with balance>0 and a past
due_date inflated `overdue_invoices_amount`. Only invoices that vat_utils.invoice_counts
would count (i.e. not draft/void/cancelled) should be included.
"""
from datetime import date, timedelta

from cfo.database import SessionLocal
from cfo.models import Contact, ContactType, Invoice, InvoiceStatus
from cfo.services.financial_control_service import FinancialControlService


def _make_invoice(db, org_id, contact_id, status, balance, days_overdue):
    inv = Invoice(
        organization_id=org_id,
        contact_id=contact_id,
        invoice_number=f"TEST-{status.value}-{days_overdue}",
        issue_date=date.today() - timedelta(days=days_overdue + 10),
        due_date=date.today() - timedelta(days=days_overdue),
        status=status,
        subtotal=balance,
        tax=0.0,
        total=balance,
        balance=balance,
    )
    db.add(inv)
    return inv


def test_draft_invoice_not_counted_as_overdue(fresh_org):
    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        customer = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="Cust")
        db.add(customer)
        db.flush()

        # DRAFT invoice, overdue, positive balance — must NOT be counted (it's the bug).
        _make_invoice(db, org_id, customer.id, InvoiceStatus.DRAFT, 1000.0, 40)
        # VOID / CANCELLED — also must not be counted.
        _make_invoice(db, org_id, customer.id, InvoiceStatus.VOID, 500.0, 40)
        _make_invoice(db, org_id, customer.id, InvoiceStatus.CANCELLED, 500.0, 40)
        # A genuinely overdue, finalized invoice — must be counted.
        _make_invoice(db, org_id, customer.id, InvoiceStatus.OVERDUE, 750.0, 40)
        db.commit()

        svc = FinancialControlService(db, organization_id=org_id)
        total = svc._overdue_invoice_total(date.today())

        assert float(total) == 750.0
    finally:
        db.close()
