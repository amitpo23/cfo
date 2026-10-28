"""Books P&L, budget line status, and a budget edit showing up on the dashboard immediately."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import BankTransaction, Bill, BillStatus, Expense, Invoice, InvoiceStatus, JournalEntry


AS_OF = date(2026, 10, 28)


def _create(client, headers, org_id, slug):
    response = client.post("/api/dashboards", headers=headers, json={
        "primary_organization_id": org_id, "slug": slug, "title": "ספרים", "access_mode": "public",
    })
    assert response.status_code == 201, response.text
    client.patch(f"/api/dashboards/{response.json()['id']}", headers=headers,
                 json={"status": "active", "access_mode": "public"})
    return response.json()["id"]


def test_books_pnl_reconciles_to_documents_and_does_not_borrow_the_bank(fresh_org):
    from cfo.services.dashboards.books_pnl import books_pnl

    org_id = fresh_org()["org_id"]
    with SessionLocal() as db:
        db.add(Invoice(
            organization_id=org_id, invoice_number="aug-pizza", issue_date=date(2026, 8, 4),
            status=InvoiceStatus.SENT, subtotal=Decimal("1000"), tax=Decimal("180"), total=Decimal("1180"),
            raw_data={"division": "pizza"},
        ))
        db.add(Invoice(
            organization_id=org_id, invoice_number="aug-draft", issue_date=date(2026, 8, 5),
            status=InvoiceStatus.DRAFT, subtotal=Decimal("9999"), tax=Decimal("0"), total=Decimal("9999"),
        ))
        db.add(Bill(
            organization_id=org_id, external_id="dup-1", bill_number="b1", issue_date=date(2026, 8, 6),
            status=BillStatus.RECEIVED, subtotal=Decimal("300"), tax=Decimal("54"), total=Decimal("354"),
        ))
        db.add(Expense(
            organization_id=org_id, external_id="dup-1", supplier_name="ספק", expense_date=date(2026, 8, 6),
            status="filed", amount=Decimal("300"), vat_amount=Decimal("54"), total=Decimal("354"),
        ))
        db.add(Expense(
            organization_id=org_id, supplier_name="משלוחים", expense_date=date(2026, 8, 8),
            status="filed", amount=Decimal("200"), vat_amount=Decimal("0"), total=Decimal("200"),
            raw_data={"division": "deliveries"}, description="פיצה בתיאור אינה סיווג",
        ))
        db.add(Expense(
            organization_id=org_id, supplier_name="בלי סיווג", expense_date=date(2026, 8, 9),
            status="filed", amount=Decimal("50"), vat_amount=Decimal("0"), total=Decimal("50"),
        ))
        db.add(Expense(
            organization_id=org_id, supplier_name="טיוטה", expense_date=date(2026, 8, 10),
            status="pending", amount=Decimal("400"), vat_amount=Decimal("0"), total=Decimal("400"),
        ))
        db.add(BankTransaction(
            organization_id=org_id, transaction_date=date(2026, 9, 3), amount=Decimal("-800"),
            description="תשלום", source="manual",
        ))
        db.add(JournalEntry(
            organization_id=org_id, source="reviewed_local_import", external_id="j-aug",
            entry_date=date(2026, 8, 12), memo="לא להוסיף על המסמכים",
            lines=[
                {"account": "90003", "debit": 999, "credit": 0},
                {"account": "2000", "debit": 0, "credit": 999},
            ],
        ))
        db.add(JournalEntry(
            organization_id=org_id, source="reviewed_local_import", external_id="j-jul",
            entry_date=date(2026, 7, 2), memo="רק יומן",
            lines=[
                {"account": "90003", "debit": 80, "credit": 0},
                {"account": "2000", "debit": 0, "credit": 80},
            ],
        ))
        db.add(BankTransaction(
            organization_id=org_id, transaction_date=date(2026, 10, 12), amount=Decimal("-5"),
            description="יבוא בנק", source="reviewed_local_import", external_id="fg-bank",
        ))
        db.add(JournalEntry(
            organization_id=org_id, source="reviewed_local_import", external_id="j-stale",
            entry_date=date(2026, 10, 11), memo="יומן ישן",
            lines=[
                {"account": "1000", "debit": 5, "credit": 0},
                {"account": "2000", "debit": 0, "credit": 5},
            ],
        ))
        db.commit()
        report = books_pnl(db, org_id, as_of=AS_OF, months=4, include_documents=True)

    by_month = {month["month"]: month for month in report["months"]}
    assert list(by_month) == ["2026-07", "2026-08", "2026-09", "2026-10"]
    july = by_month["2026-07"]
    assert july["basis"] == "books" and july["source"] == "journal"
    assert july["costs"] == 80.0 and july["revenue"] == 0.0
    assert july["basis_label"] == "ספרים — יומן SUMIT מיובא"
    august = by_month["2026-08"]
    assert august["basis"] == "books" and august["source"] == "documents"
    assert august["journal_not_added"] is True
    assert august["revenue"] == 1000.0
    assert august["costs"] == 550.0
    document_revenue = sum(item["net"] for item in august["documents"] if item["side"] == "revenue")
    document_costs = sum(item["net"] for item in august["documents"] if item["side"] == "cost")
    assert document_revenue == august["revenue"]
    assert document_costs == august["costs"]
    divisions = {row["id"]: row for row in august["divisions"]}
    assert divisions["pizza"]["revenue"] == 1000.0
    assert divisions["deliveries"]["costs"] == 200.0
    assert divisions["clarify"]["costs"] == 350.0
    assert august["clarify_share_pct"] == pytest.approx(350 / 1550 * 100, abs=0.01)
    september = by_month["2026-09"]
    assert september["basis"] == "no_books"
    assert september["revenue"] is None and september["costs"] is None
    assert "אין נתוני ספרים" in september["message"]
    assert september["bank_rows_present"] is True
    stale = {(item["kind"], item["age_days"], item["status_label"]) for item in report["stale_sources"]}
    assert ("bank", 16, "לא עדכני") in stale
    assert ("journal", 17, "לא עדכני") in stale
    assert all(item["status_label"] != "עדכני" for item in report["stale_sources"])
    assert report["provider_calls"] == 0


def test_seed_payroll_is_the_four_filled_lines_and_the_rest_stay_missing():
    import json
    from pathlib import Path
    from cfo.services.dashboards.budget_fill import seed_status

    seed = json.loads(Path("tests/fixtures/eliav_budget_seed_shape.json").read_text(encoding="utf-8"))
    report = seed_status(seed)
    assert [line["id"] for line in report["filled"]] == ["wage_05", "wage_06", "wage_08", "wage_11"]
    assert report["declared_payroll"]["matches_declared"] is True
    assert report["declared_payroll"]["filled_sum"] == "49700.00"
    missing_ids = {line["id"] for line in report["missing"]}
    assert "rev_pizza" in missing_ids and "rev_chef" in missing_ids
    assert "wage_01" in missing_ids
    assert "loan_principal" not in missing_ids


def test_budget_lines_are_not_four_zeros(client, fresh_org):
    owner = fresh_org()
    response = client.get("/api/financial/budget/lines", headers=owner["headers"],
                          params={"year": 2026, "from_month": 1, "to_month": 10})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["counts"]["active"] > 4
    labels = {line["label"] for line in data["lines"]}
    assert "מכירות" in labels or any("מכיר" in label for label in labels)
    january = data["lines"][0]["months"]["2026-01"]
    assert january["status"] == "missing"
    assert january["amount"] is None
    assert january["status_he"] == "חסר, הבעלים יזין"
    assert data["declared_payroll"]["monthly"] == "49700.00"
    assert data["provider_calls"] == 0


def _plan(month_key, rate):
    return {
        "budgetLines": [{
            "id": "sales-1",
            "label": "מכירות",
            "category": "sales",
            "kind": "revenue",
            "months": {month_key: {"quantity": 1, "rate": rate}},
        }],
    }


def _save_plan(client, headers, dashboard_id, payload, version):
    response = client.put(
        f"/api/dashboards/{dashboard_id}/plan",
        headers={**headers, "If-Match": version},
        json={"payload": payload},
    )
    assert response.status_code == 200, response.text
    return response.json()["version"]


def test_saved_budget_replaces_the_snapshot_on_the_next_dashboard_read(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "budget-live")
    today = date.today()
    if today.month == 12:
        nxt = date(today.year + 1, 1, 1)
    else:
        nxt = date(today.year, today.month + 1, 1)
    future = f"{nxt.year:04d}-{nxt.month:02d}"
    current = f"{today.year:04d}-{today.month:02d}"
    with SessionLocal() as db:
        db.add(Invoice(
            organization_id=owner["org_id"], invoice_number="live-1", issue_date=today,
            status=InvoiceStatus.SENT, subtotal=Decimal("100"), tax=Decimal("18"), total=Decimal("118"),
        ))
        db.commit()
    payload = {
        "budgetLines": [
            {"id": "sales-1", "label": "מכירות", "category": "sales", "kind": "revenue",
             "months": {
                 current: {"quantity": 1, "rate": 80},
                 future: {"quantity": 1, "rate": 100},
             }},
            {"id": "rent-1", "label": "שכירות", "category": "rent", "kind": "cost", "months": {}},
        ],
    }
    version = _save_plan(client, owner["headers"], dashboard_id, payload, "null")
    published = client.post(f"/api/dashboards/{dashboard_id}/snapshots", headers=owner["headers"])
    assert published.status_code == 201, published.text
    before = client.get("/api/public/d/budget-live")
    assert before.status_code == 200, before.text
    assert before.json()["source"] == "snapshot"
    assert before.json()["forecast"]["rows"][0]["months"][future]["value"] == 100.0

    payload["budgetLines"][0]["months"][current]["rate"] = 180
    payload["budgetLines"][0]["months"][future]["rate"] = 250
    payload["budgetLines"].append({
        "id": "power-1", "label": "חשמל", "category": "utilities", "kind": "cost",
        "months": {current: {"quantity": 1, "rate": 40}},
    })
    _save_plan(client, owner["headers"], dashboard_id, payload, version)

    public = client.get("/api/public/d/budget-live")
    assert public.status_code == 200, public.text
    body = public.json()
    assert body["source"] == "live"
    forecast = body["forecast"]["rows"][0]["months"][future]
    assert forecast["source"] == "budget" and forecast["value"] == 250.0
    view = client.get(f"/api/dashboards/{dashboard_id}/view", headers=owner["headers"])
    assert view.status_code == 200, view.text
    live = view.json()
    future_row = live["forecast"]["rows"][0]["months"][future]
    assert future_row["value"] == 250.0
    sales = [
        line for month in live["budget_vs_actual"]["months"] if month["month"] == current
        for line in month["categories"] if line["category"] == "sales"
    ]
    assert sales and sales[0]["budget"] == 180.0
    utilities = [
        line for month in live["budget_vs_actual"]["months"] if month["month"] == current
        for line in month["categories"] if line["category"] == "utilities"
    ]
    assert utilities and utilities[0]["budget"] == 40.0
    books_month = next(month for month in live["books_pnl"]["months"] if month["month"] == current)
    assert books_month["budget_revenue"] == 180.0
    assert books_month["budget_costs"] == 40.0
    revision = client.get(f"/api/dashboards/{dashboard_id}/revision", headers=owner["headers"])
    assert revision.status_code == 200, revision.text
    assert revision.json()["plan_version"]
    assert revision.headers["cache-control"] == "private, no-store"


def test_super_admin_with_a_single_active_org_skips_the_chooser(client, platform_admin):
    from cfo.models import Organization

    db = SessionLocal()
    saved = []
    try:
        rows = db.query(Organization).all()
        keep = platform_admin["org_id"]
        for org in rows:
            saved.append((org.id, org.is_active))
            org.is_active = org.id == keep
        db.commit()
        response = client.get("/api/integration/status", headers=platform_admin["headers"])
        assert response.status_code == 200, response.text
        assert response.json()["organization_id"] == keep
    finally:
        for org_id, active in saved:
            org = db.get(Organization, org_id)
            if org is not None:
                org.is_active = active
        db.commit()
        db.close()
