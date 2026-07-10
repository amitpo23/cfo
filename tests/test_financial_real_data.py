"""בדיקות אינטגרציה: AR/AP/מס"ב נשענים על נתונים אמיתיים מהדאטאבייס."""
from datetime import date, timedelta

import pytest


@pytest.fixture(scope="module")
def seeded(owner):
    """זריעת ספק עם פרטי בנק, ספק ללא פרטי בנק, לקוח עם חשבונית פתוחה."""
    from cfo.database import SessionLocal
    from cfo.models import (
        Contact, ContactType, Invoice, InvoiceStatus, Bill, BillStatus,
    )

    org_id = owner["user"]["organization_id"]
    db = SessionLocal()
    try:
        # ספק עם פרטי בנק מלאים
        vendor = Contact(
            organization_id=org_id, contact_type=ContactType.VENDOR,
            name="ספק מבחן בעמ", tax_id="123456782",
            bank_code="12", bank_branch="345", bank_account_number="998877",
        )
        # ספק ללא פרטי בנק
        vendor_no_bank = Contact(
            organization_id=org_id, contact_type=ContactType.VENDOR,
            name="ספק בלי בנק",
        )
        # לקוח
        customer = Contact(
            organization_id=org_id, contact_type=ContactType.CUSTOMER,
            name="לקוח מבחן בעמ", tax_id="555555550",
        )
        db.add_all([vendor, vendor_no_bank, customer])
        db.flush()

        bill = Bill(
            organization_id=org_id, vendor_id=vendor.id,
            bill_number="BILL-100", issue_date=date.today() - timedelta(days=10),
            due_date=date.today() + timedelta(days=5),
            total=1000, paid_amount=0, balance=1000, status=BillStatus.APPROVED,
        )
        bill_no_bank = Bill(
            organization_id=org_id, vendor_id=vendor_no_bank.id,
            bill_number="BILL-200", issue_date=date.today() - timedelta(days=5),
            due_date=date.today() + timedelta(days=10),
            total=500, paid_amount=0, balance=500, status=BillStatus.APPROVED,
        )
        invoice = Invoice(
            organization_id=org_id, contact_id=customer.id,
            invoice_number="INV-100", issue_date=date.today() - timedelta(days=45),
            due_date=date.today() - timedelta(days=15),
            total=2000, paid_amount=0, balance=2000, status=InvoiceStatus.OVERDUE,
        )
        db.add_all([bill, bill_no_bank, invoice])
        db.commit()
        return {
            "org_id": org_id,
            "vendor_id": vendor.id,
            "customer_id": customer.id,
        }
    finally:
        db.close()


# ---------- AR ----------

def test_ar_aging_uses_real_invoice(client, owner, seeded):
    resp = client.get("/api/financial/ar/aging", headers=owner["headers"])
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    names = [c["customer_name"] for c in data["customers"]]
    assert "לקוח מבחן בעמ" in names
    # נתון אמיתי, לא ה-mock הישן
    assert "חברת אלפא בע\"מ" not in names
    assert data["total_receivables"] == 2000


def test_ar_aging_bucket_is_31_60(client, owner, seeded):
    data = client.get("/api/financial/ar/aging", headers=owner["headers"]).json()["data"]
    # חשבונית בת 45 יום -> דלי 31-60
    assert data["buckets"]["days_31_60"] == 2000


def test_ar_collection_forecast_real(client, owner, seeded):
    resp = client.get("/api/financial/ar/collection-forecast", headers=owner["headers"])
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total_outstanding"] == 2000
    assert 0 < data["expected_collection"] <= 2000


# ---------- AP ----------

def test_ap_pending_uses_real_bills(client, owner, seeded):
    resp = client.get("/api/financial/ap/pending", headers=owner["headers"])
    assert resp.status_code == 200, resp.text
    names = [p["vendor_name"] for p in resp.json()["data"]]
    assert "ספק מבחן בעמ" in names
    assert "ספק אלקטרוניקה" not in names  # mock ישן


