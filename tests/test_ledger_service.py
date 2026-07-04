"""Tests for the derived double-entry shadow ledger.

The non-negotiable invariant: every entry balances and the whole trial balance
balances (Σdebit == Σcredit), including when source `total` is rounded oddly.
"""
from datetime import date

from cfo.database import SessionLocal
from cfo.models import Invoice, Bill, Expense, Payment, Contact, ContactType, InvoiceStatus, BillStatus
from cfo.services import ledger_service


def _seed(org_id):
    db = SessionLocal()
    try:
        # Idempotent: the `owner` fixture is session-scoped, so wipe any prior
        # ledger-test rows for this org before reseeding (avoids unique-id clashes
        # and cross-test amount accumulation).
        for model in (Payment, Expense, Bill, Invoice):
            db.query(model).filter(model.organization_id == org_id,
                                   model.source == "test").delete()
        db.commit()
        inv = Invoice(organization_id=org_id, external_id="L-INV-1", source="test",
                      invoice_number="100", issue_date=date(2026, 6, 1),
                      status=InvoiceStatus.SENT, subtotal=1000, tax=180, total=1180)
        db.add(inv)
        # A draft must NOT post.
        db.add(Invoice(organization_id=org_id, external_id="L-INV-DRAFT", source="test",
                       invoice_number="DR", issue_date=date(2026, 6, 2),
                       status=InvoiceStatus.DRAFT, subtotal=999, tax=179, total=1178))
        db.add(Bill(organization_id=org_id, external_id="L-BILL-1", source="test",
                    bill_number="B1", issue_date=date(2026, 6, 3),
                    status=BillStatus.RECEIVED, subtotal=500, tax=90, total=590))
        db.add(Expense(organization_id=org_id, external_id="L-EXP-1", source="test",
                       supplier_name="ספק", amount=200, vat_amount=36, total=236,
                       expense_date=date(2026, 6, 4), status="filed"))
        db.commit()
        inv_id = inv.id
        db.add(Payment(organization_id=org_id, external_id="L-PAY-1", source="test",
                       invoice_id=inv_id, payment_date=date(2026, 6, 5), amount=1180))
        db.commit()
        return inv_id
    finally:
        db.close()


