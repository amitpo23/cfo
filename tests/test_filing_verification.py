"""אימות משולש לדיווחים — הכלל המחייב: שלוש בדיקות בלתי-תלויות לכל פלט דיווח."""
from datetime import date, datetime
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Bill, BillStatus, Contact, ContactType, Expense, Invoice, InvoiceStatus
from cfo.services import filing_verification as fv


def _seed(db, org_id):
    c = Contact(organization_id=org_id, name="לקוח", contact_type=ContactType.CUSTOMER)
    db.add(c); db.flush()
    db.add(Invoice(organization_id=org_id, contact_id=c.id, external_id="i1", source="sumit",
                   invoice_number="100", issue_date=date(2026, 5, 10), status=InvoiceStatus.SENT,
                   subtotal=Decimal("1000"), tax=Decimal("180"), total=Decimal("1180"),
                   paid_amount=Decimal("0"), balance=Decimal("1180")))
    db.add(Bill(organization_id=org_id, external_id="b1", source="sumit", bill_number="B1",
                issue_date=date(2026, 5, 12), status=BillStatus.PAID,
                subtotal=Decimal("500"), tax=Decimal("90"), total=Decimal("590"),
                paid_amount=Decimal("590"), balance=Decimal("0")))
    db.commit()


def test_all_three_checks_pass_on_clean_period(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        assert result["status"] == "pass"
        assert len(result["checks"]) == 3
        assert result["checks"][0]["passed"] is True   # reconciliation
        assert result["checks"][1]["passed"] is True   # independent recomputation
        assert result["checks"][2]["passed"] is True   # completeness
    finally:
        db.close()


def test_pending_drafts_produce_warning_not_silent_pass(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        db.add(Expense(organization_id=org_id, external_id="draft1", source="sumit",
                       supplier_name="ספק SUMIT", amount=Decimal("0"), vat_amount=Decimal("0"),
                       total=Decimal("0"), expense_date=date(2026, 5, 20), status="pending"))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        assert result["status"] == "warn"
        c3 = result["checks"][2]
        assert c3["passed"] is None
        assert c3["pending_drafts"] == 1
        assert "ממתינות לתיוק" in c3["details"]
    finally:
        db.close()


def test_illegal_vat_rate_fails_sanity(fresh_org):
    """מסמך עם מע"מ מעל השיעור החוקי ביחס לנטו — בדיקה 2 נכשלת (אדום)."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Bill(organization_id=org_id, external_id="bad1", source="sumit", bill_number="BAD",
                    issue_date=date(2026, 5, 15), status=BillStatus.PAID,
                    subtotal=Decimal("100"), tax=Decimal("50"), total=Decimal("150"),
                    paid_amount=Decimal("150"), balance=Decimal("0")))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        assert result["status"] == "fail"
        assert result["checks"][1]["passed"] is False
        assert "חורג" in result["checks"][1]["details"]
    finally:
        db.close()


def test_verify_route_org_scoped(client, owner):
    r = client.get("/api/daily-reports/vat/verify?year=2026&month=5", headers=owner["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("pass", "warn", "fail")
    assert len(body["checks"]) == 3


def test_verify_route_requires_auth(client):
    assert client.get("/api/daily-reports/vat/verify?year=2026&month=5").status_code in (401, 403)
