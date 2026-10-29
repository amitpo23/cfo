"""One balance, no placeholder income, discounting is financing, gaps are not funding."""
from datetime import date, datetime
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, BankTransaction
from cfo.services.dashboards import filing, liquidity
from cfo.services.dashboards.books import cash_basis_month
from cfo.services.dashboards.budget_fill import budget_lines_for_org, counts_in_total
from cfo.services.dashboards.cash_forecast import _principal
from cfo.services.dashboards.money_screens import (
    credit_overrun, partial_data_banner, reject_gap_as_funding, unexplained_gap,
)
from cfo.services.open_finance_connector import OpenFinanceConnector


def _entry(balance_type, amount, ref="2026-10-25"):
    return {
        "balanceType": balance_type,
        "balanceAmount": {"amount": amount, "currency": "ILS"},
        "referenceDate": ref,
    }


def _txn(**kwargs):
    defaults = dict(
        id=None, organization_id=6, account_id=9, date="2026-10-25",
        amount=1000.0, description="", debtor="", creditor="",
    )
    defaults.update(kwargs)
    return filing.Txn(**defaults)


def test_booked_balance_is_not_replaced_by_available_or_forward():
    account = OpenFinanceConnector("cid", "secret", "user")._normalize_account({
        "id": "fg-checking",
        "accountType": "CHECKING",
        "currency": "ILS",
        "creditLimit": "100000",
        "balances": [
            _entry("closingBooked", "-134845.05"),
            _entry("interimAvailable", "28052.95"),
            _entry("forwardAvailable", "10000.00"),
        ],
    })
    assert account.balance == Decimal("-134845.05")
    assert account.available_limit == Decimal("28052.95")
    assert account.forward_available == Decimal("10000.00")
    assert account.balance != account.available_limit
    assert account.balance != account.forward_available


def test_forward_available_without_interim_stays_off_the_booked_balance():
    account = OpenFinanceConnector("cid", "secret", "user")._normalize_account({
        "id": "fg-checking",
        "accountType": "CHECKING",
        "balances": [
            _entry("closingBooked", "-134845.05"),
            _entry("forwardAvailable", "10000.00"),
        ],
    })
    assert account.balance == Decimal("-134845.05")
    assert account.available_limit == Decimal("10000.00")
    assert account.forward_available == Decimal("10000.00")


def test_available_alone_is_not_a_booked_balance_or_zero():
    account = OpenFinanceConnector("cid", "secret", "user")._normalize_account({
        "id": "fg-checking",
        "accountType": "CHECKING",
        "balances": [
            _entry("interimAvailable", "28052.95"),
            _entry("forwardAvailable", "10000"),
        ],
    })
    assert account.balance is None
    assert account.available_limit == Decimal("28052.95")
    assert account.forward_available == Decimal("10000")


def test_overrun_uses_the_booked_balance_not_the_friendlier_number(fresh_org):
    owner = fresh_org()
    with SessionLocal() as db:
        account = Account(
            organization_id=owner["org_id"], name="הפועלים", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id="fg",
            balance=Decimal("-134845.05"), credit_limit=Decimal("100000"),
            available_limit=Decimal("28052.95"),
            balance_as_of=datetime(2026, 10, 28), currency="ILS",
        )
        db.add(account)
        db.flush()
        db.add(BankTransaction(
            organization_id=owner["org_id"], account_id=account.id,
            transaction_date=date(2026, 10, 25),
            amount=Decimal("62898"), description="צקים דחויים", source="open_finance",
            external_id="cheque-62898",
            raw_data={"status": "BOOKED", "balancePerEndDay": -71947.05},
        ))
        db.commit()
        snap = liquidity.checking_snapshot(db, owner["org_id"], today=date(2026, 10, 28))
    assert snap["balance"] == -134845.05
    assert snap["booked_balance"] == -134845.05
    assert snap["available"] == 28052.95
    assert snap["balance"] != round(-134845.05 + 62898, 2)
    assert snap["credit_overrun"]["status"] == "overrun"
    assert snap["credit_overrun"]["overrun"] == round(134845.05 - 100000, 2)
    assert snap["balance_mismatch"]["amount"] == 62898.0
    assert snap["balance_mismatch"]["counts_as_funding_need"] is False
    friendlier = credit_overrun(-71947.05, 100000)
    assert friendlier["status"] == "within"
    assert snap["credit_overrun"]["status"] != friendlier["status"]


def test_unexplained_of_gap_is_not_a_funding_need():
    parts = [
        {"amount": 41000, "label": "פער לא מזוהה"},
        {"amount": 62898, "label": "שיק שנגבה 25.10"},
    ]
    gap = unexplained_gap(-134845.05, -71947.05, parts=parts)
    assert gap["amount"] == 103898
    assert gap["counts_as_funding_need"] is False
    assert "אינו צורך מימון" in gap["label_he"]
    assert reject_gap_as_funding(103898, gap["amount"]) is None
    assert reject_gap_as_funding(12000, gap["amount"]) == 12000


