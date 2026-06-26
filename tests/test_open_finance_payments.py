"""Webhook persistence for Open Finance payment-status events.

The Payment Status Change webhook carries {paymentId, paymentStatus, userId,
orgId, ...} — no connectionId. We resolve the local organization via the OF
``user_id`` stored in the org's IntegrationConnection credentials, then upsert an
OpenFinancePayment row (idempotent on re-delivery).
"""
import pytest


_of_user_counter = {"n": 0}


@pytest.fixture
def of_org(fresh_org):
    """An isolated org with an Open Finance IntegrationConnection (carrying a
    unique OF user_id) so payment webhooks can be attributed to it.

    Uses ``fresh_org`` rather than the shared ``owner`` org so that seeding an
    open_finance IntegrationConnection here doesn't leak into other files' tests
    that assume the owner org has no OF credentials. Returns the org_id and the
    OF user_id to send in webhook payloads.
    """
    from cfo.database import SessionLocal
    from cfo.models import IntegrationConnection
    from cfo.services.credentials_vault import encrypt_credentials

    _of_user_counter["n"] += 1
    of_user_id = f"of-user-pay-{_of_user_counter['n']}"
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(IntegrationConnection(
            organization_id=org_id,
            source="open_finance",
            status="active",
            credentials_encrypted=encrypt_credentials({
                "client_id": "cid", "client_secret": "csec",
                "user_id": of_user_id,
            }),
        ))
        db.commit()
    finally:
        db.close()
    return {"org_id": org_id, "of_user_id": of_user_id}


def _payment_rows(org_id, external_payment_id):
    from cfo.database import SessionLocal
    from cfo.models import OpenFinancePayment

    db = SessionLocal()
    try:
        return (
            db.query(OpenFinancePayment)
            .filter(
                OpenFinancePayment.organization_id == org_id,
                OpenFinancePayment.external_payment_id == external_payment_id,
            )
            .all()
        )
    finally:
        db.close()


def test_payment_webhook_persists_open_finance_payment(client, of_org):
    org_id = of_org["org_id"]
    payment_id = "of-pay-001"

    r = client.post("/api/open-finance/webhooks", json={
        "paymentId": payment_id,
        "paymentStatus": "PENDING",
        "userId": of_org["of_user_id"],
        "orgId": "of-tenant-999",
        "bankName": "Bank Leumi",
    })
    assert r.status_code == 200, r.text
    assert r.json()["received"] is True

    rows = _payment_rows(org_id, payment_id)
    assert len(rows) == 1
    assert rows[0].status == "PENDING"
    assert rows[0].raw_data["bankName"] == "Bank Leumi"


def test_payment_webhook_is_idempotent_and_updates_status(client, of_org):
    org_id = of_org["org_id"]
    payment_id = "of-pay-002"

    first = client.post("/api/open-finance/webhooks", json={
        "paymentId": payment_id, "paymentStatus": "PENDING", "userId": of_org["of_user_id"],
    })
    assert first.status_code == 200

    second = client.post("/api/open-finance/webhooks", json={
        "paymentId": payment_id, "paymentStatus": "ACCC", "userId": of_org["of_user_id"],
    })
    assert second.status_code == 200

    rows = _payment_rows(org_id, payment_id)
    assert len(rows) == 1, "re-delivery must update, not duplicate"
    assert rows[0].status == "ACCC"


def test_payment_webhook_resolves_org_via_connection_id_fallback(client, fresh_org):
    # Payment events normally omit connectionId, but if one is present and maps
    # to a known BankConnection, the payment is attributed to that org even with
    # no matching OF user_id.
    from cfo.database import SessionLocal
    from cfo.models import BankConnection

    org_id = fresh_org()["org_id"]
    conn_id = "of-conn-pay-link"
    db = SessionLocal()
    try:
        db.add(BankConnection(
            organization_id=org_id, source="open_finance",
            connection_id=conn_id, status="ACTIVE",
        ))
        db.commit()
    finally:
        db.close()

    r = client.post("/api/open-finance/webhooks", json={
        "paymentId": "of-pay-via-conn", "paymentStatus": "ACSC",
        "connectionId": conn_id, "userId": "unmatched-of-user",
    })
    assert r.status_code == 200, r.text

    rows = _payment_rows(org_id, "of-pay-via-conn")
    assert len(rows) == 1
    assert rows[0].status == "ACSC"


def test_payment_webhook_unresolvable_org_is_tolerated(client, of_org):
    # Unknown OF user_id -> cannot attribute to any org -> log-and-skip, still 200.
    r = client.post("/api/open-finance/webhooks", json={
        "paymentId": "of-pay-orphan", "paymentStatus": "PENDING",
        "userId": "no-such-of-user",
    })
    assert r.status_code == 200
    assert r.json()["received"] is True
    assert _payment_rows(of_org["org_id"], "of-pay-orphan") == []
