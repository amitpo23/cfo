"""AP aging — הפער שהתבקש במפורש: "חשבוניות לספקים שלא שילמתי, ואין
לזה תנועה בבנק".

**הממצא (18/08/2026).** ל-AR (לקוחות חייבים לי) יש `get_ar_aging` עם
דלגים (0-30/31-60/61-90/90+) דרך `DashboardService.get_ar_aging()`.
ל-AP (אני חייב לספקים) יש רק `get_ap_bills` — רשימה שטוחה בלי דלגים,
ו-`ARAPAgingService.ap_aging_report()` שיש בו דלגים אך **אינו חשוף
כלי-מושקו כלל**. באף אחד מהשניים אין את מה שהבעלים ביקש: הבחנה בין
חשבון ספק פתוח **עם** תנועת בנק תואמת (כנראה עיכוב סנכרון — הכסף כבר
יצא) לבין חשבון ספק פתוח **בלי** שום תנועת בנק (סיכון אמיתי — צריך
לשלם, או שנשכח).

**התיקון:** `DashboardService.get_ap_aging()` מראה זהה ל-`get_ar_aging()`
(dict שטוח, `bucket_0_30`...`bucket_90_plus`, `total`, `count`,
`bills`), פר-חשבון עם `bank_movement_seen: bool` — נגזר מ-
`BankTransaction.matched_entity_type='bill'` (`is_reconciled`),
בלי ליצור Payment וללא כתיבה (אותו מנוע כמו `get_bank_reconciliation`
שנבנה אתמול — קריאה בלבד).
"""
import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import BankTransaction, Bill, BillStatus, Contact, ContactType
from cfo.services.ai_chat_tools import TOOLS
from cfo.services.dashboard_service import DashboardService


def _mk_vendor(db, org_id, name="ספק בדיקה"):
    v = Contact(organization_id=org_id, name=name, contact_type=ContactType.VENDOR)
    db.add(v); db.flush()
    return v


def test_the_tool_is_registered():
    """הפער עצמו: מנוע הדלגים קיים, אבל למושקו לא היה אליו כלי."""
    assert "get_ap_aging" in TOOLS


def test_buckets_mirror_the_ar_shape(fresh_org):
    """אותה תבנית בדיוק כמו get_ar_aging — לא מבנה שני שמושקו צריך
    ללמוד בנפרד."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    vendor = _mk_vendor(db, org_id)
    db.add(Bill(
        organization_id=org_id, vendor_id=vendor.id, bill_number="B1",
        total=Decimal("500"), balance=Decimal("500"), status=BillStatus.RECEIVED,
        issue_date=date.today() - timedelta(days=75),
        due_date=date.today() - timedelta(days=45),  # days_overdue נגזר מכאן
    ))
    db.commit()

    result = asyncio.run(TOOLS["get_ap_aging"].fn(db, org_id))

    assert result["bucket_31_60"] == 500.0
    assert result["total"] == 500.0
    assert result["count"] == 1


def test_a_bill_with_a_matched_bank_transaction_is_flagged(fresh_org):
    """**הלב.** תנועת בנק תואמת קיימת — הכסף כנראה כבר יצא, זה עיכוב
    סנכרון ולא סיכון תשלום. הבעלים לא צריך לפעול על זה."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    vendor = _mk_vendor(db, org_id)
    bill = Bill(
        organization_id=org_id, vendor_id=vendor.id, bill_number="B2",
        total=Decimal("300"), balance=Decimal("300"), status=BillStatus.RECEIVED,
        issue_date=date.today() - timedelta(days=20),
        due_date=date.today() - timedelta(days=5),
    )
    db.add(bill); db.flush()
    db.add(BankTransaction(
        organization_id=org_id, amount=Decimal("-300"),
        transaction_date=date.today() - timedelta(days=3),
        is_reconciled=True, matched_entity_type="bill", matched_entity_id=bill.id,
    ))
    db.commit()

    result = asyncio.run(TOOLS["get_ap_aging"].fn(db, org_id))
    flagged = next(b for b in result["bills"] if b["id"] == bill.id)

    assert flagged["bank_movement_seen"] is True


def test_a_bill_without_any_bank_transaction_is_a_real_risk(fresh_org):
    """שער נגדי, וזה המקרה שהבעלים ביקש לתפוס: אין תנועת בנק כלל —
    זה מה שדורש תשומת לב, לא מה שהותאם."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    vendor = _mk_vendor(db, org_id)
    db.add(Bill(
        organization_id=org_id, vendor_id=vendor.id, bill_number="B3",
        total=Decimal("800"), balance=Decimal("800"), status=BillStatus.OVERDUE,
        issue_date=date.today() - timedelta(days=100),
        due_date=date.today() - timedelta(days=70),
    ))
    db.commit()

    result = asyncio.run(TOOLS["get_ap_aging"].fn(db, org_id))
    flagged = next(b for b in result["bills"] if b["balance"] == 800.0)

    assert flagged["bank_movement_seen"] is False


def test_paid_bills_are_excluded(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    vendor = _mk_vendor(db, org_id)
    db.add(Bill(
        organization_id=org_id, vendor_id=vendor.id, bill_number="B4",
        total=Decimal("100"), balance=Decimal("0"), status=BillStatus.PAID,
        issue_date=date.today() - timedelta(days=200),
    ))
    db.commit()

    result = asyncio.run(TOOLS["get_ap_aging"].fn(db, org_id))

    assert result["count"] == 0
    assert result["total"] == 0.0


def test_org_scoped(fresh_org):
    """שער נגדי: לא רואים חשבונות ספק של ארגון אחר."""
    db = SessionLocal()
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    vendor = _mk_vendor(db, org_b)
    db.add(Bill(
        organization_id=org_b, vendor_id=vendor.id, bill_number="X",
        total=Decimal("999"), balance=Decimal("999"), status=BillStatus.RECEIVED,
        issue_date=date.today() - timedelta(days=10),
    ))
    db.commit()

    result = asyncio.run(TOOLS["get_ap_aging"].fn(db, org_a))

    assert result["total"] == 0.0


def test_dashboard_service_method_matches_ar_aging_shape(fresh_org):
    """שער ישיר על ה-service, לא רק על הכלי — כדי שהחוזה יישבר גם אם
    מישהו יעטוף אותו בכלי אחר בעתיד."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]

    result = DashboardService(db, org_id).get_ap_aging()

    for key in ("bucket_0_30", "bucket_31_60", "bucket_61_90",
                "bucket_90_plus", "total", "count", "bills"):
        assert key in result, f"חסר מפתח {key}"
