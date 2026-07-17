"""Tests for the cross-source synthesis engine (SUMIT books + bank)."""
from datetime import date

import pytest

from cfo.services.financial_synthesis import build_synthesis, link_payments, PaymentLite
from cfo.services.bank_reconciliation import BankTxnLite, DocLite


def _actions_by_type(report):
    out = {}
    for a in report["required_actions"]:
        out.setdefault(a["type"], []).append(a)
    return out


def test_unmatched_outflow_becomes_file_expense_action():
    bank = [BankTxnLite(1, -300.0, date(2026, 6, 5), "ספק לא ידוע")]
    report = build_synthesis(bank, [], [], [])
    by = _actions_by_type(report)
    assert "file_expense" in by
    assert by["file_expense"][0]["amount"] == 300.0


def test_unmatched_inflow_becomes_record_income_action():
    bank = [BankTxnLite(1, 900.0, date(2026, 6, 5), "תקבול")]
    report = build_synthesis(bank, [], [], [])
    by = _actions_by_type(report)
    assert "record_income" in by


def test_matched_bank_to_invoice_produces_no_action():
    bank = [BankTxnLite(1, 1170.0, date(2026, 6, 6), "אקמה")]
    invoices = [DocLite("i1", "invoice", 1170.0, date(2026, 6, 6), "אקמה")]
    report = build_synthesis(bank, invoices, [], [])
    assert report["reconciliation"]["matched"] == 1
    # The matched invoice should not appear as uncollected.
    assert "collect_receivable" not in _actions_by_type(report)


def test_unpaid_invoice_without_bank_match_is_uncollected():
    invoices = [DocLite("i2", "invoice", 500.0, date(2026, 5, 1), "בטא")]
    report = build_synthesis([], invoices, [], [], unpaid_invoice_ids={"i2"})
    by = _actions_by_type(report)
    assert "collect_receivable" in by


def test_vat_position():
    report = build_synthesis([], [], [], [], output_vat=1800.0, input_vat=500.0)
    vat = report["vat_summary"]
    assert vat["output_vat"] == 1800.0
    assert vat["input_vat"] == 500.0
    assert vat["net_vat"] == 1300.0
    assert vat["direction"] == "לתשלום"


def test_vat_refund_direction():
    report = build_synthesis([], [], [], [], output_vat=100.0, input_vat=400.0)
    assert report["vat_summary"]["net_vat"] == -300.0
    assert report["vat_summary"]["direction"] == "להחזר"


def test_link_payment_to_invoice():
    pays = [PaymentLite("p1", 1170.0, date(2026, 6, 7), name="אקמה")]
    invoices = [DocLite("i1", "invoice", 1170.0, date(2026, 6, 6), "אקמה"),
                DocLite("i2", "invoice", 500.0, date(2026, 5, 1), "בטא")]
    res = link_payments(pays, invoices, [])
    assert res["linked_count"] == 1
    assert res["links"][0]["entity_type"] == "invoice"
    assert res["links"][0]["entity_id"] == "i1"


def test_payment_amount_mismatch_not_linked():
    pays = [PaymentLite("p1", 999.0, date(2026, 6, 7), name="אקמה")]
    invoices = [DocLite("i1", "invoice", 1170.0, date(2026, 6, 6), "אקמה")]
    res = link_payments(pays, invoices, [])
    assert res["linked_count"] == 0
    assert res["unlinked"] == ["p1"]


