"""M2c — in-Rezef Open Finance bank-connection journey (multi-business onboarding).

Covers:
  * ensure_of_identity: idempotent, org-scoped userId provisioning; org 1
    (pilot) is left alone when its stored credentials are empty.
  * start_bank_connection: calls create_connection with allowBusiness=True
    and persists the returned connection id.
  * get_connection_status: honest status proxy, including the
    PARTIALLY_AUTHORIZED shared-account explanation.
  * routes: /open-finance/onboarding/start and /open-finance/onboarding/status/{id}.
  * credentials resolution: client_id/client_secret may fall back to env for
    ANY org; user_id only falls back to env for org 1.
"""
import pytest

from cfo.database import SessionLocal
from cfo.models import IntegrationConnection
from cfo.services.credentials_vault import decrypt_credentials, encrypt_credentials


# ------------------------------------------------------------------ #
# ensure_of_identity
# ------------------------------------------------------------------ #
def test_ensure_of_identity_sets_org_scoped_user_id(fresh_org):
    from cfo.services.open_finance_onboarding import ensure_of_identity

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        conn = ensure_of_identity(db, org_id)
        creds = decrypt_credentials(conn.credentials_encrypted)
        assert creds["user_id"] == f"rezef-org-{org_id}"
        assert conn.status == "active"
    finally:
        db.close()


def test_ensure_of_identity_is_idempotent(fresh_org):
    from cfo.services.open_finance_onboarding import ensure_of_identity

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        conn1 = ensure_of_identity(db, org_id)
        conn_id = conn1.id
        user_id_1 = decrypt_credentials(conn1.credentials_encrypted)["user_id"]

        conn2 = ensure_of_identity(db, org_id)
        assert conn2.id == conn_id
        assert decrypt_credentials(conn2.credentials_encrypted)["user_id"] == user_id_1

        # Row count stays exactly one.
        count = (
            db.query(IntegrationConnection)
            .filter(
                IntegrationConnection.organization_id == org_id,
                IntegrationConnection.source == "open_finance",
            )
            .count()
        )
        assert count == 1
    finally:
        db.close()


def test_ensure_of_identity_leaves_org1_with_empty_credentials_alone(owner):
    from cfo.services.open_finance_onboarding import ensure_of_identity

    org_id = owner["user"]["organization_id"]
    assert org_id == 1
    # `owner` (org 1) is a session-scoped fixture shared with every other test
    # file — mutate its IntegrationConnection state only within this test and
    # restore it exactly afterward so we don't leak an "active open_finance
    # connection" into unrelated integration-status assertions elsewhere.
    db = SessionLocal()
    try:
        conn = (
            db.query(IntegrationConnection)
            .filter(
                IntegrationConnection.organization_id == org_id,
                IntegrationConnection.source == "open_finance",
            )
            .first()
        )
        original_existed = conn is not None
        original_status = conn.status if conn else None
        original_creds = conn.credentials_encrypted if conn else None

        empty_creds = encrypt_credentials({})
        if conn is None:
            conn = IntegrationConnection(
                organization_id=org_id, source="open_finance", status="active",
                credentials_encrypted=empty_creds,
            )
            db.add(conn)
            db.commit()
        else:
            conn.credentials_encrypted = empty_creds
            db.commit()

        try:
            result = ensure_of_identity(db, org_id)
            creds = decrypt_credentials(result.credentials_encrypted)
            # Env fallback covers org 1 — no user_id should be injected.
            assert "user_id" not in creds
        finally:
            if original_existed:
                conn.status = original_status
                conn.credentials_encrypted = original_creds
                db.commit()
            else:
                db.delete(conn)
                db.commit()
    finally:
        db.close()


# ------------------------------------------------------------------ #
# start_bank_connection / get_connection_status
# ------------------------------------------------------------------ #
@pytest.fixture
def platform_creds(monkeypatch):
    """Simulate shared platform client_id/client_secret available via env for
    any org (the M2c model) — see get_open_finance_client."""
    import cfo.config as config_module

    monkeypatch.setattr(config_module.settings, "open_finance_client_id", "platform-client-id")
    monkeypatch.setattr(config_module.settings, "open_finance_client_secret", "platform-client-secret")


