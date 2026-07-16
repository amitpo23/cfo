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
        assert "משיכת מסמכי SUMIT אחרונה" in c3["details"]
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


def test_freshness_gate_uses_checkpoints_not_run_status(fresh_org):
    """ריצת סנכרון COMPLETED שדילגה על הכול (circuit open) לא נחשבת טרייה —
    האמת היא SyncCheckpoint.last_success_at (ממצא חי 13/07: org1 עם ריצות
    'מוצלחות' בזמן חסימת obligo וללא משיכה אמיתית)."""
    from datetime import datetime, timedelta
    from cfo.database import SessionLocal
    from cfo.models import SyncRun, SyncStatus, SyncCheckpoint
    from cfo.services import filing_verification as fv

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        # ריצה "מוצלחת" טרייה — אבל ה-checkpoint מעיד שאין משיכה אמיתית
        db.add(SyncRun(organization_id=org_id, source="sumit",
                       status=SyncStatus.COMPLETED, sync_type="full",
                       started_at=datetime.utcnow(), finished_at=datetime.utcnow()))
        db.add(SyncCheckpoint(organization_id=org_id, source="sumit",
                              entity_type="invoices", last_success_at=None,
                              circuit_open_until=datetime.utcnow() + timedelta(hours=5)))
        db.add(SyncCheckpoint(organization_id=org_id, source="sumit",
                              entity_type="bills", last_success_at=None))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        c3 = result["checks"][2]
        assert c3["passed"] is None  # אזהרה
        assert "מעולם לא הצליחה" in c3["details"] or "אין להגיש" in c3["details"]
    finally:
        db.close()


def test_high_duplicate_in_period_fails_completeness_check(fresh_org):
    """ממצא P0 2026-07: מנה 4 חפפה 14 שורות למנה 2 הסגורה — כמעט כפל-ספירה
    של ₪150K. שני מסמכי הוצאה עם אותו ח.פ+אסמכתא בתקופה => בדיקה 3 נכשלת."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        db.add(Expense(organization_id=org_id, source="manual", supplier_name="ספק ענק",
                       supplier_tax_id="512345678", invoice_number="BATCH2-ROW14",
                       amount=Decimal("150000"), vat_amount=Decimal("0"), total=Decimal("150000"),
                       expense_date=date(2026, 5, 5), status="filed"))
        db.add(Expense(organization_id=org_id, source="manual", supplier_name="ספק ענק",
                       supplier_tax_id="512345678", invoice_number="BATCH2-ROW14",
                       amount=Decimal("150000"), vat_amount=Decimal("0"), total=Decimal("150000"),
                       expense_date=date(2026, 5, 20), status="filed"))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        c3 = result["checks"][2]
        assert result["status"] == "fail"
        assert c3["passed"] is False
        assert len(c3["duplicate_candidates"]) >= 1
        assert "כפילות" in c3["details"]
        assert len(result["checks"]) == 3  # still exactly 3 checks
    finally:
        db.close()


def test_no_duplicates_clean_period_still_passes(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        db.add(Expense(organization_id=org_id, source="manual", supplier_name="ספק תקין א",
                       supplier_tax_id="111111118", invoice_number="A-1",
                       amount=Decimal("500"), vat_amount=Decimal("90"), total=Decimal("590"),
                       expense_date=date(2026, 5, 5), status="filed"))
        db.add(Expense(organization_id=org_id, source="manual", supplier_name="ספק תקין ב",
                       supplier_tax_id="222222229", invoice_number="B-1",
                       amount=Decimal("2000"), vat_amount=Decimal("360"), total=Decimal("2360"),
                       expense_date=date(2026, 5, 6), status="filed"))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        c3 = result["checks"][2]
        assert c3["duplicate_candidates"] == []
        assert result["status"] == "pass"
    finally:
        db.close()


def test_vat_ratio_below_threshold_warns_missing_vat_splits(fresh_org):
    """ממצא עומר ועודד: ₪6.7K מתוך ₪731K = 0.9% — מפתחות שהוזנו ללא מע"מ.
    69 מסמכים (>=10) עם יחס תשומות/סך-הוצאות מתחת ל-3% => אזהרה.

    כל מסמך בנפרד עומד בשיעור המע"מ החוקי (18%, מתחת לתקרת השפיות 18.5%) —
    זו לא בעיית מסמך בודד (בדיקה 2), אלא דפוס-על של רוב המסמכים ללא מע"מ כלל."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        # 66 הוצאות ללא מע"מ כלל (מפתחות שהוזנו בטעות בלי פיצול)
        for i in range(66):
            db.add(Expense(organization_id=org_id, source="manual",
                           supplier_name=f"ספק {i}", supplier_tax_id=f"{300000000+i}",
                           invoice_number=f"NOVAT-{i}",
                           amount=Decimal("11000.00"), vat_amount=Decimal("0"),
                           total=Decimal("11000.00"),
                           expense_date=date(2026, 5, 8), status="filed"))
        # 3 הוצאות עם מע"מ תקין (18%, ₪2233.33 כל אחת = ₪6700 בסה"כ)
        for i in range(3):
            db.add(Expense(organization_id=org_id, source="manual",
                           supplier_name=f"ספק תקין {i}", supplier_tax_id=f"{400000000+i}",
                           invoice_number=f"HASVAT-{i}",
                           amount=Decimal("12407.39"), vat_amount=Decimal("2233.33"),
                           total=Decimal("14640.72"),
                           expense_date=date(2026, 5, 9), status="filed"))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        c3 = result["checks"][2]
        assert result["checks"][1]["passed"] is True  # לא בעיית מסמך בודד
        assert c3["vat_ratio_warning"] is not None
        assert c3["vat_ratio_warning"]["doc_count"] >= 69
        assert c3["vat_ratio_warning"]["ratio"] < 0.03
        assert "חשד למפתחות ללא מע\"מ" in c3["details"]
        assert result["status"] == "warn"
        assert len(result["checks"]) == 3
    finally:
        db.close()


