"""שער כפילויות (duplicate_gate) — הכפילות שכמעט גרמה לכפל-ספירה של ₪150K
(מנה 4 חפפה 14 שורות למנה 2 הסגורה) והבאג הקודם (הזנה ×4 = ₪9.6K ניפוח)."""
from datetime import date
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Bill, BillStatus, Contact, ContactType, Expense
from cfo.services import duplicate_gate as dg


def _mk_expense(db, org_id, **overrides):
    defaults = dict(
        organization_id=org_id, source="manual", supplier_name="ספק",
        amount=Decimal("1000"), vat_amount=Decimal("0"), total=Decimal("1000"),
        expense_date=date(2026, 5, 10), status="pending",
    )
    defaults.update(overrides)
    e = Expense(**defaults)
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


# ---------- expense_fingerprint ----------

def test_fingerprint_primary_key_when_tax_id_and_reference_present():
    fp1 = dg.expense_fingerprint("514012345", "INV-1234", 1000, date(2026, 5, 10))
    fp2 = dg.expense_fingerprint("514-012-345", "inv 1234", 1000, date(2026, 5, 10))
    assert fp1["tier"] == "primary"
    assert fp2["tier"] == "primary"
    assert fp1["key"] == fp2["key"]  # normalized identically despite formatting


def test_fingerprint_falls_back_to_second_tier_without_tax_id_or_reference():
    fp = dg.expense_fingerprint(None, None, 1000, date(2026, 5, 10))
    assert fp["tier"] == "fallback"


def test_fingerprint_different_tax_id_gives_different_primary_key():
    fp1 = dg.expense_fingerprint("514012345", "INV-1", 100, date(2026, 5, 10))
    fp2 = dg.expense_fingerprint("999999999", "INV-1", 100, date(2026, 5, 10))
    assert fp1["key"] != fp2["key"]


# ---------- find_duplicate_candidates ----------

def test_same_tax_id_and_reference_twice_is_high_confidence(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_expense(
            db, org_id, supplier_name="ספק א", supplier_tax_id="514012345",
            invoice_number="INV-777", amount=Decimal("9600"), total=Decimal("9600"),
            expense_date=date(2026, 5, 1),
        )
        candidates = dg.find_duplicate_candidates(
            db, org_id,
            supplier_tax_id="514012345", reference="INV-777",
            amount=9600, doc_date=date(2026, 5, 3),
        )
        assert any(c["confidence"] == "HIGH" for c in candidates)
        high = [c for c in candidates if c["confidence"] == "HIGH"][0]
        assert high["source"] == "expense"
    finally:
        db.close()


def test_same_amount_same_day_different_reference_is_suspect_not_high(fresh_org):
    """שתי נסיעות מונית זהות באותו יום: לגיטימי, לא HIGH — טעון הכרעת אדם."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_expense(
            db, org_id, supplier_name="מונית", supplier_tax_id=None,
            invoice_number="RIDE-1", amount=Decimal("45"), total=Decimal("45"),
            expense_date=date(2026, 5, 10),
        )
        candidates = dg.find_duplicate_candidates(
            db, org_id,
            supplier_tax_id=None, reference="RIDE-2",
            amount=45, doc_date=date(2026, 5, 10),
        )
        assert not any(c["confidence"] == "HIGH" for c in candidates)
        assert any(c["confidence"] == "SUSPECT" for c in candidates)
    finally:
        db.close()


def test_two_legitimate_records_different_amount_are_clean(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_expense(
            db, org_id, supplier_name="ספק ב", supplier_tax_id="600111222",
            invoice_number="INV-A", amount=Decimal("500"), total=Decimal("500"),
            expense_date=date(2026, 5, 5),
        )
        candidates = dg.find_duplicate_candidates(
            db, org_id,
            supplier_tax_id="600111222", reference="INV-B",
            amount=1500, doc_date=date(2026, 6, 20),
        )
        assert candidates == []
    finally:
        db.close()


def test_exclude_id_skips_self_match(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        e = _mk_expense(
            db, org_id, supplier_name="ספק ג", supplier_tax_id="700333444",
            invoice_number="INV-SELF", amount=Decimal("300"), total=Decimal("300"),
            expense_date=date(2026, 5, 15),
        )
        candidates = dg.find_duplicate_candidates(
            db, org_id,
            supplier_tax_id="700333444", reference="INV-SELF",
            amount=300, doc_date=date(2026, 5, 15),
            exclude_id=e.id, exclude_source="expense",
        )
        assert candidates == []
    finally:
        db.close()


def test_exclude_id_is_source_scoped_does_not_hide_cross_table_duplicate(fresh_org):
    """exclude_id=N בלי exclude_source תואם, או עם exclude_source שגוי, לא אמור
    לסנן שורה מהטבלה השנייה — אחרת כפילות אמיתית חוצת-טבלה (Bill/Expense עם
    אותו id במקרה) הייתה מתפספסת בטעות."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        e = _mk_expense(
            db, org_id, supplier_name="ספק ד", supplier_tax_id="800555666",
            invoice_number="INV-CROSS", amount=Decimal("400"), total=Decimal("400"),
            expense_date=date(2026, 5, 16),
        )
        # exclude_source="bill" (not "expense") must NOT hide this expense row
        candidates = dg.find_duplicate_candidates(
            db, org_id,
            supplier_tax_id="800555666", reference="INV-CROSS",
            amount=400, doc_date=date(2026, 5, 16),
            exclude_id=e.id, exclude_source="bill",
        )
        assert any(c["confidence"] == "HIGH" and c["source"] == "expense" for c in candidates)
    finally:
        db.close()


