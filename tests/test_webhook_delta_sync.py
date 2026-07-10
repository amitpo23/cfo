"""Tests for M1b — bidirectional webhooks / targeted delta sync.

Covers:
- cfo.services.webhook_delta_sync (pure unit tests, connector/SyncEngine faked)
- the SUMIT webhook route (secret validation + wiring)
- the SUMIT webhook subscribe route (SumitIntegration faked, no live API calls)

No live external API calls are made anywhere in this file.
"""
import asyncio
from datetime import date

import pytest

from cfo.services import webhook_delta_sync as wds


# --------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _reset_debounce():
    """The debounce map is module-level state — isolate tests from each other."""
    wds._last_handled.clear()
    yield
    wds._last_handled.clear()


def _patch_targeted_sync(monkeypatch, calls):
    async def _fake(db, org_id, source, entity_types):
        calls.append((org_id, source, list(entity_types)))
        return {"sync_run_id": 999, "status": "completed", "counts": {}}
    monkeypatch.setattr(wds, "_run_targeted_sync", _fake)


# --------------------------------------------------------------------- #
# handle_open_finance_event
# --------------------------------------------------------------------- #
def test_of_connection_active_triggers_targeted_sync(monkeypatch):
    calls = []
    _patch_targeted_sync(monkeypatch, calls)
    monkeypatch.setattr(wds, "_resolve_of_org", lambda db, payload: 7)

    result = asyncio.run(wds.handle_open_finance_event(None, {
        "connectionId": "conn-1", "connectionStatus": "ACTIVE", "userId": "u1",
    }))

    assert result["handled"] is True
    assert result["event"] == "connection_status"
    assert result["org_id"] == 7
    assert calls == [(7, "open_finance", ["accounts", "bank_transactions"])]


def test_of_connection_completed_also_triggers_sync(monkeypatch):
    calls = []
    _patch_targeted_sync(monkeypatch, calls)
    monkeypatch.setattr(wds, "_resolve_of_org", lambda db, payload: 7)

    result = asyncio.run(wds.handle_open_finance_event(None, {"connectionStatus": "COMPLETED"}))
    assert result["handled"] is True
    assert len(calls) == 1


def test_of_unknown_payload_handled_gracefully():
    assert asyncio.run(wds.handle_open_finance_event(None, {"foo": "bar"})) == {
        "handled": False, "reason": "unrecognized_event_type",
    }
    assert asyncio.run(wds.handle_open_finance_event(None, {}))["handled"] is False
    assert asyncio.run(wds.handle_open_finance_event(None, None))["handled"] is False


def test_of_sync_error_is_swallowed_not_raised(monkeypatch):
    async def _boom(db, org_id, source, entity_types):
        raise ValueError("Open Finance credentials not configured")
    monkeypatch.setattr(wds, "_run_targeted_sync", _boom)
    monkeypatch.setattr(wds, "_resolve_of_org", lambda db, payload: 1)

    result = asyncio.run(wds.handle_open_finance_event(None, {"connectionStatus": "ACTIVE"}))
    assert result["handled"] is False
    assert "error" in result["reason"]


def test_of_debounce(monkeypatch):
    calls = []
    _patch_targeted_sync(monkeypatch, calls)
    monkeypatch.setattr(wds, "_resolve_of_org", lambda db, payload: 7)

    first = asyncio.run(wds.handle_open_finance_event(None, {"connectionStatus": "ACTIVE"}))
    second = asyncio.run(wds.handle_open_finance_event(None, {"connectionStatus": "ACTIVE"}))

    assert first["handled"] is True
    assert second == {"handled": False, "reason": "debounced"}
    assert len(calls) == 1


def test_of_payment_event_recorded_when_match_exists(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Payment

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Payment(
            organization_id=org_id, external_id="of-pay-777", source="open_finance",
            payment_date=date.today(), amount=100, currency="ILS",
        ))
        db.commit()

        import cfo.services.webhook_delta_sync as wds_mod
        # No open_finance IntegrationConnection configured -> resolves to org 1
        # by default, so force the org explicitly for this test.
        orig = wds_mod._resolve_of_org
        wds_mod._resolve_of_org = lambda db_, payload: org_id
        try:
            result = asyncio.run(wds.handle_open_finance_event(db, {
                "paymentId": "of-pay-777", "paymentStatus": "ACCC",
            }))
        finally:
            wds_mod._resolve_of_org = orig

        assert result["handled"] is True
        assert result["matched"] is True

        row = db.query(Payment).filter(Payment.external_id == "of-pay-777").first()
        assert row.raw_data["webhook_event"]["paymentStatus"] == "ACCC"
    finally:
        db.close()