def test_ap_payment_schedule_real(client, owner, seeded):
    resp = client.get(
        "/api/financial/ap/payment-schedule?available_cash=100000",
        headers=owner["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert "schedule_date" in resp.json()["data"]


# ---------- מס"ב ----------

def test_masav_requires_settings(client, owner, seeded):
    resp = client.post("/api/masav/preview", json={
        "payment_date": date.today().isoformat(),
    }, headers=owner["headers"])
    assert resp.status_code == 400  # אין הגדרות מוסד


def test_masav_full_flow(client, owner, seeded):
    # שמירת הגדרות מוסד
    r = client.post("/api/masav/settings", json={
        "institution_code": "12345678",
        "sending_institution": "54321",
        "institution_name": "העסק שלי",
    }, headers=owner["headers"])
    assert r.status_code == 200, r.text

    # תצוגה מקדימה
    prev = client.post("/api/masav/preview", json={
        "payment_date": date.today().isoformat(),
    }, headers=owner["headers"]).json()
    assert prev["summary"]["payment_count"] == 1   # רק הספק עם פרטי בנק
    assert prev["summary"]["total_amount"] == 1000
    assert len(prev["skipped"]) == 1               # הספק ללא בנק דולג
    assert "חסרים פרטי בנק" in prev["skipped"][0]["reason"]

    # יצירת הקובץ
    gen = client.post("/api/masav/generate", json={
        "payment_date": date.today().isoformat(),
    }, headers=owner["headers"])
    assert gen.status_code == 200, gen.text
    assert "attachment" in gen.headers["content-disposition"]
    lines = gen.content.split(b"\r\n")
    assert lines[-1] == b""
    for line in lines[:-1]:
        assert len(line) == 128
    assert gen.content[:1] == b"K"        # רשומת כותרת
    assert lines[-2] == b"9" * 128        # רשומת תשיעיות


def test_masav_settings_are_org_scoped(client, owner, tenant, seeded):
    # ל-tenant אין הגדרות מס"ב (נשמרו רק ל-owner)
    resp = client.get("/api/masav/settings", headers=tenant["headers"])
    assert resp.status_code == 200
    assert resp.json()["configured"] is False


def test_masav_gather_skips_vendor_with_bad_id_checkdigit(client, owner, seeded):
    """ספק עם ח.פ שנכשל בביקורת הספרה מדולג (לא נכנס לקובץ המס"ב)."""
    from cfo.database import SessionLocal
    from cfo.models import Contact, ContactType, Bill, BillStatus

    org_id = seeded["org_id"]
    db = SessionLocal()
    try:
        bad_vendor = Contact(
            organization_id=org_id, contact_type=ContactType.VENDOR,
            name="ספק ח.פ שגוי", tax_id="123456789",  # נכשל בביקורת הספרה
            bank_code="12", bank_branch="345", bank_account_number="111222",
        )
        db.add(bad_vendor)
        db.flush()
        bad_bill = Bill(
            organization_id=org_id, vendor_id=bad_vendor.id,
            bill_number="BILL-BADID", issue_date=date.today() - timedelta(days=3),
            due_date=date.today() + timedelta(days=20),
            total=300, paid_amount=0, balance=300, status=BillStatus.APPROVED,
        )
        db.add(bad_bill)
        db.commit()
    finally:
        db.close()

    r = client.post("/api/masav/settings", json={
        "institution_code": "12345678",
        "sending_institution": "54321",
        "institution_name": "העסק שלי",
    }, headers=owner["headers"])
    assert r.status_code == 200, r.text

    prev = client.post("/api/masav/preview", json={
        "payment_date": date.today().isoformat(),
    }, headers=owner["headers"]).json()
    reasons = [s["reason"] for s in prev["skipped"] if s.get("vendor") == "ספק ח.פ שגוי"]
    assert reasons, prev["skipped"]
    assert "ביקורת הספרה" in reasons[0]
    names = [p["beneficiary_name"] for p in prev["payments"]]
    assert "ספק ח.פ שגוי" not in names


def test_masav_gather_skips_vendor_with_invalid_bank_code(client, owner, seeded):
    """ספק עם קוד בנק שאינו ברשימת חברי מס"ב מדולג (לא נכנס לקובץ המס"ב)."""
    from cfo.database import SessionLocal
    from cfo.models import Contact, ContactType, Bill, BillStatus

    org_id = seeded["org_id"]
    db = SessionLocal()
    try:
        bad_vendor = Contact(
            organization_id=org_id, contact_type=ContactType.VENDOR,
            name="ספק קוד בנק שגוי", tax_id="123456782",
            bank_code="77", bank_branch="345", bank_account_number="333444",  # 77 אינו קוד בנק פעיל
        )
        db.add(bad_vendor)
        db.flush()
        bad_bill = Bill(
            organization_id=org_id, vendor_id=bad_vendor.id,
            bill_number="BILL-BADBANK", issue_date=date.today() - timedelta(days=3),
            due_date=date.today() + timedelta(days=20),
            total=400, paid_amount=0, balance=400, status=BillStatus.APPROVED,
        )
        db.add(bad_bill)
        db.commit()
    finally:
        db.close()

    r = client.post("/api/masav/settings", json={
        "institution_code": "12345678",
        "sending_institution": "54321",
        "institution_name": "העסק שלי",
    }, headers=owner["headers"])
    assert r.status_code == 200, r.text

    prev = client.post("/api/masav/preview", json={
        "payment_date": date.today().isoformat(),
    }, headers=owner["headers"]).json()
    reasons = [s["reason"] for s in prev["skipped"] if s.get("vendor") == "ספק קוד בנק שגוי"]
    assert reasons, prev["skipped"]
    assert "קוד בנק" in reasons[0]
    names = [p["beneficiary_name"] for p in prev["payments"]]
    assert "ספק קוד בנק שגוי" not in names


def test_financial_routes_org_scoped_no_crash(client, owner, seeded):
    """כל ה-routes הפיננסיים מקבלים org_id מה-JWT ולא קורסים (NameError)."""
    crashed = []
    for path in [
        "/api/financial/budget/alerts", "/api/financial/budget/vs-actual",
        "/api/financial/kpis", "/api/financial/kpis/executive-summary",
        "/api/financial/costs/break-even", "/api/financial/costs/breakdown",
        "/api/financial/tax/calendar", "/api/financial/tax/planning",
        "/api/financial/ai/risks", "/api/financial/reports/templates",
    ]:
        try:
            r = client.get(path, headers=owner["headers"])
            if r.status_code == 500:
                crashed.append((path, r.text[:120]))
        except Exception as exc:  # TestClient re-raises server exceptions
            crashed.append((path, f"{type(exc).__name__}: {exc}"))
    # ודא שהעריכה הקבוצתית של org scoping לא הזריקה NameError על org_id
    assert not any("NameError" in msg or "org_id" in msg for _, msg in crashed), crashed
