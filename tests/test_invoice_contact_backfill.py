"""fetch_customers() previously derived customers from SUMIT's incomplete
get_debt_report() (fixed 2026-07-04, see test_sumit_connector_customers.py) --
any invoice whose real customer never happened to appear in that debt report
kept contact_id=None forever, even after the fix, because a normal re-sync's
payload_hash short-circuit skips re-touching an invoice whose underlying
SUMIT document hasn't changed (see sync_engine._upsert_invoice). Existing
broken invoices need an explicit backfill against the Contact rows a fixed
customer sync creates -- this is a pure local-DB repair, no SUMIT calls."""
from datetime import date
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Bill, BillStatus, Contact, ContactType, Invoice, InvoiceStatus
from cfo.services.sync_engine import SyncEngine


def test_backfill_links_invoice_to_contact_created_after_the_fact(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        # Invoice synced before the customer existed -- contact_id is None,
        # but raw_data (stored from the original SUMIT document) still has
        # the real customer_id.
        inv = Invoice(
            organization_id=org_id, external_id="doc-1", source="sumit",
            contact_id=None, invoice_number="20005", status=InvoiceStatus.SENT,
            total=Decimal("23000"), balance=Decimal("23000"),
            raw_data={"customer_id": "cust-99", "customer_name": "אליהב כהן"},
        )
        db.add(inv)
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        contact = Contact(
            organization_id=org_id, external_id="cust-99", source="sumit",
            contact_type=ContactType.CUSTOMER, name="אליהב כהן",
        )
        db.add(contact)
        db.commit()
        contact_id = contact.id
    finally:
        db.close()

    engine = SyncEngine(SessionLocal(), connector=None, organization_id=org_id, source="sumit")
    result = engine.backfill_invoice_contacts()
    engine.db.close()

    assert result["invoices_fixed"] == 1

    db = SessionLocal()
    try:
        refreshed = db.query(Invoice).filter(Invoice.external_id == "doc-1").first()
        assert refreshed.contact_id == contact_id
    finally:
        db.close()


def test_backfill_is_a_noop_when_no_matching_contact_exists(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Invoice(
            organization_id=org_id, external_id="doc-2", source="sumit",
            contact_id=None, invoice_number="20006", status=InvoiceStatus.SENT,
            total=Decimal("100"), balance=Decimal("100"),
            raw_data={"customer_id": "cust-unresolvable"},
        ))
        db.commit()
    finally:
        db.close()

    engine = SyncEngine(SessionLocal(), connector=None, organization_id=org_id, source="sumit")
    result = engine.backfill_invoice_contacts()
    engine.db.close()

    assert result["invoices_fixed"] == 0


def test_backfill_links_bill_to_vendor_created_after_the_fact(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Bill(
            organization_id=org_id, external_id="bill-1", source="sumit",
            vendor_id=None, bill_number="B-1", status=BillStatus.RECEIVED,
            total=Decimal("500"), balance=Decimal("500"),
            raw_data={"customer_id": "vendor-99"},
        ))
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        vendor = Contact(
            organization_id=org_id, external_id="vendor-99", source="sumit",
            contact_type=ContactType.VENDOR, name="ספק אמיתי",
        )
        db.add(vendor)
        db.commit()
        vendor_id = vendor.id
    finally:
        db.close()

    engine = SyncEngine(SessionLocal(), connector=None, organization_id=org_id, source="sumit")
    result = engine.backfill_bill_vendors()
    engine.db.close()

    assert result["bills_fixed"] == 1

    db = SessionLocal()
    try:
        refreshed = db.query(Bill).filter(Bill.external_id == "bill-1").first()
        assert refreshed.vendor_id == vendor_id
    finally:
        db.close()


def test_backfill_only_touches_invoices_missing_a_contact(fresh_org):
    """Invoices that already have a contact_id are left untouched."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        contact = Contact(
            organization_id=org_id, external_id="cust-1", source="sumit",
            contact_type=ContactType.CUSTOMER, name="לקוח קיים",
        )
        db.add(contact)
        db.flush()
        db.add(Invoice(
            organization_id=org_id, external_id="doc-3", source="sumit",
            contact_id=contact.id, invoice_number="20007", status=InvoiceStatus.SENT,
            total=Decimal("100"), balance=Decimal("100"),
            raw_data={"customer_id": "cust-1"},
        ))
        db.commit()
    finally:
        db.close()

    engine = SyncEngine(SessionLocal(), connector=None, organization_id=org_id, source="sumit")
    result = engine.backfill_invoice_contacts()
    engine.db.close()

    assert result["invoices_fixed"] == 0
