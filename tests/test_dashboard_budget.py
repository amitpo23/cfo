"""Dashboard budget entry and the budget-vs-actual section. No provider calls."""
from datetime import date, datetime
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import (
    AuditLog, Bill, BillStatus, Budget, Category, DashboardMember, Expense, Invoice,
    InvoiceStatus, PublishedSnapshot, User,
)

START = "2026-03-01"
END = "2026-04-30"


def _create(client, headers, org_id, slug):
    response = client.post("/api/dashboards", headers=headers, json={
        "primary_organization_id": org_id, "slug": slug, "title": "תקציב",
        "access_mode": "link",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _put(client, headers, dashboard_id, rows):
    return client.put(f"/api/dashboards/{dashboard_id}/budget", headers=headers, json={"rows": rows})


def _view(client, headers, dashboard_id, start=START, end=END):
    response = client.get(
        f"/api/dashboards/{dashboard_id}/view", headers=headers,
        params={"start": start, "end": end},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _add_member(dashboard_id, org_id, role):
    with SessionLocal() as db:
        user = db.query(User).filter(User.organization_id == org_id).one()
        db.add(DashboardMember(dashboard_id=dashboard_id, user_id=user.id, role=role, status="active"))
        db.commit()


def _books(org_id):
    """March: invoice 1000, bill 300, a filed expense that echoes the bill, a marketing expense 200,
    an uncategorized expense 50, a pending expense that must not count. April: invoice 500."""
    with SessionLocal() as db:
        db.add_all([
            Invoice(organization_id=org_id, invoice_number="b-1", issue_date=date(2026, 3, 5),
                    status=InvoiceStatus.SENT, subtotal=Decimal("1000"), tax=Decimal("180"),
                    total=Decimal("1180")),
            Invoice(organization_id=org_id, invoice_number="b-2", issue_date=date(2026, 4, 9),
                    status=InvoiceStatus.PAID, subtotal=Decimal("500"), tax=Decimal("90"),
                    total=Decimal("590")),
            Bill(organization_id=org_id, external_id="dup-77", bill_number="s-1",
                 issue_date=date(2026, 3, 10), status=BillStatus.RECEIVED,
                 subtotal=Decimal("300"), tax=Decimal("54"), total=Decimal("354")),
            Expense(organization_id=org_id, external_id="dup-77", supplier_name="ספק",
                    expense_date=date(2026, 3, 10), status="filed", category="rent",
                    amount=Decimal("300"), vat_amount=Decimal("54"), total=Decimal("354")),
            Expense(organization_id=org_id, supplier_name="פרסום", expense_date=date(2026, 3, 12),
                    status="filed", category="marketing", amount=Decimal("200"),
                    vat_amount=Decimal("36"), total=Decimal("236")),
            Expense(organization_id=org_id, supplier_name="שונות", expense_date=date(2026, 3, 20),
                    status="filed", category=None, amount=Decimal("50"),
                    vat_amount=Decimal("0"), total=Decimal("50")),
            Expense(organization_id=org_id, supplier_name="טיוטה", expense_date=date(2026, 3, 21),
                    status="pending", category="marketing", amount=Decimal("999"),
                    vat_amount=Decimal("0"), total=Decimal("999")),
        ])
        db.commit()


def _line(month, kind, category):
    matches = [c for c in month["categories"] if c["kind"] == kind and c["category"] == category]
    assert len(matches) == 1, month["categories"]
    return matches[0]


def test_owner_upserts_budget_rows_and_writes_an_audit_row(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "budget-upsert")
    first = _put(client, owner["headers"], dashboard_id, [
        {"year": 2026, "month": 3, "category": "marketing", "budgeted_amount": 150, "notes": "קמפיין"},
        {"year": 2026, "month": 3, "category": "מכירות", "budgeted_amount": 900},
    ])
    assert first.status_code == 200, first.text
    assert first.json()["saved"] == 2
    assert first.json()["provider_calls"] == 0
    # The Hebrew label and the code are the same category: this updates, not inserts.
    second = _put(client, owner["headers"], dashboard_id, [
        {"year": 2026, "month": 3, "category": "שיווק ופרסום", "budgeted_amount": 250.5},
    ])
    assert second.status_code == 200, second.text
    with SessionLocal() as db:
        rows = db.query(Budget).filter_by(organization_id=owner["org_id"]).all()
        assert len(rows) == 2
        marketing = next(r for r in rows if r.category_name == "marketing")
        assert marketing.budgeted_amount == Decimal("250.50")
        assert marketing.notes is None
        audits = db.query(AuditLog).filter_by(
            organization_id=owner["org_id"], action="UPSERT_DASHBOARD_BUDGET",
        ).all()
        assert len(audits) == 2
        assert audits[0].details["provider_calls"] == 0
    listed = client.get(f"/api/dashboards/{dashboard_id}/budget", headers=owner["headers"],
                        params={"year": 2026})
    assert listed.status_code == 200, listed.text
    by_category = {r["category"]: r for r in listed.json()["rows"]}
    assert by_category["marketing"]["budgeted_amount"] == 250.5
    assert by_category["sales"]["kind"] == "revenue"
    assert by_category["marketing"]["kind"] == "cost"


def test_category_id_must_belong_to_the_dashboard_org(client, fresh_org):
    owner = fresh_org()
    other = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "budget-catid")
    with SessionLocal() as db:
        mine = Category(organization_id=owner["org_id"], name="rent", category_type="expense")
        theirs = Category(organization_id=other["org_id"], name="rent", category_type="expense")
        db.add_all([mine, theirs])
        db.commit()
        mine_id, theirs_id = mine.id, theirs.id
    foreign = _put(client, owner["headers"], dashboard_id, [
        {"year": 2026, "month": 3, "category_id": theirs_id, "budgeted_amount": 10},
    ])
    assert foreign.status_code == 422
    ok = _put(client, owner["headers"], dashboard_id, [
        {"year": 2026, "month": 3, "category_id": mine_id, "budgeted_amount": 10},
    ])
    assert ok.status_code == 200, ok.text
    with SessionLocal() as db:
        assert db.query(Budget).filter_by(organization_id=other["org_id"]).count() == 0
        assert db.query(Budget).filter_by(organization_id=owner["org_id"], category_id=mine_id).count() == 1


def test_only_the_owner_writes_and_readers_may_read(client, fresh_org):
    owner = fresh_org()
    viewer = fresh_org()
    stranger = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "budget-auth")
    _add_member(dashboard_id, viewer["org_id"], "client_viewer")
    row = [{"year": 2026, "month": 3, "category": "marketing", "budgeted_amount": 100}]
    denied = _put(client, viewer["headers"], dashboard_id, row)
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "not_found"
    hidden = _put(client, stranger["headers"], dashboard_id, row)
    assert hidden.status_code == 404
    assert client.get(f"/api/dashboards/{dashboard_id}/budget", headers=stranger["headers"]).status_code == 404
    readable = client.get(f"/api/dashboards/{dashboard_id}/budget", headers=viewer["headers"])
    assert readable.status_code == 200, readable.text
    assert readable.json()["rows"] == []
    unauthenticated = client.put(f"/api/dashboards/{dashboard_id}/budget", json={"rows": row})
    assert unauthenticated.status_code in (401, 403)
    with SessionLocal() as db:
        assert db.query(Budget).filter_by(organization_id=owner["org_id"]).count() == 0


@pytest.mark.parametrize("row", [
    {"year": 2026, "month": 0, "category": "rent", "budgeted_amount": 1},
    {"year": 2026, "month": 13, "category": "rent", "budgeted_amount": 1},
    {"year": 2026, "month": 3, "category": "rent", "budgeted_amount": -1},
    {"year": 2026, "month": 3, "category": "rent", "budgeted_amount": "abc"},
    {"year": 2026, "month": 3, "category": "rent", "budgeted_amount": "inf"},
    {"year": 2026, "month": 3, "category": "rent", "budgeted_amount": 1e13},
    {"year": 2026, "month": 3, "category": "   ", "budgeted_amount": 1},
    {"year": 2026, "month": 3, "budgeted_amount": 1},
    {"year": 2026, "month": 3, "category": "rent", "budgeted_amount": 1, "owner_id": 5},
])
def test_invalid_rows_are_rejected_and_nothing_is_written(client, fresh_org, row):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], f"budget-bad-{owner['org_id']}")
    good = {"year": 2026, "month": 4, "category": "rent", "budgeted_amount": 5}
    response = _put(client, owner["headers"], dashboard_id, [good, row])
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.query(Budget).filter_by(organization_id=owner["org_id"]).count() == 0