def test_every_entry_balances_and_drafts_excluded(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        entries = ledger_service.build_journal(db, org_id)
        assert entries, "expected derived entries"
        for e in entries:
            assert e.balanced, f"unbalanced entry {e.source_ref}: {e.total_debit} != {e.total_credit}"
        refs = {e.source_ref for e in entries}
        # Draft invoice excluded; the others present.
        assert any(r.startswith("invoice:") for r in refs)
        assert any(r.startswith("bill:") for r in refs)
        assert any(r.startswith("expense:") for r in refs)
        assert any(r.startswith("payment:") for r in refs)
    finally:
        db.close()


def test_trial_balance_balances(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        tb = ledger_service.trial_balance(db, org_id)
        assert tb["balanced"] is True
        assert abs(tb["total_debit"] - tb["total_credit"]) < 0.01
        assert tb["derived"] is True
        # Revenue should be credited 1000 (net of the one posted invoice).
        rev = next(a for a in tb["accounts"] if a["account"] == "4000")
        assert rev["credit"] == 1000.0
        # VAT output 180.
        vat_out = next(a for a in tb["accounts"] if a["account"] == "2200")
        assert vat_out["credit"] == 180.0
    finally:
        db.close()


def test_general_ledger_running_balance(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        gl = ledger_service.general_ledger(db, org_id, "1100")  # לקוחות
        # Invoice debits 1180, receipt credits 1180 -> closing 0.
        assert gl["closing_balance"] == 0.0
        assert len(gl["movements"]) == 2
    finally:
        db.close()


def test_ledger_routes_require_auth(client):
    for path in ["/api/ledger/journal", "/api/ledger/trial-balance",
                 "/api/ledger/account/1100", "/api/ledger/chart"]:
        assert client.get(path).status_code == 403, path


def test_trial_balance_route_balances(client, fresh_org):
    iso = fresh_org()
    _seed(iso["org_id"])
    r = client.get("/api/ledger/trial-balance", headers=iso["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balanced"] is True
    assert body["derived"] is True
    assert body["total_debit"] == body["total_credit"]


def test_balance_sheet_identity_holds(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        bs = ledger_service.balance_sheet(db, org_id)
        assert bs["derived"] is True
        # Assets == Liabilities + Equity (identity by construction).
        assert bs["balanced"] is True
        assert abs(bs["total_assets"] - bs["total_equity_and_liabilities"]) < 0.01
    finally:
        db.close()


# ---------- כרטסת לקוח/ספק (contact_card) ----------

def _seed_contact_card(org_id):
    """לקוח עם חשבונית+תקבול, ספק עם חשבון+תשלום — כרונולוגיה שונה בין השניים."""
    db = SessionLocal()
    try:
        customer = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER,
                           name="לקוח כרטסת")
        vendor = Contact(organization_id=org_id, contact_type=ContactType.VENDOR,
                         name="ספק כרטסת")
        db.add_all([customer, vendor])
        db.flush()
        inv = Invoice(organization_id=org_id, contact_id=customer.id,
                     invoice_number="CARD-INV-1", issue_date=date(2026, 5, 1),
                     status=InvoiceStatus.SENT, subtotal=1000, tax=180, total=1180,
                     paid_amount=0, balance=1180)
        bill = Bill(organization_id=org_id, vendor_id=vendor.id,
                    bill_number="CARD-BILL-1", issue_date=date(2026, 5, 3),
                    status=BillStatus.RECEIVED, subtotal=500, tax=90, total=590,
                    paid_amount=0, balance=590)
        db.add_all([inv, bill])
        db.commit()
        db.add(Payment(organization_id=org_id, contact_id=customer.id, invoice_id=inv.id,
                      payment_date=date(2026, 5, 15), amount=1180))
        db.add(Payment(organization_id=org_id, contact_id=vendor.id, bill_id=bill.id,
                      payment_date=date(2026, 5, 20), amount=590))
        db.commit()
        return {"customer_id": customer.id, "vendor_id": vendor.id}
    finally:
        db.close()


def test_contact_card_customer_running_balance(fresh_org):
    org_id = fresh_org()["org_id"]
    ids = _seed_contact_card(org_id)
    db = SessionLocal()
    try:
        card = ledger_service.contact_card(db, org_id, ids["customer_id"])
        assert card["contact_name"] == "לקוח כרטסת"
        assert len(card["movements"]) == 2
        # חשבונית מגדילה את היתרה, תקבול מקזז אותה במלואה
        assert card["movements"][0]["amount"] == 1180
        assert card["movements"][0]["balance"] == 1180
        assert card["movements"][1]["amount"] == -1180
        assert card["closing_balance"] == 0.0
        assert card["derived"] is True
    finally:
        db.close()


def test_contact_card_vendor_running_balance(fresh_org):
    org_id = fresh_org()["org_id"]
    ids = _seed_contact_card(org_id)
    db = SessionLocal()
    try:
        card = ledger_service.contact_card(db, org_id, ids["vendor_id"])
        assert card["contact_name"] == "ספק כרטסת"
        assert len(card["movements"]) == 2
        assert card["movements"][0]["amount"] == 590
        assert card["movements"][1]["amount"] == -590
        assert card["closing_balance"] == 0.0
    finally:
        db.close()


def test_contact_card_finds_payment_with_unresolved_contact_id(fresh_org):
    """A Payment synced with contact_id=NULL (contact_external_id didn't
    resolve) but a valid invoice_id/bill_id link must still be picked up
    via that link -- otherwise the card understates how much is actually
    settled, overstating the outstanding balance."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        customer = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER,
                           name="לקוח לא-משוייך")
        vendor = Contact(organization_id=org_id, contact_type=ContactType.VENDOR,
                         name="ספק לא-משוייך")
        db.add_all([customer, vendor])
        db.flush()
        inv = Invoice(organization_id=org_id, contact_id=customer.id,
                     invoice_number="UNLINKED-INV-1", issue_date=date(2026, 5, 1),
                     status=InvoiceStatus.SENT, subtotal=1000, tax=180, total=1180,
                     paid_amount=0, balance=0)
        bill = Bill(organization_id=org_id, vendor_id=vendor.id,
                    bill_number="UNLINKED-BILL-1", issue_date=date(2026, 5, 3),
                    status=BillStatus.RECEIVED, subtotal=500, tax=90, total=590,
                    paid_amount=0, balance=0)
        db.add_all([inv, bill])
        db.commit()
        # contact_id intentionally omitted -- simulates an unresolved sync.
        db.add(Payment(organization_id=org_id, contact_id=None, invoice_id=inv.id,
                      payment_date=date(2026, 5, 15), amount=1180))
        db.add(Payment(organization_id=org_id, contact_id=None, bill_id=bill.id,
                      payment_date=date(2026, 5, 20), amount=590))
        db.commit()
        customer_id, vendor_id = customer.id, vendor.id
    finally:
        db.close()

    db = SessionLocal()
    try:
        customer_card = ledger_service.contact_card(db, org_id, customer_id)
        vendor_card = ledger_service.contact_card(db, org_id, vendor_id)
    finally:
        db.close()

    assert len(customer_card["movements"]) == 2, customer_card["movements"]
    assert customer_card["closing_balance"] == 0.0
    assert len(vendor_card["movements"]) == 2, vendor_card["movements"]
    assert vendor_card["closing_balance"] == 0.0


def test_contact_card_returns_none_for_other_org_contact(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    ids = _seed_contact_card(org_a)
    db = SessionLocal()
    try:
        assert ledger_service.contact_card(db, org_b, ids["customer_id"]) is None
    finally:
        db.close()


def test_contact_card_route_requires_auth(client):
    assert client.get("/api/ledger/contact/1/card").status_code == 403


def test_contact_card_route_404_for_other_org_contact(fresh_org, client):
    iso_a = fresh_org()
    iso_b = fresh_org()
    ids = _seed_contact_card(iso_a["org_id"])
    r = client.get(f"/api/ledger/contact/{ids['customer_id']}/card", headers=iso_b["headers"])
    assert r.status_code == 404


def test_contact_card_route_returns_card(fresh_org, client):
    iso = fresh_org()
    ids = _seed_contact_card(iso["org_id"])
    r = client.get(f"/api/ledger/contact/{ids['customer_id']}/card", headers=iso["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["contact_name"] == "לקוח כרטסת"
    assert body["closing_balance"] == 0.0
