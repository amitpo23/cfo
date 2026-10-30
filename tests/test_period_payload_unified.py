"""One Bank | Books | Budget payload for P&L, BvA and cashflow screens.

/pnl, /budget and /cashflow read /api/cashflow/period. The /d tabs read
/api/dashboards/{id}/period-compare or /api/public/d/{slug}/period-compare.
For the same organization and range all three return the same payload.
"""
from datetime import date, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import BankTransaction, Bill, BillStatus, Invoice, InvoiceStatus
from cfo.services.dashboards.period_compare import compare_period


def _seed(org_id: int) -> None:
    db = SessionLocal()
    db.add(Invoice(
        organization_id=org_id, invoice_number="U-IN-1", status=InvoiceStatus.SENT,
        issue_date=date(2026, 1, 5), subtotal=Decimal("1000"), tax=Decimal("180"), total=Decimal("1180"),
        balance=Decimal("1180"),
    ))
    db.add(Bill(
        organization_id=org_id, bill_number="U-B-1", status=BillStatus.RECEIVED,
        issue_date=date(2026, 1, 7), subtotal=Decimal("400"), tax=Decimal("0"), total=Decimal("400"),
        balance=Decimal("400"),
    ))
    db.add(BankTransaction(
        organization_id=org_id, source="open_finance", external_id="u-in-1",
        transaction_date=date(2026, 1, 6), amount=Decimal("1180"),
        description="הפקדה", raw_data={"status": "BOOKED"},
    ))
    db.commit()
    db.close()


def _dashboard(client, owner, slug):
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"], "slug": slug, "title": "איחוד", "access_mode": "link",
    })
    assert created.status_code == 201, created.text
    saved = client.put("/api/financial/budget/lines", headers=owner["headers"], json={"updates": [
        {"id": "sales", "label": "מכירות", "category": "sales", "kind": "revenue",
         "month": "2026-01", "status": "filled", "amount": 5000},
        {"id": "other", "label": "אחר", "category": "other", "kind": "cost",
         "month": "2026-01", "status": "filled", "amount": 3000},
    ]})
    assert saved.status_code == 200, saved.text
    return created.json()


def test_cashflow_period_and_dashboard_routes_share_one_payload(client, fresh_org):
    owner = fresh_org()
    _seed(owner["org_id"])
    dashboard = _dashboard(client, owner, "unified-payload")
    params = {"grain": "month", "start": "2026-01-01", "end": "2026-01-31"}

    screens = client.get("/api/cashflow/period", headers=owner["headers"], params=params)
    editor = client.get(f"/api/dashboards/{dashboard['id']}/period-compare", headers=owner["headers"], params=params)
    public = client.get(f"/api/public/d/{dashboard['slug']}/period-compare", headers=owner["headers"], params=params)
    for response in (screens, editor, public):
        assert response.status_code == 200, response.text
        assert response.json()["organization_id"] == owner["org_id"]

    body = screens.json()
    assert body == editor.json()
    assert body == public.json()
    assert body["dashboard_slug"] == "unified-payload"
    totals = body["totals"]
    assert totals["budget"]["revenue"]["amount"] == 5000
    assert totals["books"]["revenue"]["amount"] == 1000
    assert totals["books"]["costs"]["amount"] == 400
    assert totals["bank"]["in"]["amount"] == 1180


def test_budget_vs_actual_reads_the_same_dashboard_as_the_period_payload(client, fresh_org):
    owner = fresh_org()
    _dashboard(client, owner, "unified-bva")
    period = client.get("/api/cashflow/period", headers=owner["headers"], params={
        "grain": "month", "start": "2026-01-01", "end": "2026-01-31",
    }).json()
    bva = client.get("/api/financial/budget/vs-actual", headers=owner["headers"], params={
        "year": 2026, "month": 1, "period": "month",
    }).json()["data"]
    assert bva["dashboard_slug"] == period["dashboard_slug"] == "unified-bva"


def test_cash_movement_stays_known_when_a_profit_claim_is_blocked(fresh_org, monkeypatch):
    """Unclassified outflows withhold profit. The cash that moved is still a fact."""
    from cfo.services.dashboards import period_compare
    monkeypatch.setattr(period_compare, "_unclassified_outflows", lambda *args: {
        "count": 1, "amount": 200.0, "blocks_profit": True, "label_he": "חסר/לסיווג",
    })
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    db.add(BankTransaction(
        organization_id=org_id, source="open_finance", external_id="u-cash-in",
        transaction_date=date(2026, 1, 6), amount=Decimal("500"),
        description="הפקדה", raw_data={"status": "BOOKED"},
    ))
    db.add(BankTransaction(
        organization_id=org_id, source="open_finance", external_id="u-cash-out",
        transaction_date=date(2026, 1, 8), amount=Decimal("-200"),
        description="תשלום לא מזוהה", raw_data={"status": "BOOKED"},
    ))
    db.commit()

    result = compare_period(
        db, org_id, None, grain="month", start=date(2026, 1, 1), end=date(2026, 1, 31),
        as_of=date(2026, 10, 30),
    )

    assert result["profit_claim"]["allowed"] is False
    assert result["totals"]["bank"]["net"]["amount"] is None
    cash = result["totals"]["cash"]
    assert cash["in"]["amount"] == 500
    assert cash["out"]["amount"] == 200
    assert cash["net"]["amount"] == 300
    assert cash["net"]["source"] == "bank.BOOKED"
    db.close()


def test_day_totals_ignore_days_that_have_not_happened(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    today = date(2026, 1, 10)
    for offset in range(3):
        db.add(BankTransaction(
            organization_id=org_id, source="open_finance", external_id=f"u-day-{offset}",
            transaction_date=today - timedelta(days=offset), amount=Decimal("100"),
            description="הפקדה", raw_data={"status": "BOOKED"},
        ))
    db.commit()

    result = compare_period(
        db, org_id, None, grain="day", start=today - timedelta(days=2), end=today + timedelta(days=2),
        as_of=today,
    )

    assert [period["elapsed"] for period in result["periods"]] == [True, True, True, False, False]
    assert result["totals"]["cash"]["in"]["amount"] == 300
    assert result["totals"]["bank"]["in"]["amount"] == 300
    db.close()


def test_week_across_two_months_keeps_budget_missing_without_a_driver(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    plan = {"budgetLines": [
        {"id": "income", "kind": "revenue", "months": {
            "2026-01": {"amount": 3100, "status": "confirmed"},
            "2026-02": {"amount": 2800, "status": "confirmed"}}},
        {"id": "costs", "kind": "cost", "months": {
            "2026-01": {"amount": 620, "status": "confirmed"},
            "2026-02": {"amount": 560, "status": "confirmed"}}},
    ]}

    result = compare_period(
        db, org_id, plan, grain="week", start=date(2026, 1, 29), end=date(2026, 2, 4),
        as_of=date(2026, 10, 30),
    )

    budget = result["periods"][0]["budget"]
    assert budget["revenue"]["amount"] is None
    assert budget["net"]["missing_label"]
    assert [row["month"] for row in budget["month_context"]] == ["2026-01", "2026-02"]
    assert result["totals"]["budget"]["net"]["amount"] is None
    db.close()
