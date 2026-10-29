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


def test_empty_window_is_missing_not_zero_even_when_another_day_has_a_bank_row(fresh_org):
    """A quiet day is not a zero. Books, bank and budget stay missing, with as-of."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    db.add(BankTransaction(
        organization_id=org_id, source="open_finance", external_id="other-day",
        transaction_date=date(2026, 1, 2), amount=Decimal("10"),
        description="הפקדה", raw_data={"status": "BOOKED"},
    ))
    db.commit()

    result = compare_period(
        db, org_id, None, grain="day",
        start=date(2026, 1, 5), end=date(2026, 1, 5), as_of=date(2026, 10, 29),
    )

    period = result["periods"][0]
    figures = [
        period["books"]["revenue"], period["books"]["costs"], period["books"]["net"],
        period["bank"]["in"], period["bank"]["out"], period["bank"]["net"],
        period["budget"]["revenue"], period["budget"]["costs"], period["budget"]["net"],
        result["totals"]["books"]["net"], result["totals"]["bank"]["net"], result["totals"]["budget"]["net"],
    ]
    for figure in figures:
        assert figure["amount"] is None
        assert figure["amount"] != 0
        assert figure["as_of"] == "2026-10-29"
        assert figure["missing_label"]


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


def _sides(month, revenue, costs):
    def cell(amount):
        return {"amount": amount, "quantity": 1, "rate": amount, "status": "confirmed"}
    return {"budgetLines": [
        {"id": "income", "kind": "revenue", "label": "הכנסות", "months": {month: cell(revenue)}},
        {"id": "costs", "kind": "cost", "label": "הוצאות", "months": {month: cell(costs)}},
    ]}


def test_quarter_budget_is_not_three_times_one_filled_month(fresh_org):
    """A quarter is the months that actually have lines. One month is not ×3."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    plan = _sides("2026-01", 283200, 226000)

    result = compare_period(
        db, org_id, plan, grain="quarter",
        start=date(2026, 1, 1), end=date(2026, 3, 31), as_of=date(2026, 10, 29),
    )

    budget = result["periods"][0]["budget"]
    assert budget["revenue"]["amount"] == 283200
    assert budget["costs"]["amount"] == 226000
    assert budget["revenue"]["amount"] != 849600
    assert budget["costs"]["amount"] != 678000
    assert budget["net"]["amount"] == 283200 - 226000
    assert "2026-02" in budget["months_missing"]
    assert "2026-03" in budget["months_missing"]
    assert budget["ahead"]["revenue"]["amount"] is None
    assert result["totals"]["budget"]["revenue"]["amount"] == 283200
    assert result["totals"]["books"]["net"]["amount"] is None
    assert result["totals"]["books"]["revenue"]["amount"] != 0
    assert result["totals"]["bank"]["net"]["amount"] is None
    assert result["profit"][0]["books"]["amount"] is None
    assert result["profit"][0]["budget"]["amount"] == 283200 - 226000
    assert result["provider_calls"] == 0


def test_quarter_does_not_add_months_that_have_not_started(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    income = {"id": "income", "kind": "revenue", "label": "הכנסות", "months": {}}
    costs = {"id": "costs", "kind": "cost", "label": "הוצאות", "months": {}}
    for month in ("2026-10", "2026-11", "2026-12"):
        income["months"][month] = {"amount": 283200, "quantity": 1, "rate": 283200, "status": "confirmed"}
        costs["months"][month] = {"amount": 226000, "quantity": 1, "rate": 226000, "status": "confirmed"}

    result = compare_period(
        db, org_id, {"budgetLines": [income, costs]}, grain="quarter",
        start=date(2026, 10, 1), end=date(2026, 12, 31), as_of=date(2026, 10, 29),
    )

    budget = result["periods"][0]["budget"]
    assert budget["revenue"]["amount"] == 283200
    assert budget["costs"]["amount"] == 226000
    assert budget["ahead"]["revenue"]["amount"] == 566400
    assert budget["ahead"]["costs"]["amount"] == 452000
    assert result["totals"]["budget"]["revenue"]["amount"] == 283200
    assert result["totals"]["books"]["net"]["amount"] is None
    assert result["totals"]["bank"]["net"]["amount"] is None


def test_period_switch_refreshes_budget_totals(client, fresh_org):
    owner = fresh_org()
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"], "slug": "period-switch", "title": "טווח", "access_mode": "link",
    })
    assert created.status_code == 201, created.text
    saved = client.put("/api/financial/budget/lines", headers=owner["headers"], json={"updates": [
        {"id": "sales", "label": "מכירות", "category": "sales", "kind": "revenue",
         "month": "2026-01", "status": "filled", "amount": 283200},
        {"id": "sales", "label": "מכירות", "category": "sales", "kind": "revenue",
         "month": "2026-02", "status": "filled", "amount": 1000},
        {"id": "other", "label": "אחר", "category": "other", "kind": "cost",
         "month": "2026-01", "status": "filled", "amount": 226000},
    ]})
    assert saved.status_code == 200, saved.text

    def read(grain, start, end):
        response = client.get("/api/cashflow/period", headers=owner["headers"], params={
            "grain": grain, "start": start, "end": end,
        })
        assert response.status_code == 200, response.text
        return response.json()

    month = read("month", "2026-01-01", "2026-01-31")
    quarter = read("quarter", "2026-01-01", "2026-03-31")
    assert month["totals"]["budget"]["revenue"]["amount"] == 283200
    assert quarter["totals"]["budget"]["revenue"]["amount"] == 284200
    assert quarter["totals"]["budget"]["revenue"]["amount"] != 283200 * 3
    assert quarter["totals"]["books"]["net"]["amount"] is None
    assert quarter["totals"]["bank"]["net"]["amount"] is None
    assert quarter["periods"][0]["books"]["revenue"]["amount"] is None
    assert quarter["dashboard_slug"] == "period-switch"