def test_bill_side_duplicate_matched_via_vendor_tax_id(fresh_org):
    """כיסוי לצד ה-Bill (AP): ה-tax_id של Bill מגיע דרך vendor (Contact),
    לא שדה ישיר על ה-Bill עצמו — הנתיב העקיף הזה חייב לעבוד נכון."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        vendor = Contact(
            organization_id=org_id, name="ספק ח.פ נוצרי", contact_type=ContactType.VENDOR,
            tax_id="514777888",
        )
        db.add(vendor)
        db.flush()
        db.add(Bill(
            organization_id=org_id, source="manual", vendor_id=vendor.id,
            bill_number="BILL-42", issue_date=date(2026, 5, 12), status=BillStatus.APPROVED,
            subtotal=Decimal("2000"), tax=Decimal("360"), total=Decimal("2360"),
        ))
        db.commit()

        candidates = dg.find_duplicate_candidates(
            db, org_id,
            supplier_tax_id="514777888", reference="BILL-42",
            amount=2360, doc_date=date(2026, 5, 14),
        )
        high = [c for c in candidates if c["confidence"] == "HIGH"]
        assert len(high) == 1
        assert high[0]["source"] == "bill"
        assert high[0]["supplier_name"] == "ספק ח.פ נוצרי"
    finally:
        db.close()


def test_bill_excluded_by_matching_exclude_source_not_by_id_alone(fresh_org):
    """Bill#N נכלל כמועמד כשמחריגים expense#N (source שונה) — ה-exclude
    ממוקד-מקור, לא רק לפי id גולמי."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        vendor = Contact(
            organization_id=org_id, name="ספק לבדיקת החרגה", contact_type=ContactType.VENDOR,
            tax_id="611222333",
        )
        db.add(vendor)
        db.flush()
        bill = Bill(
            organization_id=org_id, source="manual", vendor_id=vendor.id,
            bill_number="BILL-EXC", issue_date=date(2026, 5, 12), status=BillStatus.APPROVED,
            subtotal=Decimal("800"), tax=Decimal("144"), total=Decimal("944"),
        )
        db.add(bill)
        db.commit()
        db.refresh(bill)

        # מחריגים expense עם אותו id מספרי — אסור שזה יסתיר את ה-Bill
        candidates = dg.find_duplicate_candidates(
            db, org_id,
            supplier_tax_id="611222333", reference="BILL-EXC",
            amount=944, doc_date=date(2026, 5, 12),
            exclude_id=bill.id, exclude_source="expense",
        )
        assert any(c["confidence"] == "HIGH" and c["source"] == "bill" for c in candidates)
    finally:
        db.close()


def test_batch_overlap_scenario_150k(fresh_org):
    """סימולציה: מנה 4 חפפה 14 שורות למנה 2 הסגורה — אותו ח.פ+אסמכתא, סכום גדול."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_expense(
            db, org_id, supplier_name="ספק ענק", supplier_tax_id="512345678",
            invoice_number="BATCH2-ROW14", amount=Decimal("150000"), total=Decimal("150000"),
            expense_date=date(2026, 4, 20), status="filed",
        )
        candidates = dg.find_duplicate_candidates(
            db, org_id,
            supplier_tax_id="512345678", reference="BATCH2-ROW14",
            amount=150000, doc_date=date(2026, 5, 18),  # more than 3 days later
        )
        high = [c for c in candidates if c["confidence"] == "HIGH"]
        assert len(high) == 1  # caught even though dates are far apart, via primary key
    finally:
        db.close()