def test_duplicate_category_in_one_request_is_rejected(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "budget-dupe")
    response = _put(client, owner["headers"], dashboard_id, [
        {"year": 2026, "month": 3, "category": "marketing", "budgeted_amount": 1},
        {"year": 2026, "month": 3, "category": "שיווק ופרסום", "budgeted_amount": 2},
    ])
    assert response.status_code == 422


def test_actuals_match_the_pnl_and_missing_budget_is_null(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "budget-actuals")
    _books(owner["org_id"])
    saved = _put(client, owner["headers"], dashboard_id, [
        {"year": 2026, "month": 3, "category": "marketing", "budgeted_amount": 250},
        {"year": 2026, "month": 3, "category": "sales", "budgeted_amount": 800},
        {"year": 2026, "month": 3, "category": "rent", "budgeted_amount": 0},
        {"year": 2026, "month": 4, "category": "insurance", "budgeted_amount": 40},
    ])
    assert saved.status_code == 200, saved.text
    body = _view(client, owner["headers"], dashboard_id)
    section = body["budget_vs_actual"]
    assert section["status"] == "ready"
    assert section["has_budget"] is True
    march, april = section["months"]
    assert (march["month"], april["month"]) == ("2026-03", "2026-04")

    # The bill and the expense that echoes it count once (P&L rule), under the bill's bucket.
    uncategorized = _line(march, "cost", "other")
    assert uncategorized["category_he"] == "לא מסווג"
    assert uncategorized["actual"] == 350.0
    assert uncategorized["budget"] is None
    assert uncategorized["variance"] is None and uncategorized["variance_pct"] is None
    assert not [c for c in march["categories"] if c["category"] == "rent" and c["actual"]]

    marketing = _line(march, "cost", "marketing")
    assert marketing["actual"] == 200.0  # the pending 999 does not count
    assert marketing["budget"] == 250.0
    assert marketing["variance"] == -50.0
    assert marketing["variance_pct"] == -20.0

    rent = _line(march, "cost", "rent")
    assert rent["budget"] == 0.0 and rent["actual"] == 0.0
    assert rent["variance"] == 0.0 and rent["variance_pct"] is None

    sales = _line(march, "revenue", "sales")
    assert (sales["budget"], sales["actual"], sales["variance"], sales["variance_pct"]) == (
        800.0, 1000.0, 200.0, 25.0,
    )
    assert march["totals"]["revenue"] == {
        "budget": 800.0, "actual": 1000.0, "variance": 200.0, "variance_pct": 25.0,
    }
    assert march["totals"]["costs"]["budget"] == 250.0
    assert march["totals"]["costs"]["actual"] == 550.0

    # April has no revenue budget: the total budget is null, not 0.
    assert april["totals"]["revenue"]["budget"] is None
    assert april["totals"]["revenue"]["actual"] == 500.0
    assert april["totals"]["revenue"]["variance"] is None
    assert _line(april, "cost", "insurance")["actual"] == 0.0

    pnl = body["pnl"]
    assert sum(m["totals"]["revenue"]["actual"] for m in section["months"]) == pytest.approx(pnl["total_revenue"])
    assert sum(m["totals"]["costs"]["actual"] for m in section["months"]) == pytest.approx(pnl["total_expenses"])