# ---------------------------------------------------------------------- #
# select_vat_documents — ממצאי אודיט אליהב (2026-07-13):
# 1) טיוטות-אפס לא נכללות ב-inputs (מזהמות קובץ PCN רגולטורי כשורות L באפס).
# 3) ח.פ ספק ב-Bill מגיע מ-vendor.tax_id כשקיים.
# ---------------------------------------------------------------------- #
@pytest.fixture
def org_with_zero_draft_and_real_bill(fresh_org):
    """הוצאה בת-אפס שכבר סומנה status='filed' ב-DB (סריקת קבלה ריקה שהתויקה
    בטעות/בלי סכום) לצד מסמך תשומות אמיתי — לוודא שהאפס לא מזהם את הבחירה."""
    from cfo.database import SessionLocal
    from cfo.models import Contact, ContactType, Bill, BillStatus, Expense

    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        vend = Contact(organization_id=org_id, contact_type=ContactType.VENDOR,
                       name="ספק אמיתי", tax_id="512345678")
        db.add(vend); db.flush()
        db.add(Bill(organization_id=org_id, vendor_id=vend.id, bill_number="REAL-1",
                    issue_date=date(2026, 5, 10), status=BillStatus.RECEIVED,
                    subtotal=100, tax=18, total=118, paid_amount=0, balance=118))
        # טיוטת-אפס: צילום קבלה שסונכרן בסכום 0/0 — status="filed" כדי לעבור את
        # פילטר הסטטוס הרגיל (expense_counts) ולהוכיח שהסינון החדש הוא לפי סכום.
        db.add(Expense(organization_id=org_id, external_id="DRAFT-0", source="sumit",
                       supplier_name="קבלה לא מתויקת", amount=0, vat_amount=0, total=0,
                       expense_date=date(2026, 5, 15), status="filed"))
        db.commit()
        return {"org_id": org_id}
    finally:
        db.close()


def test_zero_value_draft_excluded_from_inputs(org_with_zero_draft_and_real_bill):
    """מסמך תשומות עם subtotal==0 וגם vat==0 לא נכלל ב-inputs — לא מזהם קובץ PCN."""
    from cfo.database import SessionLocal
    from cfo.services.financial_synthesis import select_vat_documents

    db = SessionLocal()
    try:
        sel = select_vat_documents(db, org_with_zero_draft_and_real_bill["org_id"],
                                   start=date(2026, 5, 1), end=date(2026, 5, 31))
        numbers = [r["number"] for r in sel["inputs"]]
        assert "REAL-1" in numbers
        assert not any(r["subtotal"] == 0 and r["vat"] == 0 for r in sel["inputs"])
        assert len(sel["inputs"]) == 1
    finally:
        db.close()


def test_zero_value_draft_still_counted_as_pending_in_verification(
        org_with_zero_draft_and_real_bill):
    """הטיוטה-אפס מוחרגת מה-inputs אך עדיין נספרת ב-pending_drafts של האימות
    המשולש — לא לאבד את האזהרה על מה שממתין לתיוק."""
    from cfo.database import SessionLocal
    from cfo.services import filing_verification as fv

    db = SessionLocal()
    try:
        n = fv._pending_drafts(db, org_with_zero_draft_and_real_bill["org_id"],
                              date(2026, 5, 1), date(2026, 5, 31))
        assert n == 1
    finally:
        db.close()


def test_bill_vat_id_from_vendor_contact_tax_id(org_with_zero_draft_and_real_bill):
    """ל-bill עם ספק בעל tax_id — vat_id נושא אותו, לא ריק/אפסים."""
    from cfo.database import SessionLocal
    from cfo.services.financial_synthesis import select_vat_documents

    db = SessionLocal()
    try:
        sel = select_vat_documents(db, org_with_zero_draft_and_real_bill["org_id"],
                                   start=date(2026, 5, 1), end=date(2026, 5, 31))
        real = next(r for r in sel["inputs"] if r["number"] == "REAL-1")
        assert real["vat_id"] == "512345678"
    finally:
        db.close()


def test_bill_without_vendor_tax_id_leaves_vat_id_blank(fresh_org):
    """ספק בלי tax_id (או בלי vendor כלל) — vat_id נשאר ריק (None), לא מומצא."""
    from cfo.database import SessionLocal
    from cfo.models import Bill, BillStatus
    from cfo.services.financial_synthesis import select_vat_documents

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Bill(organization_id=org_id, bill_number="NOVENDOR-1",
                    issue_date=date(2026, 5, 11), status=BillStatus.RECEIVED,
                    subtotal=50, tax=9, total=59, paid_amount=0, balance=59))
        db.commit()
        sel = select_vat_documents(db, org_id, start=date(2026, 5, 1), end=date(2026, 5, 31))
        row = next(r for r in sel["inputs"] if r["number"] == "NOVENDOR-1")
        assert not row["vat_id"]
    finally:
        db.close()
