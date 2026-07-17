"""בדיקות רמת-route ל-POST /api/masav/preview — ולידציית שפיות מינימלית
לפני שידור (בנק/סניף/חשבון תקינים, אין סך שלילי) לפי מרכז הידע:
מס"ב לא מדווחת כשל על פרטי בנק שגויים, וקובץ עם סך שלילי ללקוח לא ישודר."""
from datetime import date
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Bill, BillStatus, Contact, ContactType


def _make_vendor(db, org_id, **kw):
    base = dict(
        organization_id=org_id, contact_type=ContactType.VENDOR, name="ספק בדיקה",
        tax_id="789621349",  # ח.פ תקין (ביקורת ספרה עוברת — ר' test_masav.py)
        bank_code="12", bank_branch="345", bank_account_number="123456",
    )
    base.update(kw)
    vendor = Contact(**base)
    db.add(vendor)
    db.flush()
    return vendor


def _make_bill(db, org_id, vendor_id, balance="1000.00", **kw):
    base = dict(
        organization_id=org_id, vendor_id=vendor_id, bill_number="B-1",
        issue_date=date(2026, 6, 1), status=BillStatus.APPROVED,
        subtotal=Decimal("850"), tax=Decimal("150"), total=Decimal("1000"),
        paid_amount=Decimal("0"), balance=Decimal(balance),
    )
    base.update(kw)
    bill = Bill(**base)
    db.add(bill)
    db.commit()
    return bill


def _preview(client, org, settings_override=True):
    payload = {"payment_date": "2026-06-15"}
    if settings_override:
        payload["settings"] = {
            "institution_code": "12345678",
            "sending_institution": "54321",
            "institution_name": "משרד בדיקה",
        }
    return client.post("/api/masav/preview", headers=org["headers"], json=payload)


def test_valid_bill_included_as_payment(client, fresh_org):
    org = fresh_org()
    db = SessionLocal()
    try:
        vendor = _make_vendor(db, org["org_id"])
        _make_bill(db, org["org_id"], vendor.id)
    finally:
        db.close()

    r = _preview(client, org)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["payment_count"] == 1
    assert body["skipped"] == []


def test_invalid_branch_length_flagged_as_warning(client, fresh_org):
    org = fresh_org()
    db = SessionLocal()
    try:
        vendor = _make_vendor(db, org["org_id"], bank_branch="1234")  # 4 ספרות — לא תקין
        _make_bill(db, org["org_id"], vendor.id)
    finally:
        db.close()

    r = _preview(client, org)
    body = r.json()
    assert body["summary"]["payment_count"] == 0
    assert len(body["skipped"]) == 1
    assert "מספר סניף" in body["skipped"][0]["reason"]
    assert "1-3 ספרות" in body["skipped"][0]["reason"]


def test_invalid_account_too_short_flagged_as_warning(client, fresh_org):
    org = fresh_org()
    db = SessionLocal()
    try:
        vendor = _make_vendor(db, org["org_id"], bank_account_number="12")  # קצר מדי
        _make_bill(db, org["org_id"], vendor.id)
    finally:
        db.close()

    r = _preview(client, org)
    body = r.json()
    assert body["summary"]["payment_count"] == 0
    assert "מספר חשבון" in body["skipped"][0]["reason"]
    assert "4-9 ספרות" in body["skipped"][0]["reason"]


def test_invalid_account_too_long_flagged_as_warning(client, fresh_org):
    org = fresh_org()
    db = SessionLocal()
    try:
        vendor = _make_vendor(db, org["org_id"], bank_account_number="1234567890")  # 10 ספרות
        _make_bill(db, org["org_id"], vendor.id)
    finally:
        db.close()

    r = _preview(client, org)
    body = r.json()
    assert body["summary"]["payment_count"] == 0
    assert "מספר חשבון" in body["skipped"][0]["reason"]


def test_unknown_bank_code_flagged_as_warning(client, fresh_org):
    org = fresh_org()
    db = SessionLocal()
    try:
        vendor = _make_vendor(db, org["org_id"], bank_code="77")  # לא ברשימת חברי מס"ב
        _make_bill(db, org["org_id"], vendor.id)
    finally:
        db.close()

    r = _preview(client, org)
    body = r.json()
    assert body["summary"]["payment_count"] == 0
    assert "אינו ברשימת חברי מס\"ב" in body["skipped"][0]["reason"]


def test_negative_balance_flagged_explicit_warning(client, fresh_org):
    """יתרת חשבונית שלילית (למשל אחרי זיכוי) — מס"ב לא תשדר סך שלילי, אזהרה
    מפורשת ולא היעלמות שקטה מהתצוגה המקדימה."""
    org = fresh_org()
    db = SessionLocal()
    try:
        vendor = _make_vendor(db, org["org_id"])
        _make_bill(db, org["org_id"], vendor.id, balance="-50.00")
    finally:
        db.close()

    r = _preview(client, org)
    body = r.json()
    assert body["summary"]["payment_count"] == 0
    assert len(body["skipped"]) == 1
    assert "מס\"ב לא תשדר סך שלילי" in body["skipped"][0]["reason"]


def test_zero_balance_bill_silently_excluded_from_default_sweep(client, fresh_org):
    """חשבונית ששולמה במלואה (balance=0) לא אמורה להופיע בסריקה הכללית (בלי
    bill_ids) — לא תשלום ולא אזהרה, כמו ההתנהגות הקודמת (רעש על כל חשבונית
    סגורה בכל תצוגה מקדימה)."""
    org = fresh_org()
    db = SessionLocal()
    try:
        vendor = _make_vendor(db, org["org_id"])
        _make_bill(db, org["org_id"], vendor.id, balance="0")
    finally:
        db.close()

    r = _preview(client, org)
    body = r.json()
    assert body["summary"]["payment_count"] == 0
    assert body["skipped"] == []


def test_zero_balance_bill_explicitly_selected_flagged_not_silently_dropped(client, fresh_org):
    """כשהמשתמש בוחר חשבונית ספציפית (bill_ids) שיתרתה אפס -- אסור שתיעלם
    בשקט: מס"ב לא תשדר סך אפס, ולכן אזהרה מפורשת בתצוגה המקדימה."""
    org = fresh_org()
    db = SessionLocal()
    try:
        vendor = _make_vendor(db, org["org_id"])
        bill = _make_bill(db, org["org_id"], vendor.id, balance="0")
        bill_id = bill.id
    finally:
        db.close()

    payload = {
        "payment_date": "2026-06-15", "bill_ids": [bill_id],
        "settings": {
            "institution_code": "12345678", "sending_institution": "54321",
            "institution_name": "משרד בדיקה",
        },
    }
    r = client.post("/api/masav/preview", headers=org["headers"], json=payload)
    body = r.json()
    assert body["summary"]["payment_count"] == 0
    assert len(body["skipped"]) == 1
    assert "מס\"ב לא תשדר סך שלילי או אפס" in body["skipped"][0]["reason"]


def test_multiple_bills_mixed_valid_and_invalid(client, fresh_org):
    org = fresh_org()
    db = SessionLocal()
    try:
        good_vendor = _make_vendor(db, org["org_id"], external_id="v-good")
        _make_bill(db, org["org_id"], good_vendor.id, bill_number="GOOD-1")

        bad_vendor = _make_vendor(db, org["org_id"], external_id="v-bad", bank_branch="0000")
        _make_bill(db, org["org_id"], bad_vendor.id, bill_number="BAD-1")
    finally:
        db.close()

    r = _preview(client, org)
    body = r.json()
    assert body["summary"]["payment_count"] == 1
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["bill"] == "BAD-1"