def test_start_bank_connection_returns_connect_url_and_persists_id(fresh_org, platform_creds, monkeypatch):
    from cfo.services.open_finance_client import OpenFinanceClient
    from cfo.services.open_finance_onboarding import start_bank_connection

    org_id = fresh_org()["org_id"]

    captured = {}

    async def fake_create_connection(self, body):
        captured["body"] = body
        return {"id": "conn-onb-1", "connectUrl": "https://consent.example.com/conn-onb-1"}

    monkeypatch.setattr(OpenFinanceClient, "create_connection", fake_create_connection)

    import asyncio

    async def _run():
        db = SessionLocal()
        try:
            return await start_bank_connection(db, org_id, psu_id="123456789")
        finally:
            db.close()

    result = asyncio.run(_run())
    assert result == {"connection_id": "conn-onb-1", "connect_url": "https://consent.example.com/conn-onb-1"}
    assert captured["body"]["allowBusiness"] is True
    assert captured["body"]["psuId"] == "123456789"

    db = SessionLocal()
    try:
        conn = (
            db.query(IntegrationConnection)
            .filter(
                IntegrationConnection.organization_id == org_id,
                IntegrationConnection.source == "open_finance",
            )
            .first()
        )
        creds = decrypt_credentials(conn.credentials_encrypted)
        assert creds["user_id"] == f"rezef-org-{org_id}"
        assert "conn-onb-1" in creds["of_connection_ids"]
    finally:
        db.close()


def test_get_connection_status_proxies_and_explains_partially_authorized(fresh_org, platform_creds, monkeypatch):
    from cfo.services.open_finance_client import OpenFinanceClient
    from cfo.services.open_finance_onboarding import ensure_of_identity, get_connection_status
    import asyncio

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        ensure_of_identity(db, org_id)
    finally:
        db.close()

    async def fake_get_connection(self, connection_id):
        assert connection_id == "conn-onb-2"
        return {
            "id": connection_id,
            "status": "PARTIALLY_AUTHORIZED",
            "providerFriendlyId": "leumi",
            "expiryDate": "2029-01-01",
            "accounts": [{"id": "acc-1"}],
            "lastRefreshAt": "2026-07-01T00:00:00Z",
        }

    monkeypatch.setattr(OpenFinanceClient, "get_connection", fake_get_connection)

    async def _run():
        db = SessionLocal()
        try:
            return await get_connection_status(db, org_id, "conn-onb-2")
        finally:
            db.close()

    result = asyncio.run(_run())
    assert result["status"] == "PARTIALLY_AUTHORIZED"
    assert result["provider"] == "leumi"
    assert result["expiry"] == "2029-01-01"
    assert result["accounts"] == [{"id": "acc-1"}]
    assert "explanation" in result and "משותף" in result["explanation"]


