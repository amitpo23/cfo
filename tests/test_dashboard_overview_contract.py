"""GET /api/dashboard/overview — חוזה חדש (docs/REZEF_DATA_INTEGRITY_PLAN.md סעיף ד):
מזומן רק מחשבונות OF מסוג CHECKING, AP לעולם לא שלילי, P&L נופל לחודש סגור
אחרון כשאין ספרים לחודש הנוכחי, undocumented_expenses מהמנוע הקיים, וכו'.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest


def _month_bounds(year, month):
    from calendar import monthrange
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


# --------------------------------------------------------------------- #
# cash / savings / loans / card — Open Finance only, CHECKING = cash
# --------------------------------------------------------------------- #
def test_cash_balance_only_from_open_finance_checking_accounts(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Account, AccountType
    from cfo.services.dashboard_service import DashboardService

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        # SUMIT synthesized placeholder — לא נספר במזומן
        db.add(Account(organization_id=org_id, name="Bank Account",
                       account_type=AccountType.BANK, balance=0, source="sumit"))
        # OF checking — נספר
        db.add(Account(organization_id=org_id, name='עו"ש', account_type=AccountType.BANK,
                       balance=Decimal("28459.68"), source="open_finance",
                       balance_as_of=datetime(2026, 7, 12), raw_account_type="CHECKING"))
        # OF savings — לא נספר במזומן
        db.add(Account(organization_id=org_id, name="חיסכון", account_type=AccountType.ASSET,
                       balance=Decimal("5000"), source="open_finance",
                       balance_as_of=datetime(2026, 7, 12), raw_account_type="SAVINGS"))
        db.commit()

        overview = DashboardService(db, org_id).get_overview()
        assert overview["cash_balance"] == 28459.68
        assert overview["savings_balance"] == 5000.0
        assert overview["cash_as_of"] is not None
    finally:
        db.close()


def test_cash_balance_none_when_no_checking_accounts(fresh_org):
    from cfo.database import SessionLocal
    from cfo.services.dashboard_service import DashboardService

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        overview = DashboardService(db, org_id).get_overview()
        assert overview["cash_balance"] is None
        assert overview["cash_as_of"] is None
        assert overview["savings_balance"] is None
        assert overview["loans_total"] is None
        assert overview["card_outstanding"] is None
    finally:
        db.close()


def test_loans_and_card_reported_separately(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Account, AccountType
    from cfo.services.dashboard_service import DashboardService

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(organization_id=org_id, name="הלוואה", account_type=AccountType.LIABILITY,
                       balance=Decimal("11998.41"), source="open_finance",
                       balance_as_of=datetime(2026, 7, 10), raw_account_type="LOAN"))
        db.add(Account(organization_id=org_id, name="כרטיס אשראי", account_type=AccountType.LIABILITY,
                       balance=Decimal("3200"), source="open_finance",
                       balance_as_of=datetime(2026, 7, 12), raw_account_type="CARD"))
        db.commit()

        overview = DashboardService(db, org_id).get_overview()
        assert overview["loans_total"] == 11998.41
        assert overview["card_outstanding"] == 3200.0
    finally:
        db.close()


# --------------------------------------------------------------------- #
# AP — לעולם לא שלילי, רק bills פתוחים
# --------------------------------------------------------------------- #
def test_ap_total_excludes_paid_and_negative_bills(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Contact, ContactType, Bill, BillStatus
    from cfo.services.dashboard_service import DashboardService

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        vend = Contact(organization_id=org_id, contact_type=ContactType.VENDOR, name="ספק")
        db.add(vend)
        db.flush()
        # פתוח — נספר
        db.add(Bill(organization_id=org_id, vendor_id=vend.id, bill_number="B1",
                    issue_date=date(2026, 7, 1), total=500, paid_amount=0, balance=500,
                    status=BillStatus.RECEIVED))
        # PAID (type 15 לשעבר) — לא נספר גם אם יש לו balance (לא אמור, אבל להיות בטוח)
        db.add(Bill(organization_id=org_id, vendor_id=vend.id, bill_number="B2",
                    issue_date=date(2026, 7, 1), total=100, paid_amount=100, balance=0,
                    status=BillStatus.PAID))
        db.commit()

        overview = DashboardService(db, org_id).get_overview()
        assert overview["ap_total"] == 500.0
        assert overview["ap_total"] >= 0
    finally:
        db.close()


def test_ap_due_buckets_only_real_due_dates(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Contact, ContactType, Bill, BillStatus
    from cfo.services.dashboard_service import DashboardService

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        vend = Contact(organization_id=org_id, contact_type=ContactType.VENDOR, name="ספק")
        db.add(vend)
        db.flush()
        today = date.today()
        db.add(Bill(organization_id=org_id, vendor_id=vend.id, bill_number="DueSoon",
                    issue_date=today, due_date=today + timedelta(days=3),
                    total=300, paid_amount=0, balance=300, status=BillStatus.RECEIVED))
        db.add(Bill(organization_id=org_id, vendor_id=vend.id, bill_number="NoDueDate",
                    issue_date=today, due_date=None,
                    total=200, paid_amount=0, balance=200, status=BillStatus.RECEIVED))
        db.commit()

        overview = DashboardService(db, org_id).get_overview()
        assert overview["ap_total"] == 500.0
        assert overview["ap_due_7_days"] == 300.0  # רק זה עם due_date אמיתי
    finally:
        db.close()


# --------------------------------------------------------------------- #
# P&L: נפילה לחודש סגור אחרון כשאין ספרים לחודש הנוכחי
# --------------------------------------------------------------------- #
def test_pnl_falls_back_to_last_closed_month_with_data(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Contact, ContactType, Invoice, InvoiceStatus
    from cfo.services.dashboard_service import DashboardService

    fixed_today = date(2026, 7, 12)  # חודש נוכחי (יולי) בלי ספרים

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        cust = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="לקוח")
        db.add(cust)
        db.flush()
        # מאי 2026 — יש ספרים
        db.add(Invoice(organization_id=org_id, contact_id=cust.id, invoice_number="I1",
                       issue_date=date(2026, 5, 15), status=InvoiceStatus.SENT,
                       total=1000, paid_amount=0, balance=1000))
        db.commit()

        overview = DashboardService(db, org_id).get_overview(today=fixed_today)
        assert overview["pnl_month"] == "2026-05"
        assert overview["pnl_is_current_month"] is False
        assert overview["month_revenue"] == 1000.0
    finally:
        db.close()


def test_pnl_uses_current_month_when_it_has_books(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Contact, ContactType, Invoice, InvoiceStatus
    from cfo.services.dashboard_service import DashboardService

    fixed_today = date(2026, 7, 12)

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        cust = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="לקוח")
        db.add(cust)
        db.flush()
        db.add(Invoice(organization_id=org_id, contact_id=cust.id, invoice_number="I1",
                       issue_date=date(2026, 7, 5), status=InvoiceStatus.SENT,
                       total=2000, paid_amount=0, balance=2000))
        db.commit()

        overview = DashboardService(db, org_id).get_overview(today=fixed_today)
        assert overview["pnl_month"] == "2026-07"
        assert overview["pnl_is_current_month"] is True
        assert overview["month_revenue"] == 2000.0
    finally:
        db.close()


def test_pnl_all_null_when_no_data_anywhere(fresh_org):
    from cfo.database import SessionLocal
    from cfo.services.dashboard_service import DashboardService

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        overview = DashboardService(db, org_id).get_overview(today=date(2026, 7, 12))
        assert overview["month_revenue"] is None
        assert overview["month_expenses"] is None
        assert overview["month_net_profit"] is None
    finally:
        db.close()


# --------------------------------------------------------------------- #
# bank_month_inflow/outflow/net + undocumented_expenses + last_sync + data_quality
# --------------------------------------------------------------------- #
def test_bank_month_flows_and_metadata_fields_present(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Account, AccountType, BankTransaction, SyncRun, SyncStatus
    from cfo.services.dashboard_service import DashboardService

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acct = Account(organization_id=org_id, name='עו"ש', account_type=AccountType.BANK,
                       balance=0, source="open_finance", raw_account_type="CHECKING")
        db.add(acct)
        db.flush()
        today = date.today()
        db.add(BankTransaction(organization_id=org_id, account_id=acct.id,
                               transaction_date=today, amount=Decimal("1000"), description="in"))
        db.add(BankTransaction(organization_id=org_id, account_id=acct.id,
                               transaction_date=today, amount=Decimal("-400"), description="out"))
        db.add(SyncRun(organization_id=org_id, source="sumit", status=SyncStatus.COMPLETED,
                       finished_at=datetime(2026, 7, 12, 6, 0)))
        db.commit()

        overview = DashboardService(db, org_id).get_overview()
        assert overview["bank_month_inflow"] == 1000.0
        assert overview["bank_month_outflow"] == 400.0
        assert overview["bank_month_net"] == 600.0
        assert "undocumented_expenses" in overview
        assert set(overview["undocumented_expenses"].keys()) == {"count", "total", "potential_vat"}
        assert overview["last_sync"]["sumit"] == "2026-07-12T06:00:00"
        assert overview["last_sync"]["open_finance"] is None
        assert "data_quality" in overview
        assert overview["data_quality"]["status"] in ("ok", "issues")
    finally:
        db.close()


def test_runway_none_without_cash_or_history(fresh_org):
    from cfo.database import SessionLocal
    from cfo.services.dashboard_service import DashboardService

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        overview = DashboardService(db, org_id).get_overview()
        assert overview["runway_months"] is None
    finally:
        db.close()
