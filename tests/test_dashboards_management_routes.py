"""The two reads the dashboards management screen needs beyond the existing API.

Owner request 27/10/2026: dashboards are created and wired from the app, not by
hand. The screen needs (1) the organizations the caller may build a dashboard
for, without the SUPER_ADMIN-only organizations list, and (2) the accounts of an
entity's organization to choose from when binding, checked against dashboard
ownership. No provider calls.
"""
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType


def _create(client, headers, org_id, slug):
    response = client.post("/api/dashboards", headers=headers, json={
        "primary_organization_id": org_id, "slug": slug, "title": "עסק", "access_mode": "members",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _account(org_id, name, account_type=AccountType.BANK, *, raw=None, source="open_finance"):
    with SessionLocal() as db:
        row = Account(organization_id=org_id, name=name, account_type=account_type,
                      raw_account_type=raw, balance=Decimal("0"), source=source)
        db.add(row)
        db.commit()
        return row.id


def test_an_org_admin_sees_their_own_organization_only(client, fresh_org):
    mine, other = fresh_org(), fresh_org()

    response = client.get("/api/dashboards/manageable-organizations", headers=mine["headers"])

    assert response.status_code == 200, response.text
    ids = {row["id"] for row in response.json()["organizations"]}
    assert mine["org_id"] in ids and other["org_id"] not in ids
    assert response.json()["provider_calls"] == 0
    assert all(set(row) == {"id", "name"} for row in response.json()["organizations"])


def test_a_platform_admin_sees_every_active_organization(client, fresh_org, platform_admin):
    org = fresh_org()

    response = client.get("/api/dashboards/manageable-organizations", headers=platform_admin["headers"])

    assert org["org_id"] in {row["id"] for row in response.json()["organizations"]}


def test_the_owner_lists_the_bank_and_card_accounts_with_their_binding(client, fresh_org):
    """Bank and card accounts only: a SUMIT chart of accounts holds hundreds of
    ledger accounts that liquidity never reads."""
    org = fresh_org()
    dashboard_id = _create(client, org["headers"], org["org_id"], "mgmt-accounts")
    bank = _account(org["org_id"], "עו״ש")
    card = _account(org["org_id"], "כרטיס", AccountType.LIABILITY, raw="CARD")
    _account(org["org_id"], "הוצאות משרד", AccountType.EXPENSE, source="sumit")
    entity_id = client.get(f"/api/dashboards/{dashboard_id}/entities",
                           headers=org["headers"]).json()["entities"][0]["id"]
    assert client.put(f"/api/dashboards/{dashboard_id}/entities/{entity_id}/accounts", headers=org["headers"],
                      json={"accounts": [{"account_id": bank}]}).status_code == 200

    response = client.get(f"/api/dashboards/{dashboard_id}/entities/{entity_id}/available-accounts",
                          headers=org["headers"])

    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()["accounts"]}
    assert set(rows) == {bank, card}
    assert rows[bank]["bound"] is True and rows[card]["bound"] is False
    assert rows[card]["kind"] == "card" and rows[bank]["kind"] == "other"
    assert response.json()["provider_calls"] == 0


def test_another_organization_cannot_list_the_accounts(client, fresh_org):
    org, stranger = fresh_org(), fresh_org()
    dashboard_id = _create(client, org["headers"], org["org_id"], "mgmt-stranger")
    _account(org["org_id"], "עו״ש")
    entity_id = client.get(f"/api/dashboards/{dashboard_id}/entities",
                           headers=org["headers"]).json()["entities"][0]["id"]

    response = client.get(f"/api/dashboards/{dashboard_id}/entities/{entity_id}/available-accounts",
                          headers=stranger["headers"])

    assert response.status_code == 404


def test_an_entity_of_another_dashboard_is_not_found(client, fresh_org):
    org = fresh_org()
    first = _create(client, org["headers"], org["org_id"], "mgmt-first")
    second = _create(client, org["headers"], org["org_id"], "mgmt-second")
    entity_of_second = client.get(f"/api/dashboards/{second}/entities",
                                  headers=org["headers"]).json()["entities"][0]["id"]

    response = client.get(f"/api/dashboards/{first}/entities/{entity_of_second}/available-accounts",
                          headers=org["headers"])

    assert response.status_code == 404
