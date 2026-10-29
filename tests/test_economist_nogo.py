"""Economist NO-GO: do not inflate AR, invent a zero, or claim a profit that is not one."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, BankTransaction, Invoice, InvoiceStatus
from cfo.services.dashboard_service import DashboardService
from cfo.services.dashboards import filing
from cfo.services.dashboards.liquidity import checking_snapshot
from cfo.services.dashboards.money_screens import ar_display, operating_income_hits, verified_amount
from cfo.services.dashboards.period_compare import compare_period
from cfo.services.financial_control_service import FinancialControlService


def _txn(**kwargs):
    defaults = dict(
        id=None, organization_id=6, account_id=9, date="2026-10-25",
        amount=0.0, description="", debtor="", creditor="",
    )
    defaults.update(kwargs)
    return filing.Txn(**defaults)


def test_ar_is_missing_not_zero_when_nothing_was_invoiced():
    gate = ar_display(None, None, None, saw_invoices=False)
    assert gate["amount"] is None
    assert gate["amount"] != 0
    assert gate["status"] == "missing"
    assert "חסר" in gate["reason_he"]
    assert verified_amount(0, measured=False) is None
    assert verified_amount(0, measured=True) == 0


def test_ar_above_ever_invoiced_is_invalid_not_inflated(fresh_org):
    owner = fresh_org()
    org_id = owner["org_id"]
    with SessionLocal() as db:
        db.add(Invoice(
            organization_id=org_id, invoice_number="1", status=InvoiceStatus.SENT,
            issue_date=date(2026, 10, 1), due_date=date(2026, 10, 15),
            subtotal=Decimal("1000"), tax=Decimal("180"), total=Decimal("1180"),
            balance=Decimal("5000"),
        ))
        db.commit()
        overview = DashboardService(db, org_id).get_overview()
        aging = DashboardService(db, org_id).get_ar_aging()
    assert overview["ever_invoiced"] == 1180.0
    assert overview["ar_total"] is None
    assert overview["ar_status"] == "invalid"
    assert overview["ar_total"] != 5000
    assert aging["total"] is None
    assert aging["ar_status"] == "invalid"


def test_open_ar_within_what_was_invoiced_is_shown(fresh_org):
    owner = fresh_org()
    org_id = owner["org_id"]
    with SessionLocal() as db:
        db.add(Invoice(
            organization_id=org_id, invoice_number="1", status=InvoiceStatus.SENT,
            issue_date=date(2026, 10, 1), due_date=date(2026, 10, 15),
            subtotal=Decimal("1000"), tax=Decimal("180"), total=Decimal("1180"),
            balance=Decimal("400"),
        ))
        db.commit()
        overview = DashboardService(db, org_id).get_overview()
    assert overview["ar_total"] == 400.0
    assert overview["ar_total"] <= overview["ever_invoiced"]
    assert overview["ar_status"] == "ok"


def test_empty_org_ar_on_the_overview_is_not_zero(fresh_org):
    owner = fresh_org()
    with SessionLocal() as db:
        overview = DashboardService(db, owner["org_id"]).get_overview()
    assert overview["ar_total"] is None
    assert overview["ar_status"] == "missing"


def test_displayed_balance_is_the_of_closing_booked(fresh_org):
    owner = fresh_org()
    org_id = owner["org_id"]
    booked = Decimal("-134845.05")
    with SessionLocal() as db:
        db.add(Account(
            organization_id=org_id, name="הפועלים", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id="fg",
            balance=booked, credit_limit=Decimal("100000"),
            balance_as_of=datetime.utcnow(), currency="ILS",
        ))
        db.add(BankTransaction(
            organization_id=org_id, transaction_date=date.today(),
            amount=Decimal("62898"), description="צקים דחויים", source="open_finance",
            external_id="cheque-62898", raw_data={"status": "BOOKED"},
        ))
        db.commit()
        snap = checking_snapshot(db, org_id, today=date.today())
        overview = DashboardService(db, org_id).get_overview()
        control = FinancialControlService(db, org_id).get_control_overview()
    assert snap["balance"] == float(booked)
    assert overview["cash_balance"] == snap["balance"]
    assert control["cash"]["bank_account_balance"] == snap["balance"]
    assert overview["cash_balance"] != round(float(booked) + 62898, 2)


def test_intercompany_cheque_is_not_invoice_plus_bank_plus_discount():
    invoice = {"organization_id": 2, "number": "C-25", "date": "2026-08-01", "total": 62898.0}
    advance = _txn(description="ניכיון שיקים", amount=60000.0, organization_id=6)
    collected = _txn(description="צקים דחויים", amount=62898.0, organization_id=6)
    filed = filing.classify_all([advance, collected], invoices=[dict(invoice)])
    hits = operating_income_hits([invoice], [(advance, filed[id(advance)]), (collected, filed[id(collected)])])
    assert hits == [62898.0]
    assert sum(hits) != 62898.0 + 62898.0 + 60000.0
    assert filed[id(collected)].category == "intercompany"
    assert filed[id(advance)].category == "loans_in"


def test_unclassified_outflows_block_a_profit_claim(fresh_org):
    owner = fresh_org()
    org_id = owner["org_id"]
    with SessionLocal() as db:
        db.add(Invoice(
            organization_id=org_id, invoice_number="1", status=InvoiceStatus.SENT,
            issue_date=date(2026, 10, 4), subtotal=Decimal("1000"), tax=Decimal("0"),
            total=Decimal("1000"), balance=Decimal("1000"),
        ))
        db.add(BankTransaction(
            organization_id=org_id, source="open_finance", external_id="fg-out",
            transaction_date=date(2026, 10, 20), amount=Decimal("-187547"),
            description="העברה לספק", raw_data={"status": "BOOKED"},
        ))
        db.commit()
        report = compare_period(
            db, org_id, None, grain="month",
            start=date(2026, 10, 1), end=date(2026, 10, 31),
            as_of=date(2026, 10, 28),
        )
    assert report["unclassified_outflows"]["blocks_profit"] is True
    assert report["unclassified_outflows"]["amount"] == 187547.0
    assert report["profit_claim"]["allowed"] is False
    assert "אי אפשר לטעון רווח" in report["profit_claim"]["reason_he"]
    assert report["periods"][0]["books"]["net"]["amount"] is None
    assert report["periods"][0]["books"]["net"]["amount"] != 1000
    assert report["profit"][0]["books"]["amount"] is None
