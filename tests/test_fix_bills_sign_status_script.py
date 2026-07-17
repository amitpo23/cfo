"""scripts/fix_bills_sign_status.py — תיקון נתונים אידמפוטנטי ל-bills ישנים
שסונכרנו בסימן/סטטוס הקודם (total שלילי, type 15 לא-PAID).
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def _make_old_bills(db, org_id):
    from cfo.models import Contact, ContactType, Bill, BillStatus

    vend = Contact(organization_id=org_id, contact_type=ContactType.VENDOR, name="ספק")
    db.add(vend)
    db.flush()

    # type 15 שנשמר בסימן הישן (שלילי) ובסטטוס RECEIVED (לא PAID)
    b15 = Bill(
        organization_id=org_id, vendor_id=vend.id, bill_number="B15",
        external_id="d15", issue_date=date(2026, 5, 10),
        subtotal=-52.10, tax=-9.37, total=-61.47, paid_amount=0, balance=-61.47,
        status=BillStatus.RECEIVED, raw_data={"document_type": "15"},
        payload_hash="oldhash15",
    )
    # type 16 שנשמר בסימן הישן (שלילי), נשאר RECEIVED
    b16 = Bill(
        organization_id=org_id, vendor_id=vend.id, bill_number="B16",
        external_id="d16", issue_date=date(2026, 5, 10),
        subtotal=-200.0, tax=-36.0, total=-236.0, paid_amount=0, balance=-236.0,
        status=BillStatus.RECEIVED, raw_data={"document_type": "16"},
        payload_hash="oldhash16",
    )
    # bill שכבר תקין (positive, לא type 15) — לא אמור להשתנות
    b_ok = Bill(
        organization_id=org_id, vendor_id=vend.id, bill_number="BOK",
        external_id="dok", issue_date=date(2026, 5, 10),
        subtotal=100.0, tax=18.0, total=118.0, paid_amount=0, balance=118.0,
        status=BillStatus.APPROVED, raw_data={"document_type": "16"},
        payload_hash="okhash",
    )
    db.add_all([b15, b16, b_ok])
    db.commit()
    return b15.id, b16.id, b_ok.id


def test_apply_fixes_sign_and_status(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Bill, BillStatus
    from fix_bills_sign_status import apply_bill_fixes

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        b15_id, b16_id, bok_id = _make_old_bills(db, org_id)

        counts = apply_bill_fixes(db, org_id=org_id)
        db.commit()

        assert counts["sign_fixed"] == 2   # b15, b16 (b_ok already positive)
        assert counts["status_fixed"] == 1  # b15 only (type 15)

        b15 = db.get(Bill, b15_id)
        assert float(b15.total) == 61.47
        assert float(b15.subtotal) == 52.10
        assert float(b15.tax) == 9.37
        assert b15.status == BillStatus.PAID
        assert float(b15.paid_amount) == 61.47
        assert float(b15.balance) == 0.0
        assert b15.payload_hash is None

        b16 = db.get(Bill, b16_id)
        assert float(b16.total) == 236.0
        assert float(b16.balance) == 236.0
        assert b16.status == BillStatus.RECEIVED  # type 16 — לא הופך ל-PAID
        assert b16.payload_hash is None

        b_ok = db.get(Bill, bok_id)
        assert float(b_ok.total) == 118.0  # לא נגע — כבר היה חיובי
        assert b_ok.payload_hash == "okhash"
    finally:
        db.close()


def test_apply_fixes_is_idempotent(fresh_org):
    """הרצה שנייה על bills שכבר תוקנו לא משנה דבר."""
    from cfo.database import SessionLocal
    from cfo.models import Bill
    from fix_bills_sign_status import apply_bill_fixes

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        b15_id, b16_id, _ = _make_old_bills(db, org_id)
        apply_bill_fixes(db, org_id=org_id)
        db.commit()

        b15_after_first = db.get(Bill, b15_id)
        totals_first = (float(b15_after_first.total), float(b15_after_first.balance))

        counts_second = apply_bill_fixes(db, org_id=org_id)
        db.commit()

        assert counts_second == {"sign_fixed": 0, "status_fixed": 0}
        b15_after_second = db.get(Bill, b15_id)
        assert (float(b15_after_second.total), float(b15_after_second.balance)) == totals_first
    finally:
        db.close()


def test_plan_does_not_write(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Bill
    from fix_bills_sign_status import plan_bill_fixes

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        b15_id, _, _ = _make_old_bills(db, org_id)
        plan = plan_bill_fixes(db, org_id=org_id)
        assert len(plan["negative_bills"]) == 2
        assert len(plan["type15_bills"]) == 1

        db.rollback()
        b15 = db.get(Bill, b15_id)
        assert float(b15.total) == -61.47  # לא נכתב דבר — עדיין בסימן הישן
    finally:
        db.close()
