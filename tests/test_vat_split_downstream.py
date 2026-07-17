"""M9 — downstream proof that the VAT split fix actually reaches compute_vat_position.

The connector-level fix (sumit_connector._derive_subtotal_tax,
sumit_integration._document_response_from_list, vat_utils.split_inclusive) already
derives subtotal/tax for freshly-synced documents. These tests prove the *downstream*
side of the contract for SUMIT-style synced rows carrying raw_data:

1. A synced invoice/bill/expense whose raw_data mirrors what the connector actually
   stores (no explicit VAT field -> split_inclusive derived it) produces non-zero
   output/input VAT in compute_vat_position — not the pre-fix VAT=0 regression.
2. A document whose raw_data carries an *explicit* zero VAT (genuinely VAT-exempt,
   per the connector's own precedence rule — explicit wins over derivation) still
   contributes exactly 0 VAT — the fix must not fabricate VAT for exempt documents.
"""
from datetime import date
from decimal import Decimal

import pytest


def _synced_invoice_raw(total: Decimal, doc_date: date, explicit_vat=None) -> dict:
    """Mirror DocumentResponse.__dict__ as stored by sumit_connector.fetch_invoices."""
    return {
        "document_id": "9001", "document_number": "100", "document_type": "0",
        "customer_id": "5", "total_amount": float(total),
        "vat_amount": float(explicit_vat) if explicit_vat is not None else 0.0,
        "status": "open", "issue_date": doc_date.isoformat(), "due_date": None,
        "pdf_url": None, "id": "9001", "total": float(total), "date": doc_date.isoformat(),
        "customer_name": "לקוח", "currency": "ILS", "allocation_number": None,
    }


@pytest.fixture
def org_with_synced_docs(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import (
        Contact, ContactType, Invoice, InvoiceStatus, Bill, BillStatus, Expense,
    )
    from cfo.services.sumit_connector import _derive_subtotal_tax
    from cfo.integrations.sumit_integration import SumitIntegration

    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        cust = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="לקוח")
        vend = Contact(organization_id=org_id, contact_type=ContactType.VENDOR, name="ספק")
        db.add_all([cust, vend]); db.flush()

        intg = SumitIntegration(api_key="k", company_id="1")

        # --- 1. Taxable invoice synced with NO explicit VAT field (the historical
        # SUMIT list-endpoint shape that used to zero VAT) — must derive via
        # split_inclusive at the connector layer, exactly like fetch_invoices does.
        gross_doc = {"DocumentID": 1, "DocumentNumber": "100", "Type": 0,
                     "DocumentValue": 23600, "Date": "2026-05-10", "CustomerID": 5}
        doc = intg._document_response_from_list(gross_doc)
        subtotal, tax = _derive_subtotal_tax(doc, Decimal(str(doc.total)))
        db.add(Invoice(
            organization_id=org_id, contact_id=cust.id, invoice_number="100",
            issue_date=date(2026, 5, 10), due_date=date(2026, 6, 10),
            subtotal=subtotal, tax=tax, total=doc.total, paid_amount=0,
            balance=doc.total, status=InvoiceStatus.SENT, source="sumit",
            raw_data=doc.__dict__,
        ))

        # --- 2. Taxable bill, same shape.
        bill_doc = intg._document_response_from_list(
            {"DocumentID": 2, "DocumentNumber": "B1", "Type": 15,
             "DocumentValue": 11800, "Date": "2026-05-08", "CustomerID": 6}
        )
        bsubtotal, btax = _derive_subtotal_tax(bill_doc, Decimal(str(bill_doc.total)))
        db.add(Bill(
            organization_id=org_id, vendor_id=vend.id, bill_number="B1",
            issue_date=date(2026, 5, 8), due_date=date(2026, 6, 8),
            subtotal=bsubtotal, tax=btax, total=bill_doc.total,
            paid_amount=bill_doc.total, balance=0, status=BillStatus.PAID,
            source="sumit", raw_data=bill_doc.__dict__,
        ))

        # --- 3. Genuinely VAT-exempt bill: raw_data carries an EXPLICIT vat_amount
        # of 0 (the connector's precedence rule: explicit wins over derivation, even
        # when explicit is zero) — this must NOT be over-split into fabricated VAT.
        exempt_raw = _synced_invoice_raw(Decimal("5000"), date(2026, 5, 12), explicit_vat=Decimal("0"))
        from cfo.services.sumit_connector import _derive_subtotal_tax as _dst

        class _FakeDoc:
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)

        exempt_doc = _FakeDoc(date=date(2026, 5, 12), vat_amount=Decimal("0"))
        exempt_subtotal, exempt_tax = _dst(exempt_doc, Decimal("5000"))
        db.add(Bill(
            organization_id=org_id, vendor_id=vend.id, bill_number="B-EXEMPT",
            issue_date=date(2026, 5, 12), due_date=date(2026, 6, 12),
            subtotal=exempt_subtotal, tax=exempt_tax, total=Decimal("5000"),
            paid_amount=Decimal("5000"), balance=0, status=BillStatus.PAID,
            source="sumit", raw_data=exempt_raw,
        ))

        # --- 4. Filed expense synced with no explicit VAT (must count — status=filed).
        exp_doc = intg._document_response_from_list(
            {"DocumentID": 3, "DocumentNumber": "E1", "Type": 15,
             "DocumentValue": 2360, "Date": "2026-05-15", "CustomerID": 7}
        )
        db.add(Expense(
            organization_id=org_id, external_id="3", source="sumit",
            supplier_name="ספק הוצאה", amount=Decimal(str(exp_doc.total)) - exp_doc.vat_amount,
            vat_amount=exp_doc.vat_amount, total=exp_doc.total,
            expense_date=date(2026, 5, 15), status="filed",
            raw_data=exp_doc.__dict__,
        ))

        db.commit()
        return {
            "org_id": org_id,
            "expected_invoice_tax": float(tax),
            "expected_bill_tax": float(btax),
            "expected_exempt_tax": float(exempt_tax),
            "expected_expense_tax": float(exp_doc.vat_amount),
        }
    finally:
        db.close()


