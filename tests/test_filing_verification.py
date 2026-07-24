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


def test_over_claim_beyond_statutory_fraction_is_red_failure(fresh_org):
    """אירוח (input_vat_fraction=0 קבוע, תקנה 2(1)/15א) שתובע מע\"מ בכל זאת
    — כשל אדום, לא רק אזהרה."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        db.add(Expense(organization_id=org_id, source="manual", supplier_name="מסעדה של השף",
                       amount=Decimal("100"), vat_amount=Decimal("18"), vat_claimable=Decimal("18"),
                       total=Decimal("118"), expense_date=date(2026, 5, 20),
                       category="hospitality", status="filed"))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        assert result["status"] == "fail"
        c2 = result["checks"][1]
        assert c2["passed"] is False
        assert c2["fraction_gate_red_issues"]
        assert "תקנ" in c2["fraction_gate_red_issues"][0]
    finally:
        db.close()


def test_vehicle_purchase_legitimate_full_claim_does_not_false_positive(fresh_org):
    """רכב מסחרי (חריג תקנה 14) עם claimable=vat_amount (מלא, לגיטימי) —
    שער-השבר חייב לחשב את התקרה תלוית-ההקשר דרך אותו VehicleProfile,
    לא להשתמש בשבר הבסיס הקבוע (0) של vehicle_purchase — אחרת false
    positive על תביעה תקינה של רכב מסחרי/מונית/השכרה/לימוד נהיגה."""
    from cfo.models import VehicleProfile

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        db.add(VehicleProfile(organization_id=org_id, label="טנדר עבודה",
                              vehicle_kind="commercial", primarily_business=True))
        # 18% מדויק (100000+18000=118000) — לא לחצות את שער-השפיות הקיים
        # (MAX_VAT_RATE) שאינו קשור לשער-השבר החדש הנבדק כאן.
        db.add(Expense(organization_id=org_id, source="manual", supplier_name="סוכנות רכב",
                       amount=Decimal("100000"), vat_amount=Decimal("18000"), vat_claimable=Decimal("18000"),
                       total=Decimal("118000"), expense_date=date(2026, 5, 20),
                       category="vehicle_purchase", doc_kind="tax_invoice", status="filed"))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        assert result["status"] == "pass"
        c2 = result["checks"][1]
        assert c2["passed"] is True
        assert not c2["fraction_gate_red_issues"]
    finally:
        db.close()


def test_vehicle_over_claim_beyond_two_thirds_is_caught(fresh_org):
    """רכב עם profile primarily_business=True (תקרה 2/3) שתובע 100% מהמע\"מ
    — כשל אדום. זה בדיוק המקרה שהיה חומק דרך שער-השבר הסטטי (fraction=None
    ל-vehicle) לפני התיקון להשתמש ב-claimable_vat תלוי-ההקשר."""
    from cfo.models import VehicleProfile

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        db.add(VehicleProfile(organization_id=org_id, label="סדאן",
                              vehicle_kind="private", primarily_business=True))
        db.add(Expense(organization_id=org_id, source="manual", supplier_name="סונול",
                       amount=Decimal("100"), vat_amount=Decimal("18"), vat_claimable=Decimal("18"),
                       total=Decimal("118"), expense_date=date(2026, 5, 20),
                       category="vehicle", doc_kind="tax_invoice", status="filed"))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        assert result["status"] == "fail"
        c2 = result["checks"][1]
        assert c2["passed"] is False
        assert c2["fraction_gate_red_issues"]
    finally:
        db.close()


def test_legacy_unclaimed_zero_fraction_category_produces_warning_not_failure(fresh_org):
    """הוצאת אירוח עם מע\"מ אבל vat_claimable=None (טרם הוחל שער התשומות —
    נתון legacy) — אזהרה (warn), לא כשל."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        db.add(Expense(organization_id=org_id, source="manual", supplier_name="מסעדה של השף",
                       amount=Decimal("100"), vat_amount=Decimal("18"), vat_claimable=None,
                       total=Decimal("118"), expense_date=date(2026, 5, 20),
                       category="hospitality", status="filed"))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        assert result["status"] == "warn"
        c2 = result["checks"][1]
        assert c2["passed"] is None
        assert c2["fraction_gate_warnings"]
        assert "טרם הוחל שער התשומות" in c2["fraction_gate_warnings"][0]
    finally:
        db.close()


def test_legitimate_partial_vat_claim_still_passes(fresh_org):
    """הוצאת רכב עם ניכוי חלקי לגיטימי (2/3 מהמע\"מ) — הדוח והחישוב העצמאי
    חייבים להסכים (שניהם קוראים vat_claimable), ולא ליפול כ'פער חישוב עצמאי'
    רק כי vat_claimable != vat_amount."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        db.add(Expense(organization_id=org_id, source="manual", supplier_name="סונול",
                       amount=Decimal("100"), vat_amount=Decimal("18"), vat_claimable=Decimal("12"),
                       total=Decimal("118"), expense_date=date(2026, 5, 20),
                       category="vehicle", status="filed"))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        assert result["status"] == "pass"
        assert result["checks"][1]["passed"] is True
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


def test_external_id_twin_pair_is_not_flagged_as_duplicate(fresh_org):
    """תאום סנכרון (אותו מסמך SUMIT כ-Bill וגם כ-Expense עם אותו external_id)
    הוא התנהגות סטנדרטית של ה-sync, לא כפילות — בדיקה 3 חייבת לעבור נקי,
    אחרת כל תקופה רגילה תוצג באדום וההפעלה תלמד להתעלם מהכשל."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        vendor = Contact(organization_id=org_id, name="ספק תאום",
                         contact_type=ContactType.VENDOR, tax_id="514999000")
        db.add(vendor); db.flush()
        db.add(Bill(organization_id=org_id, external_id="SUMIT-TWIN-9", source="sumit",
                    vendor_id=vendor.id, bill_number="DOC-9000",
                    issue_date=date(2026, 5, 12), status=BillStatus.APPROVED,
                    subtotal=Decimal("1000"), tax=Decimal("180"), total=Decimal("1180")))
        db.add(Expense(organization_id=org_id, source="sumit", supplier_name="ספק תאום",
                       supplier_tax_id="514999000", invoice_number="DOC-9000",
                       external_id="SUMIT-TWIN-9",
                       amount=Decimal("1000"), vat_amount=Decimal("180"), total=Decimal("1180"),
                       expense_date=date(2026, 5, 12), status="filed"))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        c3 = result["checks"][2]
        assert c3["duplicate_candidates"] == []
        assert c3["passed"] is not False
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
