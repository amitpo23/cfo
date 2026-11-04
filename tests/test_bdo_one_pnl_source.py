"""October books are one figure on every P&L screen.

/pnl and /budget read /cashflow/period. The dashboard overview, /dashboard/pnl
and /daily-reports/cumulative-pl must show the same revenue, costs and net for
the same month. Made-up documents only.
"""
from datetime import date
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Bill, BillStatus, Expense, Invoice, InvoiceStatus
from cfo.services.dashboard_service import DashboardService


def _seed(org_id: int) -> None:
    db = SessionLocal()
    db.add(Invoice(
        organization_id=org_id, invoice_number="T-IN-1", status=InvoiceStatus.SENT,
        issue_date=date(2026, 10, 5), subtotal=Decimal("1000"), tax=Decimal("180"),
        total=Decimal("1180"), balance=Decimal("1180"),
    ))
    db.add(Invoice(
        organization_id=org_id, invoice_number="T-IN-DRAFT", status=InvoiceStatus.DRAFT,
        issue_date=date(2026, 10, 6), subtotal=Decimal("5000"), tax=Decimal("900"),
        total=Decimal("5900"), balance=Decimal("5900"),
    ))
    db.add(Bill(
        organization_id=org_id, bill_number="T-B-1", status=BillStatus.RECEIVED, external_id="twin-1",
        issue_date=date(2026, 10, 7), subtotal=Decimal("400"), tax=Decimal("72"),
        total=Decimal("472"), balance=Decimal("472"),
    ))
    # The same SUMIT document synced again as an expense. Counted once, as the bill.
    db.add(Expense(
        organization_id=org_id, supplier_name="ספק בדיקה", external_id="twin-1", status="filed",
        expense_date=date(2026, 10, 7), amount=Decimal("400"), vat_amount=Decimal("72"), total=Decimal("472"),
    ))
    db.add(Expense(
        organization_id=org_id, supplier_name="ספק ממתין", status="pending",
        expense_date=date(2026, 10, 8), amount=Decimal("250"), vat_amount=Decimal("0"), total=Decimal("250"),
    ))
    db.add(Expense(
        organization_id=org_id, supplier_name="ספק מתויק", status="filed",
        expense_date=date(2026, 10, 9), amount=Decimal("100"), vat_amount=Decimal("18"), total=Decimal("118"),
    ))
    db.commit()
    db.close()


def test_october_books_match_on_every_pnl_screen(client, fresh_org):
    owner = fresh_org()
    _seed(owner["org_id"])
    headers = owner["headers"]

    period = client.get("/api/cashflow/period", headers=headers, params={
        "grain": "month", "start": "2026-10-01", "end": "2026-10-31",
    })
    assert period.status_code == 200, period.text
    books = period.json()["totals"]["books"]
    assert books["revenue"]["amount"] == 1000
    assert books["costs"]["amount"] == 500
    assert books["net"]["amount"] == 500

    daily = client.get("/api/daily-reports/cumulative-pl", headers=headers, params={"year": 2026, "month": 10})
    assert daily.status_code == 200, daily.text
    totals = daily.json()["totals"]
    assert (totals["revenue"], totals["expense"], totals["profit"]) == (1000, 500, 500)
    assert daily.json()["days"][-1]["profit_cum"] == 500

    db = SessionLocal()
    try:
        service = DashboardService(db, owner["org_id"])
        overview = service.get_overview(today=date(2026, 10, 20))
        assert overview["pnl_month"] == "2026-10"
        assert (overview["month_revenue"], overview["month_expenses"], overview["month_net_profit"]) == (1000, 500, 500)

        months = {row["month"]: row for row in service.get_pnl(months=2, today=date(2026, 11, 4))}
        october = months["2026-10"]
        assert (october["revenue"], october["opex"], october["net_profit"]) == (1000, 500, 500)
        # November has no books yet: every screen opens on October, not an empty month.
        assert service.get_overview(today=date(2026, 11, 4))["pnl_month"] == "2026-10"
    finally:
        db.close()


def test_withheld_profit_is_withheld_on_the_dashboard_too(client, fresh_org, monkeypatch):
    """/pnl withholds profit while bank outflows are unclassified. The other screens follow."""
    from cfo.services.dashboards import period_compare
    owner = fresh_org()
    _seed(owner["org_id"])
    monkeypatch.setattr(period_compare, "_unclassified_outflows", lambda *args: {
        "count": 2, "amount": 70.0, "blocks_profit": True, "label_he": "חסר/לסיווג",
    })
    db = SessionLocal()
    try:
        overview = DashboardService(db, owner["org_id"]).get_overview(today=date(2026, 10, 20))
    finally:
        db.close()
    assert overview["month_revenue"] == 1000
    assert overview["month_net_profit"] is None
    assert overview["pnl_profit_claim"]["allowed"] is False

    daily = client.get("/api/daily-reports/cumulative-pl", headers=owner["headers"], params={"year": 2026, "month": 10}).json()
    assert daily["totals"]["profit"] is None
    assert daily["profit_label"]
    assert daily["days"][-1]["profit_cum"] is None


def test_a_document_stored_without_a_vat_split_is_not_zero_on_pnl(client, fresh_org):
    """subtotal 0 with a gross total: the net is the gross split at the document's rate, on every screen."""
    owner = fresh_org()
    db = SessionLocal()
    db.add(Invoice(
        organization_id=owner["org_id"], invoice_number="T-UNSPLIT", status=InvoiceStatus.SENT,
        issue_date=date(2026, 10, 12), subtotal=Decimal("0"), tax=Decimal("0"),
        total=Decimal("1180"), balance=Decimal("1180"),
    ))
    db.commit()
    db.close()
    period = client.get("/api/cashflow/period", headers=owner["headers"], params={
        "grain": "month", "start": "2026-10-01", "end": "2026-10-31",
    }).json()
    assert period["totals"]["books"]["revenue"]["amount"] == 1000
    daily = client.get("/api/daily-reports/cumulative-pl", headers=owner["headers"], params={"year": 2026, "month": 10}).json()
    assert daily["totals"]["revenue"] == 1000