def test_of_payment_event_logged_when_no_match(fresh_org):
    from cfo.database import SessionLocal

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(wds.handle_open_finance_event(db, {
            "paymentId": "no-such-payment", "paymentStatus": "PENDING", "userId": "nope",
        }))
        assert result["handled"] is True
        assert result["matched"] is False
    finally:
        db.close()


def test_of_org_resolution_matches_user_id_else_falls_back_to_org1(monkeypatch, fresh_org):
    """Exercises the real _resolve_of_org (not monkeypatched) to make sure an
    event with no/unmatched userId never gets routed to an arbitrary tenant
    that happens to have an open_finance IntegrationConnection — it must fall
    back to organization 1, per the M1b spec ("else default org 1")."""
    from cfo.database import SessionLocal
    from cfo.models import IntegrationConnection
    from cfo.services.credentials_vault import encrypt_credentials

    org_id = fresh_org()["org_id"]
    of_user_id = f"of-user-resolve-{org_id}"
    db = SessionLocal()
    try:
        db.add(IntegrationConnection(
            organization_id=org_id, source="open_finance", status="active",
            credentials_encrypted=encrypt_credentials({
                "client_id": "cid", "client_secret": "csec", "user_id": of_user_id,
            }),
        ))
        db.commit()

        calls = []
        _patch_targeted_sync(monkeypatch, calls)

        # Matching userId -> resolves to that org.
        result_match = asyncio.run(wds.handle_open_finance_event(db, {
            "connectionStatus": "ACTIVE", "userId": of_user_id,
        }))
        assert result_match["org_id"] == org_id

        wds._last_handled.clear()

        # Missing/unmatched userId -> falls back to org 1, NOT to the org
        # that happens to have a connection configured.
        result_unmatched = asyncio.run(wds.handle_open_finance_event(db, {
            "connectionStatus": "ACTIVE", "userId": "some-other-user",
        }))
        assert result_unmatched["org_id"] == 1
        assert calls == [(org_id, "open_finance", ["accounts", "bank_transactions"]),
                          (1, "open_finance", ["accounts", "bank_transactions"])]
    finally:
        db.close()


# --------------------------------------------------------------------- #
# handle_sumit_trigger_event
# --------------------------------------------------------------------- #
def test_sumit_document_event_triggers_targeted_sync(monkeypatch):
    calls = []
    _patch_targeted_sync(monkeypatch, calls)
    monkeypatch.setattr(wds, "_resolve_sumit_org", lambda db, payload: 3)

    result = asyncio.run(wds.handle_sumit_trigger_event(None, {
        "TriggerType": "CreateOrUpdate", "EntityID": "doc-1",
    }))

    assert result["handled"] is True
    assert result["event"] == "document_change"
    assert calls == [(3, "sumit", ["invoices", "bills", "payments"])]


def test_sumit_event_recognized_by_entity_id_alone(monkeypatch):
    calls = []
    _patch_targeted_sync(monkeypatch, calls)
    monkeypatch.setattr(wds, "_resolve_sumit_org", lambda db, payload: 3)

    result = asyncio.run(wds.handle_sumit_trigger_event(None, {"DocumentID": "123"}))
    assert result["handled"] is True
    assert len(calls) == 1


def test_sumit_org_resolution_matches_company_id_else_falls_back_to_org1(monkeypatch, fresh_org):
    """Mirrors test_of_org_resolution_... for the SUMIT resolver: an
    unmatched/missing CompanyID must fall back to org 1, never to an
    arbitrary tenant that happens to have a sumit IntegrationConnection."""
    from cfo.database import SessionLocal
    from cfo.models import IntegrationConnection
    from cfo.services.credentials_vault import encrypt_credentials

    org_id = fresh_org()["org_id"]
    company_id = f"company-{org_id}"
    db = SessionLocal()
    try:
        db.add(IntegrationConnection(
            organization_id=org_id, source="sumit", status="active",
            credentials_encrypted=encrypt_credentials({
                "api_key": "key", "company_id": company_id,
            }),
        ))
        db.commit()

        calls = []
        _patch_targeted_sync(monkeypatch, calls)

        result_match = asyncio.run(wds.handle_sumit_trigger_event(db, {
            "TriggerType": "Create", "EntityID": "d1", "CompanyID": company_id,
        }))
        assert result_match["org_id"] == org_id

        wds._last_handled.clear()

        result_unmatched = asyncio.run(wds.handle_sumit_trigger_event(db, {
            "TriggerType": "Create", "EntityID": "d2", "CompanyID": "some-other-company",
        }))
        assert result_unmatched["org_id"] == 1
        assert calls == [(org_id, "sumit", ["invoices", "bills", "payments"]),
                          (1, "sumit", ["invoices", "bills", "payments"])]
    finally:
        db.close()


