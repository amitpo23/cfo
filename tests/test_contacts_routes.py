"""GET /api/contacts?query=... — search endpoint backing the customer
autocomplete in DocumentManager.tsx (part of the fix for the "customer_id
sent as free-text name" data-integrity bug, see contact_service.py).
"""
from cfo.database import SessionLocal
from cfo.models import Contact, ContactType


def test_search_contacts_route_returns_matches(client, fresh_org):
    iso = fresh_org()
    org_id, headers = iso["org_id"], iso["headers"]
    db = SessionLocal()
    try:
        db.add(Contact(organization_id=org_id, name="Acme Ltd", contact_type=ContactType.CUSTOMER))
        db.commit()
    finally:
        db.close()

    r = client.get("/api/contacts?query=acme", headers=headers)
    assert r.status_code == 200, r.text
    names = [c["name"] for c in r.json()["data"]]
    assert "Acme Ltd" in names


def test_search_contacts_route_is_org_scoped(client, fresh_org):
    org_a = fresh_org()
    org_b = fresh_org()
    db = SessionLocal()
    try:
        db.add(Contact(organization_id=org_a["org_id"], name="Shared Name Ltd", contact_type=ContactType.CUSTOMER))
        db.commit()
    finally:
        db.close()

    r = client.get("/api/contacts?query=Shared", headers=org_b["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["data"] == []


def test_search_contacts_route_requires_auth(client):
    r = client.get("/api/contacts?query=acme")
    assert r.status_code in (401, 403)
