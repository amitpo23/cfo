"""Three-source budget comparison for a chosen grain. No provider calls."""
from datetime import date
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import BankTransaction, Bill, BillStatus, Invoice, InvoiceStatus
from cfo.services.dashboards.period_compare import compare_period


def _plan(month, revenue, costs, formula=""):
    def cell(amount):
        return {"amount": amount, "status": "confirmed"}
    return {"budgetLines": [
        {"id": "income", "kind": "revenue", "label": "הכנסות", "driver_formula": formula,
         "months": {month: cell(revenue)}},
        {"id": "costs", "kind": "cost", "label": "הוצאות", "driver_formula": formula,
         "months": {month: cell(costs)}},
    ]}


def test_month_budget_is_the_saved_lines_and_books_are_local(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    db.add(Invoice(
        organization_id=org_id, invoice_number="IN-1", status=InvoiceStatus.SENT,
        issue_date=date(2026, 10, 4), subtotal=Decimal("100"), tax=Decimal("18"), total=Decimal("118"),
        balance=Decimal("118"),
    ))
    db.add(Bill(
        organization_id=org_id, bill_number="B-1", status=BillStatus.RECEIVED,
        issue_date=date(2026, 10, 6), subtotal=Decimal("40"), tax=Decimal("0"), total=Decimal("40"),
        balance=Decimal("40"),
    ))
    db.commit()

    result = compare_period(
        db, org_id, _plan("2026-10", 151200, 226000),
        grain="month", start=date(2026, 10, 1), end=date(2026, 10, 31),
    )

    period = result["periods"][0]
    assert result["provider_calls"] == 0
    assert period["budget"]["revenue"]["amount"] == 151200
    assert period["budget"]["costs"]["amount"] == 226000
    assert period["budget"]["net"]["amount"] == 151200 - 226000
    assert period["books"]["revenue"]["amount"] == 100
    assert period["books"]["costs"]["amount"] == 40
    assert period["books"]["net"]["amount"] == 60
    assert period["books"]["revenue"]["source"] == "books.local_documents"
    assert period["variance"]["books_vs_budget"]["amount"] == 60 - (151200 - 226000)


def test_day_does_not_divide_a_month_budget_without_a_driver(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]

    result = compare_period(
        db, org_id, _plan("2026-10", 3000, 600),
        grain="day", start=date(2026, 10, 15), end=date(2026, 10, 15),
    )

    period = result["periods"][0]
    assert period["budget"]["net"]["amount"] is None
    assert period["budget"]["net"]["missing_label"]
    assert period["budget"]["month_context"][0]["revenue"] == 3000
    assert period["variance"]["books_vs_budget"]["amount"] is None
    assert period["books"]["net"]["amount"] is None


def test_explicit_daily_driver_splits_the_month(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]

    result = compare_period(
        db, org_id, _plan("2026-10", 3100, 620, formula="per_day"),
        grain="day", start=date(2026, 10, 1), end=date(2026, 10, 1),
    )

    period = result["periods"][0]
    assert period["budget"]["revenue"]["amount"] == 100
    assert period["budget"]["costs"]["amount"] == 20
    assert period["budget"]["net"]["amount"] == 80


def test_booked_bank_counts_and_pending_does_not(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    db.add(BankTransaction(
        organization_id=org_id, source="open_finance", external_id="booked-1",
        transaction_date=date(2026, 10, 3), amount=Decimal("50"),
        description="הפקדה", raw_data={"status": "BOOKED"},
    ))
    db.add(BankTransaction(
        organization_id=org_id, source="open_finance", external_id="pending-1",
        transaction_date=date(2026, 10, 3), amount=Decimal("-999"),
        description="ממתין", raw_data={"status": "PENDING"},
    ))
    db.commit()

    result = compare_period(
        db, org_id, None, grain="day", start=date(2026, 10, 3), end=date(2026, 10, 3),
    )

    bank = result["periods"][0]["bank"]
    assert bank["in"]["amount"] == 50
    assert bank["out"]["amount"] == 0
    assert bank["net"]["amount"] == 50
    assert bank["count"] == 1
    assert bank["lines"][0]["description"] == "הפקדה"
    assert bank["lines"][0]["amount"] == 50
    assert bank["in"]["source"] == "bank.BOOKED"


def test_cashflow_period_route_reads_stored_rows_only(client, fresh_org):
    org = fresh_org()
    response = client.get(
        "/api/cashflow/period",
        params={"grain": "day", "start": "2026-10-02", "end": "2026-10-02"},
        headers=org["headers"],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider_calls"] == 0
    assert body["periods"][0]["books"]["net"]["amount"] is None
    assert body["periods"][0]["bank"]["net"]["amount"] is None


def test_empty_books_and_bank_stay_missing_not_zero(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]

    result = compare_period(
        db, org_id, {"budgetLines": []},
        grain="week", start=date(2026, 10, 5), end=date(2026, 10, 11),
    )

    period = result["periods"][0]
    assert period["bank"]["net"]["amount"] is None
    assert period["books"]["revenue"]["amount"] is None
    assert period["books"]["revenue"]["amount"] != 0
    assert period["variance"]["bank_vs_budget"]["amount"] is None
