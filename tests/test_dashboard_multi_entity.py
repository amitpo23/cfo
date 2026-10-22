"""One dashboard, more than one organization. No provider calls."""
import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

from cfo.database import SessionLocal
from cfo.models import (
    BankTransaction, ClientDashboard, DashboardEntity, DashboardMember, Invoice,
    InvoiceStatus, SumitCompany, User,
)


def _create(client, headers, org_id, slug):
    response = client.post("/api/dashboards", headers=headers, json={
        "primary_organization_id": org_id,
        "slug": slug,
        "title": "קבוצה",
        "access_mode": "link",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _roster(db, office_id, target_id, name):
    db.add(SumitCompany(
        office_organization_id=office_id,
        company_id=f"file-{target_id}",
        name=name,
        status="active",
        target_organization_id=target_id,
    ))


def _books(db, org_id, revenue, inflow, outflow, description):
    db.add(Invoice(
        organization_id=org_id,
        invoice_number=f"inv-{org_id}",
        issue_date=date(2026, 8, 10),
        status=InvoiceStatus.PAID,
        subtotal=Decimal(revenue),
        tax=Decimal("0"),
        total=Decimal(revenue),
    ))
    if inflow:
        db.add(BankTransaction(
            organization_id=org_id,
            transaction_date=date(2026, 8, 3),
            amount=Decimal(inflow),
            description=description,
        ))
    if outflow:
        db.add(BankTransaction(
            organization_id=org_id,
            transaction_date=date(2026, 8, 4),
            amount=Decimal(outflow),
            description="ספק",
        ))


def test_combined_view_sums_entities_and_nets_intercompany(client, fresh_org):
    chef = fresh_org()
    food = fresh_org()
    office = fresh_org()
    stranger = fresh_org()
    viewer = fresh_org()
    dashboard_id = _create(client, chef["headers"], chef["org_id"], "eliav-two-entities")
    with SessionLocal() as db:
        dashboard = db.get(ClientDashboard, dashboard_id)
        dashboard.office_organization_id = office["org_id"]
        primary = db.query(DashboardEntity).filter_by(dashboard_id=dashboard_id, role="primary").one()
        primary.label = "השף"
        db.add(DashboardEntity(
            dashboard_id=dashboard_id, organization_id=food["org_id"],
            label="פוד גרופ", role="related",
        ))
        _roster(db, office["org_id"], chef["org_id"], "השף")
        _roster(db, office["org_id"], food["org_id"], "פוד גרופ")
        _books(db, chef["org_id"], "100.00", "500.00", None, "תקבול לקוח")
        _books(db, food["org_id"], "40.00", None, "-200.00", "ספק")
        db.add(BankTransaction(
            organization_id=chef["org_id"], transaction_date=date(2026, 8, 15),
            amount=Decimal("1000.00"), description="העברה בין-חברתי לפוד גרופ",
        ))
        db.add(BankTransaction(
            organization_id=food["org_id"], transaction_date=date(2026, 8, 15),
            amount=Decimal("-1000.00"), description="העברה בין-חברתי מהשף",
        ))
        db.add(BankTransaction(
            organization_id=chef["org_id"], transaction_date=date(2026, 8, 16),
            amount=Decimal("50.00"), description="intercompany ללא זוג",
        ))
        viewer_user = db.query(User).filter(User.organization_id == viewer["org_id"]).one()
        db.add(DashboardMember(
            dashboard_id=dashboard_id, user_id=viewer_user.id,
            role="client_viewer", status="active",
        ))
        db.commit()

    denied = client.get(
        f"/api/dashboards/{dashboard_id}/view",
        headers=stranger["headers"],
        params={"start": "2026-08-01", "end": "2026-08-31"},
    )
    assert denied.status_code == 404

    opened = client.get(
        f"/api/dashboards/{dashboard_id}/view",
        headers=viewer["headers"],
        params={"start": "2026-08-01", "end": "2026-08-31"},
    )
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["provider_calls"] == 0
    assert body["office_organization_id"] == office["org_id"]
    assert [entity["label"] for entity in body["entities"]] == ["השף", "פוד גרופ"]
    assert body["entities"][0]["view"]["pnl"]["total_revenue"] == 100
    # Food's books have no costs against a classified supplier payment, so its
    # month is cash basis (#47: one source per month, books must cover the bank).
    food_pnl = body["entities"][1]["view"]["pnl"]
    assert food_pnl["basis"] == "cash_basis"
    assert body["combined"]["pnl"]["status"] == "ready"
    assert body["combined"]["pnl"]["basis"] == "mixed"
    assert body["combined"]["pnl"]["total_revenue"] == round(100 + food_pnl["total_revenue"], 2)
    assert body["combined"]["pnl"]["total_expenses"] == round(
        body["entities"][0]["view"]["pnl"]["total_expenses"] + food_pnl["total_expenses"], 2,
    )
    assert body["combined"]["provider_calls"] == 0
    august = body["combined"]["cashflow"]["months"][0]
    assert august["month"] == "2026-08"
    assert august["inflows"] == 550
    assert august["outflows"] == 200
    removed = body["combined"]["intercompany_removed"]
    assert (removed["pairs"], removed["inflows"], removed["outflows"], removed["amount"]) == (1, 1000.0, 1000.0, 1000.0)
    chef_august = body["entities"][0]["view"]["cashflow"]["months"][0]
    assert chef_august["inflows"] == 1550


def test_entities_from_another_office_are_rejected(client, fresh_org):
    chef = fresh_org()
    food = fresh_org()
    office = fresh_org()
    other_office = fresh_org()
    dashboard_id = _create(client, chef["headers"], chef["org_id"], "eliav-office-mismatch")
    with SessionLocal() as db:
        dashboard = db.get(ClientDashboard, dashboard_id)
        dashboard.office_organization_id = office["org_id"]
        db.add(DashboardEntity(
            dashboard_id=dashboard_id, organization_id=food["org_id"],
            label="פוד גרופ", role="related",
        ))
        _roster(db, office["org_id"], chef["org_id"], "השף")
        _roster(db, other_office["org_id"], food["org_id"], "פוד גרופ")
        db.commit()
    response = client.get(
        f"/api/dashboards/{dashboard_id}/view",
        headers=chef["headers"],
        params={"start": "2026-08-01", "end": "2026-08-31"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "entity_office_mismatch"


def test_shared_classifying_office_allows_the_combined_view(client, fresh_org):
    chef = fresh_org()
    food = fresh_org()
    office = fresh_org()
    dashboard_id = _create(client, chef["headers"], chef["org_id"], "eliav-inferred-office")
    with SessionLocal() as db:
        db.add(DashboardEntity(
            dashboard_id=dashboard_id, organization_id=food["org_id"],
            label="פוד גרופ", role="related",
        ))
        _roster(db, office["org_id"], chef["org_id"], "השף")
        _roster(db, office["org_id"], food["org_id"], "פוד גרופ")
        db.add(Invoice(
            organization_id=food["org_id"],
            invoice_number=f"food-{food['org_id']}",
            issue_date=date(2026, 8, 2),
            status=InvoiceStatus.PAID,
            subtotal=Decimal("7.00"),
            total=Decimal("7.00"),
        ))
        db.commit()
    response = client.get(
        f"/api/dashboards/{dashboard_id}/view",
        headers=chef["headers"],
        params={"start": "2026-08-01", "end": "2026-08-31"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["office_organization_id"] == office["org_id"]
    assert body["combined"]["pnl"]["status"] == "unknown"
    assert body["combined"]["pnl"]["total_revenue"] is None
    food_view = next(entity for entity in body["entities"] if entity["label"] == "פוד גרופ")
    assert food_view["view"]["pnl"]["total_revenue"] == 7


def test_one_entity_keeps_a_single_section(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-one-entity")
    response = client.get(
        f"/api/dashboards/{dashboard_id}/view",
        headers=owner["headers"],
        params={"start": "2026-08-01", "end": "2026-08-31"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["entities"]) == 1
    assert body["entities"][0]["organization_id"] == owner["org_id"]
    assert body["pnl"]["status"] == "unknown"
    assert body["combined"]["pnl"]["status"] == "unknown"
    assert body["combined"]["pnl"]["total_revenue"] is None
    assert body["combined"]["intercompany_removed"]["pairs"] == 0


def test_multi_entity_module_does_not_import_provider_clients():
    path = Path(__file__).resolve().parents[1] / "src/cfo/services/dashboards/multi_entity.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    banned = ("sumit_integration", "financy", "open_finance", "openfinance")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        lowered = " ".join(names).lower()
        assert not any(word in lowered for word in banned)


def _two_entities(db, dashboard_id, office_id, chef_id, food_id):
    dashboard = db.get(ClientDashboard, dashboard_id)
    dashboard.office_organization_id = office_id
    db.add(DashboardEntity(
        dashboard_id=dashboard_id, organization_id=food_id,
        label="פוד גרופ", role="related",
    ))
    _roster(db, office_id, chef_id, "השף")
    _roster(db, office_id, food_id, "פוד גרופ")


def test_intercompany_pairs_use_the_booked_cash_basis(client, fresh_org):
    chef = fresh_org()
    food = fresh_org()
    office = fresh_org()
    dashboard_id = _create(client, chef["headers"], chef["org_id"], "eliav-ic-pending")
    with SessionLocal() as db:
        _two_entities(db, dashboard_id, office["org_id"], chef["org_id"], food["org_id"])
        _books(db, chef["org_id"], "100.00", "500.00", None, "תקבול לקוח")
        # A PENDING twin is not in either entity's cash flow, so it must not be netted.
        db.add(BankTransaction(
            organization_id=chef["org_id"], transaction_date=date(2026, 8, 15),
            amount=Decimal("300.00"), description="העברה בין-חברתי",
            source="open_finance", external_id="of-ic-chef", raw_data={"status": "PENDING"},
        ))
        db.add(BankTransaction(
            organization_id=food["org_id"], transaction_date=date(2026, 8, 15),
            amount=Decimal("-300.00"), description="העברה בין-חברתי",
            source="open_finance", external_id="of-ic-food", raw_data={"status": "PENDING"},
        ))
        db.commit()
    response = client.get(
        f"/api/dashboards/{dashboard_id}/view",
        headers=chef["headers"],
        params={"start": "2026-08-01", "end": "2026-08-31"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["combined"]["intercompany_removed"]["pairs"] == 0
    august = body["combined"]["cashflow"]["months"][0]
    assert august["inflows"] == 500


def test_snapshot_and_public_page_cover_every_entity_without_ids(client, fresh_org):
    chef = fresh_org()
    food = fresh_org()
    office = fresh_org()
    dashboard_id = _create(client, chef["headers"], chef["org_id"], "eliav-two-public")
    client.patch(f"/api/dashboards/{dashboard_id}", headers=chef["headers"],
                 json={"status": "active", "access_mode": "public"})
    with SessionLocal() as db:
        _two_entities(db, dashboard_id, office["org_id"], chef["org_id"], food["org_id"])
        db.commit()
    live = client.get("/api/public/d/eliav-two-public")
    assert live.status_code == 200, live.text
    assert live.json()["source"] == "live"
    assert [entity["label"] for entity in live.json()["entities"]][1:] == ["פוד גרופ"]

    published = client.post(f"/api/dashboards/{dashboard_id}/snapshots", headers=chef["headers"])
    assert published.status_code == 201, published.text
    public = client.get("/api/public/d/eliav-two-public")
    assert public.status_code == 200, public.text
    body = public.json()
    assert body["source"] == "snapshot"
    assert [entity["label"] for entity in body["entities"]][1:] == ["פוד גרופ"]
    assert "combined" in body
    assert "office_organization_id" not in body
    for entity in body["entities"]:
        assert "organization_id" not in entity
        assert all("account_id" not in account for account in entity["accounts"])


def test_closed_months_apply_to_the_primary_entity_only():
    from cfo.services.dashboards.multi_entity import _plan_for
    plan = {"booksClosedMonths": ["2026-08"], "statusRules": [{"id": "r"}]}
    assert _plan_for(plan, True) is plan
    assert _plan_for(plan, False) == {"statusRules": [{"id": "r"}]}
    assert _plan_for(None, False) is None
