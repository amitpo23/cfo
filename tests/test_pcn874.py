"""Tests for the PCN874 detailed-VAT file builder.

Checks structural invariants (record types, header/trailer) and that the file's
totals reconcile to the canonical VAT position.
"""
from datetime import date, datetime

from cfo.database import SessionLocal
from cfo.models import Invoice, Bill, Expense, InvoiceStatus, BillStatus
from cfo.services import pcn874, daily_reports_service, financial_synthesis


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


def test_pcn874_reconciles_with_vat_report_document_basis(fresh_org):
    """summary של build_pcn874 חייב להתאים 1:1 ל-vat_report_period עם אותם פרמטרים
    (basis=document, months=1) — אותה לוגיקת בחירת מסמכים בדיוק."""
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        out = pcn874.build_pcn874(db, org_id, 2026, 6, company_vat_id="514999999")
        rep = daily_reports_service.vat_report_period(db, org_id, 2026, 6, basis="document")
        assert out["summary"]["output_vat"] == rep["output_vat"]
        assert out["summary"]["input_vat"] == rep["input_vat"]
        assert out["summary"]["net_vat"] == rep["net_vat"]
    finally:
        db.close()


def test_pcn874_reconciles_with_vat_report_captured_basis(fresh_org):
    """אותה בדיקת תיאום, הפעם עם basis=captured — כאן גם הדה-דופ וגם מקור
    התאריך (created_at) חייבים לעבוד זהה בשני המנועים."""
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        # הוצאה עם expense_date במאי אך created_at (מועד קליטה) ביוני.
        exp = Expense(organization_id=org_id, external_id="PCN-EXP-1", source="pcn-test",
                     supplier_name="ספק", supplier_tax_id="987654321",
                     amount=300, vat_amount=54, total=354,
                     expense_date=date(2026, 5, 15), status="filed")
        db.add(exp)
        db.commit()
        db.refresh(exp)
        db.query(Expense).filter(Expense.id == exp.id).update(
            {"created_at": datetime(2026, 6, 12, 8, 0, 0)})
        # תאריך קליטה דטרמיניסטי לביל הזרוע (ולא "עכשיו" האמיתי) כדי שהתוצאה לא
        # תלויה בתאריך הרצת הטסט בפועל.
        db.query(Bill).filter(Bill.organization_id == org_id,
                              Bill.external_id == "PCN-BILL-1").update(
            {"created_at": datetime(2026, 6, 11, 8, 0, 0)})
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        out = pcn874.build_pcn874(db, org_id, 2026, 6, basis="captured",
                                  company_vat_id="514999999")
        rep = daily_reports_service.vat_report_period(db, org_id, 2026, 6, basis="captured")
        assert out["summary"]["output_vat"] == rep["output_vat"]
        assert out["summary"]["input_vat"] == rep["input_vat"] == 54.0 + 360.0
        assert out["summary"]["net_vat"] == rep["net_vat"]
    finally:
        db.close()


def test_pcn874_bimonthly_period(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        out = pcn874.build_pcn874(db, org_id, 2026, 5, months=2, company_vat_id="514999999")
        rep = daily_reports_service.vat_report_period(db, org_id, 2026, 5, months=2)
        assert out["summary"]["output_vat"] == rep["output_vat"] == 1800.0
        assert out["summary"]["input_vat"] == rep["input_vat"] == 360.0
    finally:
        db.close()


def test_pcn874_file_route_returns_downloadable_file(client, owner):
    resp = client.get(
        "/api/daily-reports/pcn874/file?year=2026&month=6&company_vat_id=514999999",
        headers=owner["headers"],
    )
    assert resp.status_code == 200, resp.text
    cd = resp.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "PCN874" in cd
    body = resp.text
    lines = body.split("\r\n")
    assert lines[0].startswith("O")
    assert lines[-1].startswith("X")


def test_pcn874_file_route_requires_auth(client):
    assert client.get("/api/daily-reports/pcn874/file?year=2026&month=6").status_code == 403