# ------------------------------------------------------------------ #
# routes
# ------------------------------------------------------------------ #
def test_onboarding_start_route_org_scoped(client, fresh_org, platform_creds, monkeypatch):
    from cfo.services.open_finance_client import OpenFinanceClient

    org = fresh_org()

    async def fake_create_connection(self, body):
        return {"id": "conn-route-1", "connectUrl": "https://consent.example.com/conn-route-1"}

    monkeypatch.setattr(OpenFinanceClient, "create_connection", fake_create_connection)

    r = client.post(
        "/api/open-finance/onboarding/start", json={"language": "he"},
        headers=org["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connection_id"] == "conn-route-1"
    assert body["connect_url"] == "https://consent.example.com/conn-route-1"


def test_onboarding_status_route_org_scoped(client, fresh_org, platform_creds, monkeypatch):
    from cfo.services.open_finance_client import OpenFinanceClient
    from cfo.services.open_finance_onboarding import ensure_of_identity

    org = fresh_org()
    db = SessionLocal()
    try:
        ensure_of_identity(db, org["org_id"])
    finally:
        db.close()

    async def fake_get_connection(self, connection_id):
        return {"id": connection_id, "status": "ACTIVE", "providerFriendlyId": "hapoalim"}

    monkeypatch.setattr(OpenFinanceClient, "get_connection", fake_get_connection)

    r = client.get(
        "/api/open-finance/onboarding/status/conn-route-2",
        headers=org["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ACTIVE"
    assert r.json()["provider"] == "hapoalim"


def test_onboarding_routes_require_auth(client):
    assert client.post("/api/open-finance/onboarding/start", json={}).status_code == 403
    assert client.get("/api/open-finance/onboarding/status/x").status_code == 403


# ------------------------------------------------------------------ #
# credentials resolution: client_id/secret env-fallback for ANY org;
# user_id env-fallback only for org 1.
# ------------------------------------------------------------------ #
def test_client_id_secret_fall_back_to_env_for_non_default_org_but_user_id_does_not(fresh_org, monkeypatch):
    import cfo.config as config_module
    from cfo.api.routes.open_finance import get_open_finance_client
    from fastapi import HTTPException

    monkeypatch.setattr(config_module.settings, "open_finance_client_id", "env-client-id")
    monkeypatch.setattr(config_module.settings, "open_finance_client_secret", "env-client-secret")
    # Even with a env USER_ID present, a non-default org without its own
    # stored user_id must NOT pick it up (cross-tenant credential leak).
    monkeypatch.setattr(config_module.settings, "open_finance_user_id", "env-leaked-user-id")

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        with pytest.raises(HTTPException) as exc_info:
            get_open_finance_client(db, org_id)
        assert "OPEN_FINANCE_USER_ID" in exc_info.value.detail
    finally:
        db.close()


def test_org_with_stored_user_id_and_env_client_creds_works(fresh_org, monkeypatch):
    import cfo.config as config_module
    from cfo.api.routes.open_finance import get_open_finance_client
    from cfo.services.open_finance_onboarding import ensure_of_identity

    monkeypatch.setattr(config_module.settings, "open_finance_client_id", "env-client-id")
    monkeypatch.setattr(config_module.settings, "open_finance_client_secret", "env-client-secret")
    monkeypatch.setattr(config_module.settings, "open_finance_user_id", None)

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        ensure_of_identity(db, org_id)
        client = get_open_finance_client(db, org_id)
        assert client.client_id == "env-client-id"
        assert client.client_secret == "env-client-secret"
        assert client.user_id == f"rezef-org-{org_id}"
    finally:
        db.close()


def test_get_connector_for_org_mirrors_the_same_creds_split(fresh_org, monkeypatch):
    """sync_engine.get_connector_for_org has the identical env_allowed split as
    get_open_finance_client — client_id/client_secret fall back to env for any
    org, but user_id only falls back to env for org 1. Locks in both halves:
    the leak-blocked failure case and the working non-default-org case."""
    import cfo.config as config_module
    from cfo.services.sync_engine import get_connector_for_org
    from cfo.services.open_finance_onboarding import ensure_of_identity

    monkeypatch.setattr(config_module.settings, "open_finance_client_id", "env-client-id")
    monkeypatch.setattr(config_module.settings, "open_finance_client_secret", "env-client-secret")
    monkeypatch.setattr(config_module.settings, "open_finance_user_id", "env-leaked-user-id")

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        # No stored user_id yet -> must not leak the env value.
        with pytest.raises(ValueError) as exc_info:
            get_connector_for_org(db, org_id, "open_finance")
        assert "OPEN_FINANCE_USER_ID" in str(exc_info.value)

        # Once the org has its own onboarded identity, the shared env
        # client_id/client_secret are enough to build a working connector.
        ensure_of_identity(db, org_id)
        connector, _conn_id, source = get_connector_for_org(db, org_id, "open_finance")
        assert source == "open_finance"
        assert connector.client.client_id == "env-client-id"
        assert connector.user_id == f"rezef-org-{org_id}"
    finally:
        db.close()