def test_window_edges_are_clamped_to_the_view_range(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "budget-clamp")
    _books(owner["org_id"])
    body = _view(client, owner["headers"], dashboard_id, start="2026-03-11", end="2026-04-08")
    march, april = body["budget_vs_actual"]["months"]
    assert march["period_start"] == "2026-03-11" and april["period_end"] == "2026-04-08"
    assert march["totals"]["revenue"]["actual"] == 0.0
    assert april["totals"]["revenue"]["actual"] == 0.0
    assert march["totals"]["costs"]["actual"] == pytest.approx(body["pnl"]["total_expenses"])


def test_no_books_means_unknown_actual_not_zero(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "budget-nobooks")
    _put(client, owner["headers"], dashboard_id, [
        {"year": 2026, "month": 3, "category": "marketing", "budgeted_amount": 100},
    ])
    section = _view(client, owner["headers"], dashboard_id)["budget_vs_actual"]
    assert section["status"] == "unknown"
    line = _line(section["months"][0], "cost", "marketing")
    assert line["budget"] == 100.0
    assert line["actual"] is None and line["variance"] is None
    assert section["months"][1]["categories"] == []
    assert section["months"][1]["totals"]["costs"]["budget"] is None


def test_published_snapshot_carries_the_section_and_stays_redacted(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "budget-public")
    client.patch(f"/api/dashboards/{dashboard_id}", headers=owner["headers"],
                 json={"status": "active", "access_mode": "public"})
    today = date.today()
    with SessionLocal() as db:
        db.add(Invoice(organization_id=owner["org_id"], invoice_number="pub-1", issue_date=today,
                       status=InvoiceStatus.SENT, subtotal=Decimal("100"), total=Decimal("100")))
        db.commit()
    saved = _put(client, owner["headers"], dashboard_id, [
        {"year": today.year, "month": today.month, "category": "sales",
         "budgeted_amount": 80.25, "notes": "הערה פנימית של רואה החשבון"},
    ])
    assert saved.status_code == 200, saved.text
    published = client.post(f"/api/dashboards/{dashboard_id}/snapshots", headers=owner["headers"])
    assert published.status_code == 201, published.text
    public = client.get("/api/public/d/budget-public")
    assert public.status_code == 200, public.text
    body = public.json()
    assert body["source"] == "snapshot"
    current = body["budget_vs_actual"]["months"][-1]
    sales = _line(current, "revenue", "sales")
    assert sales["budget"] == 80.25 and sales["actual"] == 100.0
    assert "הערה פנימית" not in public.text
    assert "notes" not in public.text


