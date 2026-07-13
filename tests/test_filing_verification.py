"""אימות משולש לדיווחים — הכלל המחייב: שלוש בדיקות בלתי-תלויות לכל פלט דיווח."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import (
    Bill, BillStatus, Contact, ContactType, Expense, Invoice, InvoiceStatus,
    SyncRun, SyncStatus,
)
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
    # סנכרון SUMIT מוצלח וטרי — "תקופה נקייה" כוללת גם נתונים עדכניים, לא רק
    # מסמכים תקינים (ממצא אודיט אליהב 2026-07-13: שער טריות סנכרון בבדיקה 3).
    db.add(SyncRun(organization_id=org_id, source="sumit", status=SyncStatus.COMPLETED,
                   started_at=datetime.utcnow(), finished_at=datetime.utcnow()))
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


def test_stale_sync_produces_warning_in_completeness_check(fresh_org):
    """ממצא אודיט אליהב 2026-07-13 (ממצא 5): סנכרון SUMIT קפא 3 שבועות והדוח הופק
    בלי שום אזהרה. סנכרון אחרון בן >26 שעות -> אזהרה מפורשת בבדיקה 3."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        # מחליפים את הסנכרון הטרי מ-_seed בסנכרון בן 3 שבועות (קפוא).
        db.query(SyncRun).filter(SyncRun.organization_id == org_id,
                                  SyncRun.source == "sumit").delete()
        stale_at = datetime.utcnow() - timedelta(days=21)
        db.add(SyncRun(organization_id=org_id, source="sumit", status=SyncStatus.COMPLETED,
                       started_at=stale_at, finished_at=stale_at))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        assert result["status"] == "warn"
        c3 = result["checks"][2]
        assert c3["passed"] is None
        assert "סנכרון SUMIT אחרון" in c3["details"]
        assert "אין להגיש בלי רענון" in c3["details"]
    finally:
        db.close()


def test_no_successful_sync_ever_produces_stronger_warning(fresh_org):
    """אין אף ריצת סנכרון SUMIT מוצלחת לארגון — אזהרה חמורה יותר מסתם 'ישן'."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        db.query(SyncRun).filter(SyncRun.organization_id == org_id,
                                  SyncRun.source == "sumit").delete()
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        assert result["status"] == "warn"
        c3 = result["checks"][2]
        assert c3["passed"] is None
        assert "מעולם לא בוצע סנכרון" in c3["details"]
    finally:
        db.close()
