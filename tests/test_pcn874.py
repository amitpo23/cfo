"""Tests for the PCN874 detailed-VAT file builder.

Checks structural invariants (record types, header/trailer) and that the file's
totals reconcile to the canonical VAT position.
"""
from datetime import date

from cfo.database import SessionLocal
from cfo.models import Invoice, Bill, InvoiceStatus, BillStatus
from cfo.services import pcn874, financial_synthesis


def _seed(org_id):
    db = SessionLocal()
    try:
        for model in (Bill, Invoice):
            db.query(model).filter(model.organization_id == org_id,
                                   model.source == "pcn-test").delete()
        db.commit()
        db.add(Invoice(organization_id=org_id, external_id="PCN-INV-1", source="pcn-test",
                       invoice_number="100", issue_date=date(2026, 6, 5),
                       status=InvoiceStatus.SENT, subtotal=10000, tax=1800, total=11800,
                       allocation_number="123456789"))
        db.add(Bill(organization_id=org_id, external_id="PCN-BILL-1", source="pcn-test",
                    bill_number="B1", issue_date=date(2026, 6, 10),
                    status=BillStatus.RECEIVED, subtotal=2000, tax=360, total=2360))
        db.commit()
    finally:
        db.close()


def test_pcn874_file(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        out = pcn874.build_pcn874(db, org_id, 2026, 6, company_vat_id="514999999")
        lines = out["content"].split("\r\n")
        assert lines[0].startswith("O")          # header
        assert lines[-1].startswith("X")         # trailer
        assert out["record_count"] == 2          # 1 sale + 1 input
        assert any(l.startswith("S1") for l in lines)
        assert any(l.startswith("L") for l in lines)
        assert out["draft"] is True

        # Totals reconcile to the canonical VAT position for the same period.
        vat = financial_synthesis.compute_vat_position(
            db, org_id, start=date(2026, 6, 1), end=date(2026, 6, 30))
        assert out["summary"]["output_vat"] == vat["output_vat"] == 1800.0
        assert out["summary"]["input_vat"] == vat["input_vat"] == 360.0
        assert out["summary"]["net_vat"] == vat["net_vat"] == 1440.0
    finally:
        db.close()


def test_pcn874_route_requires_auth(client):
    assert client.get("/api/daily-reports/pcn874?year=2026&month=6").status_code == 403