def test_public_redaction_strips_ids_planted_in_a_snapshot(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "budget-leaky")
    client.patch(f"/api/dashboards/{dashboard_id}", headers=owner["headers"],
                 json={"status": "active", "access_mode": "public"})
    leaky = {
        "status": "ready",
        "cashflow": {"months": []},
        "pnl": {"status": "unknown"},
        "budget_vs_actual": {
            "status": "ready", "has_budget": True, "organization_id": 514002099,
            "months": [{
                "month": "2026-03", "period_start": "2026-03-01", "period_end": "2026-03-31",
                "categories": [{
                    "kind": "cost", "category": "rent", "category_he": "שכירות",
                    "budget": 10.0, "actual": 12.0, "variance": 2.0, "variance_pct": 20.0,
                    "budget_id": 9001, "category_id": 4242, "notes": "staff note",
                    "updated_by": "accountant@example.com",
                }],
                "totals": {"revenue": {"budget": None, "actual": 0.0, "variance": None,
                                       "variance_pct": None, "user_id": 77},
                           "costs": {"budget": 10.0, "actual": 12.0, "variance": 2.0,
                                     "variance_pct": 20.0}},
            }],
        },
        "provider_calls": 0,
        "freshness": {"published": True},
    }
    with SessionLocal() as db:
        from cfo.models import ClientDashboard
        snap = PublishedSnapshot(
            dashboard_id=dashboard_id, refreshed_day=date.today(), snapshot_at=datetime.utcnow(),
            view_model=leaky, freshness={"published": True}, content_sha256="b" * 64,
            provider_calls=0,
        )
        db.add(snap)
        db.flush()
        db.get(ClientDashboard, dashboard_id).current_snapshot_id = snap.id
        db.commit()
    public = client.get("/api/public/d/budget-leaky")
    assert public.status_code == 200, public.text
    line = public.json()["budget_vs_actual"]["months"][0]["categories"][0]
    assert line == {
        "kind": "cost", "category": "rent", "category_he": "שכירות",
        "budget": 10.0, "actual": 12.0, "variance": 2.0, "variance_pct": 20.0,
    }
    for secret in ("514002099", "9001", "4242", "staff note", "accountant@example.com",
                   "organization_id", "category_id", "user_id", "budget_id"):
        assert secret not in public.text
