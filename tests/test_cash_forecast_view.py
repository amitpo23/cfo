"""The 13-week cash forecast inside `/api/dashboards/{id}/view`, and the group
budget that belongs to the combined view only. No provider calls."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, ClientDashboard, SumitCompany


def _create(client, headers, org_id, slug):
    response = client.post("/api/dashboards", headers=headers, json={
        "primary_organization_id": org_id, "slug": slug, "title": "שף אליהב", "access_mode": "link",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _save(client, headers, dashboard_id, payload):
    current = client.get(f"/api/dashboards/{dashboard_id}/plan", headers=headers).json()
    response = client.put(
        f"/api/dashboards/{dashboard_id}/plan",
        headers={**headers, "If-Match": current["version"] or "null"}, json={"payload": payload},
    )
    assert response.status_code == 200, response.text


def _consolidated(client, platform_admin, fresh_org, slug):
    chef, food, office = fresh_org(), fresh_org(), fresh_org()
    dashboard_id = _create(client, platform_admin["headers"], chef["org_id"], slug)
    with SessionLocal() as db:
        db.get(ClientDashboard, dashboard_id).office_organization_id = office["org_id"]
        for org, name in ((chef, "השף"), (food, "פוד גרופ")):
            db.add(SumitCompany(office_organization_id=office["org_id"], company_id=f"file-{org['org_id']}",
                                name=name, status="active", target_organization_id=org["org_id"]))
        db.add(Account(
            organization_id=chef["org_id"], name="עו״ש", account_type=AccountType.BANK,
            raw_account_type="CHECKING", balance=Decimal("-35000"), source="open_finance",
            balance_as_of=datetime.combine(date.today(), datetime.min.time()),
        ))
        db.commit()
    added = client.post(f"/api/dashboards/{dashboard_id}/entities", headers=platform_admin["headers"],
                        json={"organization_id": food["org_id"], "label": "פוד גרופ"})
    assert added.status_code == 201, added.text
    return dashboard_id, chef, food


def _view(client, headers, dashboard_id, end="2026-10-26"):
    response = client.get(f"/api/dashboards/{dashboard_id}/view", headers=headers,
                          params={"start": "2026-07-01", "end": end})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_view_carries_a_13_week_cash_forecast_per_entity_and_combined(client, fresh_org, platform_admin):
    dashboard_id, chef, _food = _consolidated(client, platform_admin, fresh_org, "cash-forecast-13w")
    _save(client, platform_admin["headers"], dashboard_id, {"liquidityEvidence": {"facilities": [
        {"label": "מסגרת עו״ש 8954", "organizationId": chef["org_id"], "limit": 15000},
    ]}})

    body = _view(client, platform_admin["headers"], dashboard_id)

    chef_forecast = body["entities"][0]["view"]["cash_forecast"]
    assert len(chef_forecast["weeks"]) == 13
    assert chef_forecast["weeks"][0]["start"] == date.today().isoformat()
    assert chef_forecast["opening"]["amount"] == -35000.0
    assert chef_forecast["opening"]["as_of"] == date.today().isoformat()
    assert chef_forecast["opening"]["rule"] == "today_position"
    assert chef_forecast["first_breach"]["week_start"] == date.today().isoformat()
    assert "opening_balance" in body["entities"][1]["view"]["cash_forecast"]["missing"]
    combined = body["combined"]["cash_forecast"]
    assert len(combined["weeks"]) == 13
    assert combined["weeks"][0]["closing"] is None  # Food Group's balance is unknown
    assert combined["provider_calls"] == 0


def test_only_the_owner_may_change_cash_forecast_items(client, fresh_org, platform_admin):
    """An owner item moves the forecast's numbers, so it is guarded like the opening
    balance and the liquidity evidence."""
    from tests.test_dashboard_eliav_ui_r2 import _member, _put
    dashboard_id, chef, _food = _consolidated(client, platform_admin, fresh_org, "cash-forecast-items")
    accountant = fresh_org()
    _member(dashboard_id, accountant["org_id"], "accountant")
    item_day = date.today() + timedelta(days=1)
    if item_day.weekday() == 5:
        item_day += timedelta(days=1)
    items = {"cashForecastItems": [
        {"organizationId": chef["org_id"], "date": item_day.isoformat(), "amount": -17000, "label": "חוב לעובדים"},
    ]}

    denied = _put(client, accountant["headers"], dashboard_id, items)
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "cash_forecast_items_forbidden"
    assert _put(client, platform_admin["headers"], dashboard_id, items).status_code == 200

    weeks = _view(client, platform_admin["headers"], dashboard_id)["entities"][0]["view"]["cash_forecast"]["weeks"]
    manual = next(item for week in weeks for item in week["items"] if item["certainty"] == "manual")
    assert (manual["label"], manual["amount"]) == ("חוב לעובדים", -17000.0)


def test_a_cash_forecast_item_needs_an_iso_date_a_nonzero_amount_and_a_label(client, fresh_org, platform_admin):
    from tests.test_dashboard_eliav_ui_r2 import _put
    dashboard_id, chef, _food = _consolidated(client, platform_admin, fresh_org, "cash-forecast-items-bad")
    for bad in (
        {"date": "29/10/2026", "amount": -1, "label": "x"},
        {"date": "2026-10-29", "amount": 0, "label": "x"},
        {"date": "2026-10-29", "amount": "שבעה", "label": "x"},
        {"date": "2026-10-29", "amount": -1, "label": " "},
    ):
        response = _put(client, platform_admin["headers"], dashboard_id,
                        {"cashForecastItems": [dict(bad, organizationId=chef["org_id"])]})
        assert response.status_code == 422, bad


def test_a_group_budget_drives_the_combined_forecast_and_not_one_entity_alone(client, fresh_org, platform_admin):
    """The plan's budget lines carry no entity: they are the group's. Applied to the
    primary entity alone they set one company's costs to the whole group's."""
    dashboard_id, _chef, _food = _consolidated(client, platform_admin, fresh_org, "cash-forecast-budget")
    _save(client, platform_admin["headers"], dashboard_id, {"budgetLines": [
        {"id": "pay", "label": "שכר", "category": "salaries", "kind": "cost",
         "months": {"2026-11": {"quantity": 1, "rate": 40000}}},
    ]})

    body = _view(client, platform_admin["headers"], dashboard_id, end="2026-10-31")

    costs = lambda forecast: next(r for r in forecast["rows"] if r["id"] == "costs")["months"]["2026-11"]
    assert costs(body["combined"]["forecast"]) == {"value": 40000.0, "source": "budget"}
    assert costs(body["entities"][0]["view"]["forecast"])["source"] != "budget"
