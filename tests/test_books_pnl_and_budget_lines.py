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


def _division(month, division_id):
    return next(row for row in month["divisions"] if row["id"] == division_id)


def _shared_books(org_id, *, pizza_revenue="600", culinary_revenue="400", shared="200", pizza_cost="50"):
    with SessionLocal() as db:
        db.add(Invoice(
            organization_id=org_id, invoice_number="p", issue_date=date(2026, 8, 2),
            status=InvoiceStatus.SENT, subtotal=Decimal(pizza_revenue), tax=Decimal("0"),
            total=Decimal(pizza_revenue), raw_data={"division": "pizza"},
        ))
        db.add(Invoice(
            organization_id=org_id, invoice_number="c", issue_date=date(2026, 8, 3),
            status=InvoiceStatus.SENT, subtotal=Decimal(culinary_revenue), tax=Decimal("0"),
            total=Decimal(culinary_revenue), raw_data={"division": "culinary"},
        ))
        db.add(Expense(
            organization_id=org_id, supplier_name="פוד גרופ", expense_date=date(2026, 8, 4),
            status="filed", amount=Decimal(shared), vat_amount=Decimal("0"), total=Decimal(shared),
            raw_data={"division": "common"},
        ))
        db.add(Expense(
            organization_id=org_id, supplier_name="פיצה", expense_date=date(2026, 8, 5),
            status="filed", amount=Decimal(pizza_cost), vat_amount=Decimal("0"), total=Decimal(pizza_cost),
            raw_data={"division": "pizza"},
        ))
        db.commit()


def test_shared_costs_stay_unallocated_until_a_month_has_a_key(fresh_org):
    from cfo.services.dashboards.books_pnl import books_pnl

    org_id = fresh_org()["org_id"]
    _shared_books(org_id)
    with SessionLocal() as db:
        report = books_pnl(db, org_id, as_of=AS_OF, months=4)
    august = next(month for month in report["months"] if month["month"] == "2026-08")
    shared = _division(august, "shared")
    pizza = _division(august, "pizza")
    culinary = _division(august, "culinary")
    assert shared["label"] == "עלויות משותפות"
    assert shared["costs"] == 200.0 and shared["remaining"] == 200.0
    assert shared["allocation_applied"] is False
    assert august["shared_allocation"]["applied"] is False
    assert pizza["profit_before_shared"] == 550.0
    assert culinary["profit_before_shared"] == 400.0
    assert pizza["allocated_shared"] is None and culinary["allocated_shared"] is None


def test_manual_and_revenue_share_keys_allocate_the_whole_shared_total(fresh_org):
    from cfo.services.dashboards.books_pnl import books_pnl

    org_id = fresh_org()["org_id"]
    _shared_books(org_id)
    manual = {"sharedCostAllocation": {"2026-08": {"method": "manual", "percentages": {"pizza": 25, "culinary": 75}}}}
    revenue = {"sharedCostAllocation": {"2026-08": {"method": "revenue_share"}}}
    with SessionLocal() as db:
        by_hand = books_pnl(db, org_id, as_of=AS_OF, months=4, plan=manual)
        by_revenue = books_pnl(db, org_id, as_of=AS_OF, months=4, plan=revenue)
        untouched = books_pnl(db, org_id, as_of=AS_OF, months=4, plan={
            "sharedCostAllocation": {"2026-07": {"method": "revenue_share"}},
        })
    august = next(month for month in by_hand["months"] if month["month"] == "2026-08")
    pizza, culinary, shared = _division(august, "pizza"), _division(august, "culinary"), _division(august, "shared")
    assert pizza["profit_before_shared"] == 550.0
    assert pizza["allocated_shared"] == 50.0 and culinary["allocated_shared"] == 150.0
    assert pizza["allocated_shared"] + culinary["allocated_shared"] == shared["costs"]
    assert shared["remaining"] == 0.0 and shared["costs"] == 200.0
    revenue_month = next(month for month in by_revenue["months"] if month["month"] == "2026-08")
    pizza_r, culinary_r = _division(revenue_month, "pizza"), _division(revenue_month, "culinary")
    assert pizza_r["allocated_shared"] == 120.0 and culinary_r["allocated_shared"] == 80.0
    assert pizza_r["allocated_shared"] + culinary_r["allocated_shared"] == 200.0
    from cfo.services.dashboards.books_pnl import validate_shared_cost_allocation
    validate_shared_cost_allocation(manual["sharedCostAllocation"])
    with pytest.raises(ValueError):
        validate_shared_cost_allocation({"2026-08": {"method": "manual", "percentages": {"pizza": 80, "culinary": 30}}})
    # A key for another month does not allocate August, and zero revenue does not become 50/50.
    august_untouched = next(month for month in untouched["months"] if month["month"] == "2026-08")
    assert _division(august_untouched, "shared")["remaining"] == 200.0
    assert _division(august_untouched, "pizza")["allocated_shared"] is None
    org_id = fresh_org()["org_id"]
    _shared_books(org_id, pizza_revenue="0", culinary_revenue="0")
    with SessionLocal() as db:
        empty = books_pnl(db, org_id, as_of=AS_OF, months=4, plan=revenue)
    empty_august = next(month for month in empty["months"] if month["month"] == "2026-08")
    assert empty_august["shared_allocation"]["applied"] is False
    assert _division(empty_august, "shared")["remaining"] == 200.0
    assert _division(empty_august, "pizza")["allocated_shared"] is None