def test_synced_documents_yield_nonzero_vat_position(org_with_synced_docs):
    """Core M9 regression guard: synced docs with raw_data must NOT collapse VAT=0."""
    from cfo.database import SessionLocal
    from cfo.services.financial_synthesis import compute_vat_position

    ctx = org_with_synced_docs
    db = SessionLocal()
    try:
        pos = compute_vat_position(
            db, ctx["org_id"], start=date(2026, 5, 1), end=date(2026, 5, 31)
        )
        assert ctx["expected_invoice_tax"] > 0
        assert ctx["expected_bill_tax"] > 0
        assert ctx["expected_expense_tax"] > 0
        assert pos["output_vat"] == pytest.approx(ctx["expected_invoice_tax"])
        # input VAT = taxable bill + exempt bill(0) + filed expense
        expected_input = (
            ctx["expected_bill_tax"] + ctx["expected_exempt_tax"] + ctx["expected_expense_tax"]
        )
        assert pos["input_vat"] == pytest.approx(expected_input)
        assert pos["input_vat"] > 0
    finally:
        db.close()


def test_vat_exempt_document_contributes_zero(org_with_synced_docs):
    """A genuinely VAT-exempt synced bill (explicit vat=0 in raw_data) must not be
    fabricated into non-zero VAT: removing every OTHER input-side document and
    computing the VAT position from the exempt bill alone must yield input_vat==0,
    even though the bill's own gross total is non-zero."""
    from cfo.database import SessionLocal
    from cfo.models import Bill, Expense
    from cfo.services.financial_synthesis import compute_vat_position

    ctx = org_with_synced_docs
    assert ctx["expected_exempt_tax"] == 0.0  # sanity: derivation itself didn't fabricate VAT

    db = SessionLocal()
    try:
        # Strip the taxable bill and the filed expense, leaving only the exempt bill
        # on the input side, so compute_vat_position's input_vat isolates its
        # contribution.
        db.query(Bill).filter(
            Bill.organization_id == ctx["org_id"], Bill.bill_number == "B1"
        ).delete()
        db.query(Expense).filter(Expense.organization_id == ctx["org_id"]).delete()
        db.commit()

        pos = compute_vat_position(
            db, ctx["org_id"], start=date(2026, 5, 1), end=date(2026, 5, 31)
        )
        assert pos["input_vat"] == 0.0
    finally:
        db.close()