def test_discount_repayment_is_not_recurring_principal_and_the_fee_is_not_income():
    advance = _txn(description="ניכיון שיקים", amount=132000.0)
    repay_discount = _txn(description="צ'קים דחויים", amount=-62424.0)
    repay_loan = _txn(description="פרעון הלוואה", amount=-4400.0)
    collected = _txn(description="צקים דחויים", amount=70483.0)
    fee_only = _txn(description="צקים דחויים", amount=10898.0, organization_id=6)
    fee_repay = _txn(description="ניכיון שיקים", amount=-10000.0)
    invoices = [
        {"organization_id": 2, "number": "20055", "date": "2026-06-30", "total": 70483.0},
        {"organization_id": 6, "number": "30001", "date": "2026-09-01", "total": 10898.0},
    ]
    rows = [advance, repay_discount, repay_loan, collected, fee_only, fee_repay]
    filed = filing.classify_all(rows, invoices=invoices)
    assert filed[id(advance)].category == "loans_in"
    assert filed[id(repay_discount)].extra["financing"] == "repayment"
    assert filed[id(repay_discount)].extra["recurring_loan"] is False
    assert filed[id(collected)].category == "intercompany"
    assert filed[id(collected)].extra["customer_receipt_for"] == 2
    # 70483 - 62424 = 8059, above the fee cap, so it is not a discount fee.
    assert "financing_cost" not in filed[id(collected)].extra
    assert filed[id(fee_only)].category == "loans_in"
    assert filed[id(fee_only)].extra["financing_cost"] == 898
    month = cash_basis_month([(row, filed[id(row)]) for row in rows])
    assert month["revenue"] == 0.0
    interest = next(line for line in month["lines"] if line["id"] == "interest")
    assert interest["amount"] == 898.0
    service = liquidity._debt_service([(row, filed[id(row)]) for row in rows], ["2026-10"])
    assert service[0]["principal"] == 4400.0
    assert service[0]["discount_repayment"] == 72424.0
    view = {"liquidity": {"debt_service": service}}
    assert _principal(view, date(2026, 11, 1)) == 4400.0


def test_chef_collection_in_food_group_is_intercompany_not_operating_income():
    collected = _txn(description="צקים דחויים", amount=62898.0, organization_id=6)
    invoices = [{"organization_id": 2, "number": "C-25", "date": "2026-08-01", "total": 62898.0}]
    filed = filing.classify_all([collected], invoices=invoices)
    assert filed[id(collected)].category == "intercompany"
    assert filed[id(collected)].extra["customer_receipt_for"] == 2
    month = cash_basis_month([(collected, filed[id(collected)])])
    assert month["revenue"] == 0.0


def test_placeholder_income_is_excluded_from_the_total_and_the_displayed_amount(client, fresh_org):
    assert counts_in_total(
        {"kind": "revenue", "category": "sales"},
        {"amount": 10_000_000, "status": "filled"},
    ) is None
    owner = fresh_org()
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"], "slug": "ph-income", "title": "תקציב", "access_mode": "public",
    })
    assert created.status_code == 201, created.text
    saved = client.put("/api/financial/budget/lines", headers=owner["headers"], json={"updates": [{
        "id": "sales", "label": "הכנסות", "category": "sales", "kind": "revenue",
        "month": "2026-10", "status": "filled", "amount": 10000000,
    }]})
    assert saved.status_code == 200, saved.text
    listed = client.get("/api/financial/budget/lines", headers=owner["headers"], params={
        "year": 2026, "from_month": 10, "to_month": 10,
    })
    line = next(row for row in listed.json()["data"]["lines"] if row["id"] == "sales")
    cell = line["months"]["2026-10"]
    assert cell["amount"] is None
    assert cell["placeholder_amount"] == "10000000.00"
    assert "לא נמחק" in cell["placeholder_warning"]


def test_chef_payroll_line_does_not_apply_to_another_org():
    plan = {"budgetLines": [{
        "id": "wage_chef", "kind": "cost", "category": "salaries",
        "months": {"2026-10": {"quantity": 1, "rate": 49700}},
    }]}
    assert [line["id"] for line in budget_lines_for_org(plan, 2, primary=True)] == ["wage_chef"]
    assert budget_lines_for_org(plan, 6, primary=False) == []
    named = {"budgetLines": [{
        "id": "wage_fg", "organizationId": 6, "kind": "cost",
        "months": {"2026-10": {"quantity": 1, "rate": 12000}},
    }]}
    assert [line["id"] for line in budget_lines_for_org(named, 6, primary=False)] == ["wage_fg"]
    assert budget_lines_for_org(named, 2, primary=True) == []


def test_partial_banner_names_bank_and_books_dates():
    banner = partial_data_banner(date(2026, 10, 25), date(2026, 9, 30))
    assert banner["text_he"] == "נתונים חלקיים — בנק עד 25.10, ספרים עד 30.09"
    missing = partial_data_banner(None, None)
    assert missing["text_he"] == "נתונים חלקיים — בנק עד חסר, ספרים עד חסר"


def test_empty_cumulative_pl_is_missing_not_zero(fresh_org):
    from cfo.services.daily_reports_service import cumulative_pl
    org_id = fresh_org()["org_id"]
    with SessionLocal() as db:
        report = cumulative_pl(db, org_id, 2026, 4)
    assert report["totals"]["revenue"] is None
    assert report["totals"]["expense"] is None
    assert report["totals"]["profit"] is None
    assert report["basis"] == "no_books"
    assert report["days"] == []