def test_sumit_unknown_payload_handled_gracefully():
    assert asyncio.run(wds.handle_sumit_trigger_event(None, {"foo": "bar"})) == {
        "handled": False, "reason": "unrecognized_event_type",
    }
    assert asyncio.run(wds.handle_sumit_trigger_event(None, {}))["handled"] is False
    assert asyncio.run(wds.handle_sumit_trigger_event(None, None))["handled"] is False


def test_sumit_debounce(monkeypatch):
    calls = []
    _patch_targeted_sync(monkeypatch, calls)
    monkeypatch.setattr(wds, "_resolve_sumit_org", lambda db, payload: 3)

    first = asyncio.run(wds.handle_sumit_trigger_event(None, {"TriggerType": "Create", "EntityID": "d1"}))
    second = asyncio.run(wds.handle_sumit_trigger_event(None, {"TriggerType": "Create", "EntityID": "d2"}))

    assert first["handled"] is True
    assert second == {"handled": False, "reason": "debounced"}
    assert len(calls) == 1


# --------------------------------------------------------------------- #
# route: POST /api/sumit/webhooks
# --------------------------------------------------------------------- #
def test_sumit_webhook_rejects_bad_secret(client, monkeypatch):
    from cfo.api.routes import sumit_webhooks
    monkeypatch.setattr(sumit_webhooks.settings, "sumit_webhook_secret", "correct-secret")

    r = client.post(
        "/api/sumit/webhooks",
        json={"TriggerType": "Create", "EntityID": "d1"},
        headers={"X-Webhook-Secret": "wrong"},
    )
    assert r.status_code == 401


def test_sumit_webhook_accepts_good_secret_and_wires_to_service(client, monkeypatch):
    from cfo.api.routes import sumit_webhooks

    monkeypatch.setattr(sumit_webhooks.settings, "sumit_webhook_secret", "correct-secret")

    captured = {}

    async def _fake_handle(db, payload):
        captured["payload"] = payload
        return {"handled": True, "event": "document_change", "org_id": 1}

    monkeypatch.setattr(sumit_webhooks, "handle_sumit_trigger_event", _fake_handle)

    r = client.post(
        "/api/sumit/webhooks",
        json={"TriggerType": "Create", "EntityID": "d1"},
        headers={"X-Webhook-Secret": "correct-secret"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["received"] is True
    assert body["delta_sync"]["handled"] is True
    assert captured["payload"]["EntityID"] == "d1"


def test_sumit_webhook_no_secret_configured_allows_through(client, monkeypatch):
    from cfo.api.routes import sumit_webhooks
    monkeypatch.setattr(sumit_webhooks.settings, "sumit_webhook_secret", None)

    async def _fake_handle(db, payload):
        return {"handled": False, "reason": "unrecognized_event_type"}
    monkeypatch.setattr(sumit_webhooks, "handle_sumit_trigger_event", _fake_handle)

    r = client.post("/api/sumit/webhooks", json={"foo": "bar"})
    assert r.status_code == 200
    assert r.json()["received"] is True


# --------------------------------------------------------------------- #
# route: POST /api/sumit/webhooks/subscribe
# --------------------------------------------------------------------- #
def test_sumit_webhook_subscribe_requires_auth(client):
    r = client.post("/api/sumit/webhooks/subscribe", json={"target_url": "https://x/webhooks"})
    assert r.status_code == 403


def test_sumit_webhook_subscribe_calls_integration_with_url(client, owner, monkeypatch):
    from cfo.api.routes import sumit_webhooks

    calls = {}

    class _FakeSumit:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def subscribe_trigger(self, trigger_type, webhook_url):
            calls["trigger_type"] = trigger_type
            calls["webhook_url"] = webhook_url
            return {"SubscriptionID": "sub-1"}

    monkeypatch.setattr(sumit_webhooks, "sumit_for_org", lambda db, org_id: _FakeSumit())

    r = client.post(
        "/api/sumit/webhooks/subscribe",
        json={"target_url": "https://example.com/api/sumit/webhooks"},
        headers=owner["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subscribed"] is True
    assert calls["webhook_url"] == "https://example.com/api/sumit/webhooks"
    assert calls["trigger_type"] == "CreateOrUpdate"
    assert body["result"]["SubscriptionID"] == "sub-1"


def test_sumit_webhook_subscribe_requires_target_url(client, owner):
    r = client.post("/api/sumit/webhooks/subscribe", json={}, headers=owner["headers"])
    assert r.status_code == 422


def test_sumit_webhook_subscribe_missing_sumit_key(client, owner, monkeypatch):
    from cfo.api.routes import sumit_webhooks
    monkeypatch.setattr(sumit_webhooks, "sumit_for_org", lambda db, org_id: None)

    r = client.post(
        "/api/sumit/webhooks/subscribe",
        json={"target_url": "https://example.com/webhooks"},
        headers=owner["headers"],
    )
    assert r.status_code == 400
