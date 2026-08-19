"""budget_vs_actual — הכלי מ-MOSHKO_CAPABILITY_PROPOSALS.md, ממופה למנוע
קיים: `BudgetService.get_budget_vs_actual` בנוי ומתוחזק (642 שורות), אך
מעולם לא היה חשוף כלי-מושקו — המשתמש לא יכול היה לשאול "איך אני מול
התקציב החודש". ר' `[[budget-actuals-real-source]]`: התיקון שקדם לזה
(_get_actual_by_category → Bill/Expense/Invoice במקום Transaction הקפוא)
הוא מה שהופך את הכלי הזה לבטוח לחשיפה — בלעדיו הוא היה תמיד מדווח
"0 בפועל" בכל קטגוריה, גרוע מאין-כלי כלל.
"""
import asyncio
from datetime import date

import pytest

from cfo.database import SessionLocal
from cfo.models import Bill, BillStatus
from cfo.services.ai_chat_tools import TOOLS
from cfo.services.budget_service import BudgetService


def test_the_tool_is_registered():
    assert "get_budget_vs_actual" in TOOLS
    assert TOOLS["get_budget_vs_actual"].category == "read"


def test_it_reflects_a_real_budget_against_real_bills(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]

    svc = BudgetService(db, organization_id=org_id)
    svc.create_budget("office", 500.0, date(2026, 4, 1))

    from cfo.models import Contact

    vendor = Contact(organization_id=org_id, name="ציוד משרדי בע\"מ", contact_type="vendor")
    db.add(vendor); db.flush()
    db.add(Bill(
        organization_id=org_id, external_id="B-1", source="sumit",
        vendor_id=vendor.id, bill_number="1", issue_date=date(2026, 4, 5),
        subtotal=800.0, tax=136.0, status=BillStatus.RECEIVED,
    ))
    db.commit()

    result = asyncio.run(TOOLS["get_budget_vs_actual"].fn(
        db, org_id, year=2026, month=4,
    ))

    office = next((c for c in result["categories"] if c["category_id"] == "office"), None)
    assert office is not None
    assert office["budget_amount"] == 500.0
    assert office["actual_amount"] == 800.0
    assert office["status"] == "over_budget"


def test_no_budget_set_is_honest_not_fabricated(fresh_org):
    """אין תקציב מוגדר → אין קטגוריות, לא ברירת-מחדל מומצאת."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]

    result = asyncio.run(TOOLS["get_budget_vs_actual"].fn(
        db, org_id, year=2026, month=4,
    ))

    assert result["categories"] == []


def test_org_scoped(fresh_org):
    db = SessionLocal()
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]

    svc_b = BudgetService(db, organization_id=org_b)
    svc_b.create_budget("marketing", 1000.0, date(2026, 4, 1))
    db.add(Bill(
        organization_id=org_b, external_id="B-2", source="sumit",
        bill_number="2", issue_date=date(2026, 4, 5),
        subtotal=1200.0, tax=204.0, status=BillStatus.RECEIVED,
    ))
    db.commit()

    result = asyncio.run(TOOLS["get_budget_vs_actual"].fn(
        db, org_a, year=2026, month=4,
    ))

    assert result["categories"] == []
