"""בסיס קליטה (captured) + תקופה דו-חודשית לדוח המע"מ (vat_report_period).

עסקאות (מכירות) תמיד לפי תאריך המסמך. תשומות (bills/expenses) — ב-basis="captured"
נבחרות לפי created_at (מועד הקליטה) בתוך התקופה; ב-basis="document" (ברירת מחדל,
תואם להתנהגות הקיימת) לפי תאריך המסמך.
"""
from datetime import date, datetime

from cfo.database import SessionLocal
from cfo.models import Invoice, Bill, Expense, InvoiceStatus, BillStatus
from cfo.services import daily_reports_service


def _seed_basic(org_id):
    db = SessionLocal()
    try:
        for model in (Bill, Invoice, Expense):
            db.query(model).filter(model.organization_id == org_id).delete()
        db.commit()
        # חשבונית מכירה ביוני — נספרת תמיד לפי תאריך מסמך.
        db.add(Invoice(organization_id=org_id, external_id="VRP-INV-1", source="vrp-test",
                       invoice_number="1", issue_date=date(2026, 6, 5),
                       status=InvoiceStatus.SENT, subtotal=1000, tax=180, total=1180))
        db.commit()
    finally:
        db.close()


def test_captured_basis_includes_document_dated_earlier_but_synced_in_period(fresh_org):
    """הוצאה עם expense_date בחודש קודם (מאי) אך created_at ביוני — נכללת
    ב-basis=captured לחודש יוני, ולא נכללת ב-basis=document."""
    org_id = fresh_org()["org_id"]
    _seed_basic(org_id)
    db = SessionLocal()
    try:
        exp = Expense(organization_id=org_id, external_id="VRP-EXP-1", source="vrp-test",
                     supplier_name="ספק מאי", supplier_tax_id="123456789",
                     amount=500, vat_amount=90, total=590,
                     expense_date=date(2026, 5, 20), status="filed")
        db.add(exp)
        db.commit()
        db.refresh(exp)
        # created_at לא נשלט ע"י ה-constructor (default=utcnow) — דורס ידנית לתאריך קליטה ביוני.
        db.query(Expense).filter(Expense.id == exp.id).update(
            {"created_at": datetime(2026, 6, 10, 9, 0, 0)})
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        doc_basis = daily_reports_service.vat_report_period(db, org_id, 2026, 6, basis="document")
        captured_basis = daily_reports_service.vat_report_period(db, org_id, 2026, 6, basis="captured")

        assert doc_basis["input_vat"] == 0.0          # תאריך מסמך מאי — לא בתקופת יוני
        assert captured_basis["input_vat"] == 90.0     # תאריך קליטה ביוני — כלול

        # להיפך: basis=document כן כולל אותה בתקופת מאי (תאריך המסמך).
        may_doc_basis = daily_reports_service.vat_report_period(db, org_id, 2026, 5, basis="document")
        may_captured_basis = daily_reports_service.vat_report_period(db, org_id, 2026, 5, basis="captured")
        assert may_doc_basis["input_vat"] == 90.0
        assert may_captured_basis["input_vat"] == 0.0  # נקלטה ביוני, לא במאי

        # צד העסקאות (מכירות) תמיד לפי תאריך מסמך, גם ב-captured.
        assert doc_basis["output_vat"] == captured_basis["output_vat"] == 180.0
    finally:
        db.close()


def test_bimonthly_period_accumulates_both_months_not_third(fresh_org):
    """תקופה דו-חודשית (מאי-יוני, חודש עוגן=5) — מסמכים משני החודשים מצטברים;
    מסמך מאפריל (חודש שלישי, מחוץ לתקופה) לא נכלל."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        for model in (Bill, Invoice, Expense):
            db.query(model).filter(model.organization_id == org_id).delete()
        db.commit()
        db.add(Invoice(organization_id=org_id, external_id="BM-INV-APR", source="bm-test",
                       invoice_number="A1", issue_date=date(2026, 4, 15),
                       status=InvoiceStatus.SENT, subtotal=1000, tax=180, total=1180))
        db.add(Invoice(organization_id=org_id, external_id="BM-INV-MAY", source="bm-test",
                       invoice_number="M1", issue_date=date(2026, 5, 10),
                       status=InvoiceStatus.SENT, subtotal=2000, tax=360, total=2360))
        db.add(Invoice(organization_id=org_id, external_id="BM-INV-JUN", source="bm-test",
                       invoice_number="J1", issue_date=date(2026, 6, 20),
                       status=InvoiceStatus.SENT, subtotal=3000, tax=540, total=3540))
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        rep = daily_reports_service.vat_report_period(db, org_id, 2026, 5, months=2)
        # מאי (360) + יוני (540) = 900; אפריל (180) לא נכלל.
        assert rep["output_vat"] == 900.0
        assert rep["sales_documents"] == 2
        assert len(rep["breakdown"]) == 2
        by_period = {b["period"]: b for b in rep["breakdown"]}
        assert by_period["2026-05"]["output_vat"] == 360.0
        assert by_period["2026-06"]["output_vat"] == 540.0
        assert rep["due_date"] == "2026-07-15"
    finally:
        db.close()


def test_vat_report_default_matches_old_behavior(fresh_org):
    """vat_report() (ללא months/basis) חייב להישאר זהה להתנהגות הקודמת."""
    org_id = fresh_org()["org_id"]
    _seed_basic(org_id)
    db = SessionLocal()
    try:
        rep = daily_reports_service.vat_report(db, org_id, 2026, 6)
        assert rep["output_vat"] == 180.0
        assert rep["input_vat"] == 0.0
        assert rep["net_vat"] == 180.0
        assert rep["sales_documents"] == 1
        assert rep["due_date"] == "2026-07-15"
        assert rep["derived"] is True
    finally:
        db.close()


def test_vat_report_route_accepts_months_and_basis(client, owner):
    resp = client.get(
        "/api/daily-reports/vat?year=2026&month=5&months=2&basis=captured",
        headers=owner["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["months"] == 2
    assert body["basis"] == "captured"