def test_june_keeps_invoice_20055_and_credit_note_2008_when_the_journal_has_them(fresh_org):
    """Documents win, but a journal document number that is not on an invoice is not dropped."""
    from cfo.services.dashboards.books_pnl import books_pnl

    org_id = fresh_org()["org_id"]
    plan = {"journalAccountMap": {"40000": "revenue"}}
    with SessionLocal() as db:
        db.add(Invoice(
            organization_id=org_id, invoice_number="100", issue_date=date(2026, 6, 2),
            status=InvoiceStatus.SENT, subtotal=Decimal("1000"), tax=Decimal("0"), total=Decimal("1000"),
        ))
        db.add(JournalEntry(
            organization_id=org_id, source="reviewed_local_import", external_id="j-20055",
            entry_date=date(2026, 6, 30), memo="חשבונית 20055",
            lines=[
                {"account": "3000", "debit": 70483, "credit": 0},
                {"account": "40000", "debit": 0, "credit": 70483, "reference": "20055"},
            ],
        ))
        db.add(JournalEntry(
            organization_id=org_id, source="reviewed_local_import", external_id="j-2008",
            entry_date=date(2026, 6, 30), memo="זיכוי 2008",
            lines=[
                {"account": "40000", "debit": 11092, "credit": 0, "reference": "2008"},
                {"account": "3000", "debit": 0, "credit": 11092},
            ],
        ))
        db.commit()
        report = books_pnl(db, org_id, start=date(2026, 6, 1), end=date(2026, 6, 30), plan=plan)
    june = report["months"][0]
    assert june["revenue"] == 1000 + 70483 - 11092


def test_seed_payroll_is_the_four_filled_lines_and_the_rest_stay_missing():
    import json
    from pathlib import Path
    from cfo.services.dashboards.budget_fill import seed_status

    seed = json.loads(Path("tests/fixtures/eliav_budget_seed_shape.json").read_text(encoding="utf-8"))
    report = seed_status(seed)
    assert [line["id"] for line in report["filled"]] == ["wage_05", "wage_06", "wage_08", "wage_11"]
    assert report["declared_payroll"]["matches_declared"] is None
    assert report["declared_payroll"]["monthly"] is None
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
    assert any("הכנסות" in label for label in labels)
    assert "sales" not in labels and "materials" not in labels
    january = data["lines"][0]["months"]["2026-01"]
    assert january["status"] == "missing"
    assert january["amount"] is None
    assert january["status_he"] == "חסר, הבעלים יזין"
    assert data["declared_payroll"]["monthly"] is None
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


def test_budget_entry_writes_plan_lines_and_the_dashboard_forecast(client, fresh_org):
    """The amount saved from /budget-entry is on plan.budgetLines, on the budget table, and in the forecast."""
    from cfo.models import Budget

    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "budget-entry-forecast")
    today = date.today()
    nxt = date(today.year + 1, 1, 1) if today.month == 12 else date(today.year, today.month + 1, 1)
    future = f"{nxt.year:04d}-{nxt.month:02d}"
    saved = client.put("/api/financial/budget/lines", headers=owner["headers"], json={"updates": [{
        "id": "sales",
        "label": "מכירות",
        "category": "sales",
        "kind": "revenue",
        "month": future,
        "status": "filled",
        "amount": 3210,
    }]})
    assert saved.status_code == 200, saved.text
    plan = client.get(f"/api/dashboards/{dashboard_id}/plan", headers=owner["headers"])
    assert plan.status_code == 200, plan.text
    lines = plan.json()["payload"]["budgetLines"]
    sales = next(line for line in lines if line["id"] == "sales")
    assert sales["months"][future]["quantity"] == 1
    assert sales["months"][future]["rate"] == 3210
    with SessionLocal() as db:
        row = db.query(Budget).filter_by(
            organization_id=owner["org_id"], year=nxt.year, month=nxt.month, category_name="sales",
        ).one()
        assert float(row.budgeted_amount) == 3210.0
    view = client.get(f"/api/dashboards/{dashboard_id}/view", headers=owner["headers"])
    assert view.status_code == 200, view.text
    forecast = view.json()["forecast"]["rows"][0]["months"][future]
    assert forecast["source"] == "budget"
    assert forecast["value"] == 3210.0


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