def test_vat_ratio_ignores_unfiled_expenses_in_denominator(fresh_org):
    """רגרסיה: expenses שטרם תויקו (status='pending', לא נספרות במונה
    input_vat של הדוח) לא צריכות לנפח את המכנה של יחס המע"מ — אחרת תקופה
    שרק ממתינה לתיוק מאובחנת בטעות כ'מפתחות ללא מע\"מ'."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        # 10 מסמכי bill מתויקים עם יחס מע"מ תקין (18%) — לא אמורים להתריע
        for i in range(10):
            db.add(Bill(organization_id=org_id, external_id=f"vr{i}", source="sumit",
                        bill_number=f"VR-{i}", issue_date=date(2026, 5, 3),
                        status=BillStatus.APPROVED,
                        subtotal=Decimal("1000"), tax=Decimal("180"), total=Decimal("1180"),
                        paid_amount=Decimal("0"), balance=Decimal("1180")))
        # המון expenses שטרם תויקו (pending) עם סכומים גדולים — לא אמורות
        # להשפיע על יחס המע"מ כלל (לא סופרות לא במונה ולא במכנה)
        for i in range(100):
            db.add(Expense(organization_id=org_id, source="manual",
                           supplier_name=f"טרם תויק {i}", invoice_number=f"NOTYET-{i}",
                           amount=Decimal("100000"), vat_amount=Decimal("0"),
                           total=Decimal("100000"),
                           expense_date=date(2026, 5, 15), status="pending"))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        c3 = result["checks"][2]
        assert c3["vat_ratio_warning"] is None
    finally:
        db.close()


def test_freshness_gate_fresh_checkpoint_passes(fresh_org):
    from datetime import datetime
    from cfo.database import SessionLocal
    from cfo.models import SyncCheckpoint
    from cfo.services import filing_verification as fv

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        db.add(SyncCheckpoint(organization_id=org_id, source="sumit",
                              entity_type="invoices", last_success_at=datetime.utcnow()))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        assert result["checks"][2]["passed"] is True
    finally:
        db.close()
