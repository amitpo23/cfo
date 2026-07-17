"""FilingCrosscheck — הרגל שלישי של האימות המשולש: הצלבה מוקלטת מול ספרי
SUMIT (במקום הנחיה ידנית סתמית). ר' services/filing_verification.py
ו-api/routes/daily_reports.py (POST/GET /daily-reports/vat/crosscheck)."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import (
    Bill, BillStatus, Contact, ContactType, FilingCrosscheck, Invoice,
    InvoiceStatus, SyncRun, SyncStatus,
)
from cfo.services import filing_verification as fv


def _seed(db, org_id):
    """אותה תקופה 'נקייה' מ-test_filing_verification: תשומות ₪90, עסקאות ₪180."""
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
    db.add(SyncRun(organization_id=org_id, source="sumit", status=SyncStatus.COMPLETED,
                   started_at=datetime.utcnow(), finished_at=datetime.utcnow()))
    db.commit()


# ---------- routes: POST/GET upsert ----------

def test_post_crosscheck_creates_row(client, fresh_org):
    org = fresh_org()
    r = client.post("/api/daily-reports/vat/crosscheck", headers=org["headers"], json={
        "year": 2026, "month": 5, "months": 1, "basis": "document",
        "books_input_vat": 90.0, "books_output_vat": 180.0, "noted_by": "בודק",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["exists"] is True
    assert body["period"] == "2026-05"
    assert body["books_input_vat"] == 90.0
    assert body["books_output_vat"] == 180.0
    assert body["noted_by"] == "בודק"


def test_post_crosscheck_upserts_same_period_basis(client, fresh_org):
    org = fresh_org()
    payload = {"year": 2026, "month": 5, "months": 1, "basis": "document",
               "books_input_vat": 90.0}
    client.post("/api/daily-reports/vat/crosscheck", headers=org["headers"], json=payload)
    payload["books_input_vat"] = 150.0
    r = client.post("/api/daily-reports/vat/crosscheck", headers=org["headers"], json=payload)
    assert r.json()["books_input_vat"] == 150.0

    db = SessionLocal()
    try:
        count = db.query(FilingCrosscheck).filter(
            FilingCrosscheck.organization_id == org["org_id"]).count()
        assert count == 1  # upsert, לא כפילות
    finally:
        db.close()


def test_get_crosscheck_missing_returns_exists_false(client, fresh_org):
    org = fresh_org()
    r = client.get(
        "/api/daily-reports/vat/crosscheck?year=2026&month=5&months=1&basis=document",
        headers=org["headers"],
    )
    assert r.status_code == 200
    assert r.json()["exists"] is False


def test_get_crosscheck_after_post_roundtrips_bimonthly_period(client, fresh_org):
    org = fresh_org()
    client.post("/api/daily-reports/vat/crosscheck", headers=org["headers"], json={
        "year": 2026, "month": 5, "months": 2, "basis": "document",
        "books_input_vat": 300.0,
    })
    r = client.get(
        "/api/daily-reports/vat/crosscheck?year=2026&month=5&months=2&basis=document",
        headers=org["headers"],
    )
    body = r.json()
    assert body["exists"] is True
    assert body["period"] == "2026-05_2026-06"
    assert body["books_input_vat"] == 300.0


def test_crosscheck_route_requires_auth(client):
    r = client.get("/api/daily-reports/vat/crosscheck?year=2026&month=5")
    assert r.status_code in (401, 403)


# ---------- verify_filing integration ----------

def test_verify_filing_no_crosscheck_keeps_existing_behavior(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        c3 = result["checks"][2]
        assert c3["passed"] is True  # תקופה נקייה, כרגיל
        assert c3["crosscheck"] == {"present": False}
    finally:
        db.close()


def test_verify_filing_crosscheck_match_passes_explicitly(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        db.add(FilingCrosscheck(organization_id=org_id, period="2026-05", basis="document",
                                books_input_vat=Decimal("90.00"), books_output_vat=Decimal("180.00")))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        c3 = result["checks"][2]
        assert c3["passed"] is True
        assert "הוצלב מול ספרי SUMIT" in c3["details"]
        assert "הוקלד ב-" in c3["details"]
        assert c3["crosscheck"]["present"] is True
        assert c3["crosscheck"]["diff_input_vat"] == 0
        assert result["status"] == "pass"
    finally:
        db.close()


def test_verify_filing_crosscheck_mismatch_fails_with_gap(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        # תיק ההנה"ח מראה תשומות 37,884 לעומת דוח 90 -- פער גדול (ממצא אליהב).
        db.add(FilingCrosscheck(organization_id=org_id, period="2026-05", basis="document",
                                books_input_vat=Decimal("37884.15")))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        c3 = result["checks"][2]
        assert c3["passed"] is False
        assert "פער מול ספרי SUMIT" in c3["details"]
        assert result["status"] == "fail"
    finally:
        db.close()


def test_verify_filing_crosscheck_within_one_shekel_tolerance_passes(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        db.add(FilingCrosscheck(organization_id=org_id, period="2026-05", basis="document",
                                books_input_vat=Decimal("90.90")))  # פער 0.90 <= 1
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        assert result["checks"][2]["passed"] is True
    finally:
        db.close()


def test_verify_filing_crosscheck_wrong_basis_not_matched(fresh_org):
    """רשומת הצלבה עבור בסיס אחר (captured) לא אמורה להתאים לדוח document."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
        db.add(FilingCrosscheck(organization_id=org_id, period="2026-05", basis="captured",
                                books_input_vat=Decimal("90.00")))
        db.commit()
        result = fv.verify_filing(db, org_id, 2026, 5, months=1, basis="document")
        assert result["checks"][2]["crosscheck"] == {"present": False}
    finally:
        db.close()


def test_end_to_end_post_crosscheck_then_verify_flips_check3(client, fresh_org):
    """קריטי: מוודא שהפורמט של period ב-POST זהה בדיוק לזה שבתוך verify_filing
    (report['period']) -- אחרת ההצלבה "נעלמת" בשקט (סיכון advisor)."""
    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        _seed(db, org_id)
    finally:
        db.close()

    r_before = client.get(
        "/api/daily-reports/vat/verify?year=2026&month=5&months=1&basis=document",
        headers=org["headers"],
    )
    assert r_before.json()["checks"][2]["crosscheck"] == {"present": False}

    r_post = client.post("/api/daily-reports/vat/crosscheck", headers=org["headers"], json={
        "year": 2026, "month": 5, "months": 1, "basis": "document",
        "books_input_vat": 90.0, "books_output_vat": 180.0,
    })
    assert r_post.status_code == 200

    r_after = client.get(
        "/api/daily-reports/vat/verify?year=2026&month=5&months=1&basis=document",
        headers=org["headers"],
    )
    c3 = r_after.json()["checks"][2]
    assert c3["passed"] is True
    assert c3["crosscheck"]["present"] is True
