"""Tests for document anomaly detection — modeled on the real doc-120000 mistake."""
from datetime import date

from cfo.database import SessionLocal
from cfo.models import Invoice, Bill, Contact, InvoiceStatus, BillStatus, ContactType
from cfo.services import document_anomalies


def _seed(org_id):
    db = SessionLocal()
    try:
        for model in (Bill, Invoice, Contact):
            db.query(model).filter(model.organization_id == org_id,
                                   model.source == "anom-test").delete()
        db.commit()
        # A normal customer + a supplier (vendor) contact.
        vendor = Contact(organization_id=org_id, source="anom-test", name="שופרסל בע\"מ",
                         contact_type=ContactType.VENDOR, tax_id="520022732")
        cust = Contact(organization_id=org_id, source="anom-test", name="לקוח רגיל",
                       contact_type=ContactType.CUSTOMER, tax_id="111111111")
        db.add_all([vendor, cust]); db.commit()
        # 4 normal small invoices (~20k) to establish a median.
        for n in range(4):
            db.add(Invoice(organization_id=org_id, external_id=f"AN-N{n}", source="anom-test",
                           invoice_number=f"{n}", issue_date=date(2026, 2, 1),
                           status=InvoiceStatus.SENT, contact_id=cust.id,
                           subtotal=20000, tax=3600, total=23600, allocation_number="A1"))
        # The anomaly: huge invoice to the supplier, no allocation number.
        db.add(Invoice(organization_id=org_id, external_id="AN-BIG", source="anom-test",
                       invoice_number="120000", issue_date=date(2026, 5, 15),
                       status=InvoiceStatus.SENT, contact_id=vendor.id,
                       subtotal=266833, tax=0, total=266833, allocation_number=None))
        # A bill from the same supplier (so vendor cross-ref also fires).
        db.add(Bill(organization_id=org_id, external_id="AN-BILL", source="anom-test",
                    bill_number="B1", issue_date=date(2026, 5, 1),
                    status=BillStatus.RECEIVED, vendor_id=vendor.id,
                    subtotal=100, tax=18, total=118))
        db.commit()
        return vendor.id
    finally:
        db.close()


def test_detects_all_three_anomaly_types(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        findings = document_anomalies.detect_document_anomalies(db, org_id)
        types = {f["type"] for f in findings}
        assert "magnitude_outlier" in types
        assert "missing_allocation" in types
        assert "vendor_as_customer" in types
        # All three point at invoice 120000.
        big = [f for f in findings if "120000" in f["title"] or
               f["refs"].get("invoice_id")]
        assert big
    finally:
        db.close()


def test_clean_book_has_no_anomalies(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        # Only normal invoices to a real customer.
        cust = Contact(organization_id=org_id, source="anom-test", name="לקוח",
                       contact_type=ContactType.CUSTOMER, tax_id="222")
        db.add(cust); db.commit()
        for n in range(4):
            db.add(Invoice(organization_id=org_id, external_id=f"OK{n}", source="anom-test",
                           invoice_number=f"{n}", issue_date=date(2026, 2, 1),
                           status=InvoiceStatus.SENT, contact_id=cust.id,
                           subtotal=10000, tax=1800, total=11800, allocation_number="A1"))
        db.commit()
        findings = document_anomalies.detect_document_anomalies(db, org_id)
        assert findings == []
    finally:
        db.close()


def test_anomalies_route_requires_auth(client):
    assert client.get("/api/engine/anomalies").status_code == 403


def test_persist_anomalies_creates_insights(fresh_org):
    from cfo.models import CfoInsight
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        res = document_anomalies.persist_anomalies(db, org_id)
        assert res["created"] >= 3
        rows = db.query(CfoInsight).filter(CfoInsight.organization_id == org_id).all()
        assert any(r.insight_type == "vendor_as_customer" for r in rows)
        # Idempotent: a second run updates, doesn't duplicate.
        res2 = document_anomalies.persist_anomalies(db, org_id)
        assert res2["created"] == 0 and res2["updated"] >= 3
    finally:
        db.close()
