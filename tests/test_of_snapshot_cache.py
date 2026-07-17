"""RSF-030 — read paths must not trigger live Open Finance calls.

Policy (owner, 2026-07-17): Open Finance data syncs into our own Postgres
once daily; analytics/UI/bot read from OUR database. Live calls are allowed
only for the scheduled sync, an explicit cooldown-gated user refresh, or
writes. These tests cover the shared cache primitive
(`services/of_snapshot_service.get_or_fetch`) plus the two routes
(`/accounts`, `/transactions`) that were rewired to read our DB directly and
must never construct an Open Finance client at all.

Async calls use `asyncio.run(...)` inside plain sync test functions (matching
this repo's convention in test_open_finance_client.py etc.) rather than
`pytest.mark.asyncio`, since pytest-asyncio isn't configured in strict/auto
mode at the project root.
"""
import asyncio
from datetime import datetime, timedelta

import pytest

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, BankTransaction, IntegrationConnection, OfSnapshotCache
from cfo.services.credentials_vault import encrypt_credentials
from cfo.services.of_snapshot_service import OfSnapshotRefreshCooldown, get_or_fetch


# --------------------------------------------------------------------- #
# unit-level: get_or_fetch against a real (sqlite) session
# --------------------------------------------------------------------- #
@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class _Counter:
    def __init__(self):
        self.calls = 0

    def factory(self, payload=None, raise_exc=None):
        async def _fetch():
            self.calls += 1
            if raise_exc is not None:
                raise raise_exc
            return payload if payload is not None else {"items": [1, 2, 3]}
        return _fetch


def test_missing_cache_calls_factory_once_and_upserts(db, fresh_org):
    org = fresh_org()
    counter = _Counter()

    result = asyncio.run(get_or_fetch(
        db, org["org_id"], "widgets", counter.factory({"items": ["a"]}),
    ))
    assert counter.calls == 1
    assert result["items"] == ["a"]
    assert result["source"] == "live"
    assert "as_of" in result

    row = db.query(OfSnapshotCache).filter(
        OfSnapshotCache.organization_id == org["org_id"],
        OfSnapshotCache.resource == "widgets",
    ).first()
    assert row is not None
    assert row.payload == {"items": ["a"]}


def test_fresh_cache_hit_never_calls_factory(db, fresh_org):
    org = fresh_org()
    counter = _Counter()

    asyncio.run(get_or_fetch(db, org["org_id"], "widgets", counter.factory({"items": ["a"]})))
    assert counter.calls == 1

    # Second call within max_age_hours must be served from cache -- the
    # factory must NOT be invoked again (this is the actual cost-bug fix).
    result = asyncio.run(get_or_fetch(
        db, org["org_id"], "widgets", counter.factory({"items": ["SHOULD NOT APPEAR"]}),
        max_age_hours=20,
    ))
    assert counter.calls == 1  # unchanged
    assert result["items"] == ["a"]
    assert result["source"] == "cache"


def test_stale_cache_triggers_exactly_one_live_call_and_upserts(db, fresh_org):
    org = fresh_org()
    row = OfSnapshotCache(
        organization_id=org["org_id"], resource="widgets",
        payload={"items": ["old"]},
        fetched_at=datetime.utcnow() - timedelta(hours=48),
    )
    db.add(row)
    db.commit()

    counter = _Counter()
    result = asyncio.run(get_or_fetch(
        db, org["org_id"], "widgets", counter.factory({"items": ["new"]}),
        max_age_hours=20,
    ))
    assert counter.calls == 1
    assert result["items"] == ["new"]
    assert result["source"] == "live"

    refreshed = db.query(OfSnapshotCache).filter(
        OfSnapshotCache.organization_id == org["org_id"],
        OfSnapshotCache.resource == "widgets",
    ).first()
    assert refreshed.payload == {"items": ["new"]}


def test_force_refresh_within_cooldown_raises_and_does_not_call_factory(db, fresh_org):
    org = fresh_org()
    row = OfSnapshotCache(
        organization_id=org["org_id"], resource="widgets",
        payload={"items": ["old"]}, fetched_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()

    counter = _Counter()
    with pytest.raises(OfSnapshotRefreshCooldown) as exc_info:
        asyncio.run(get_or_fetch(
            db, org["org_id"], "widgets", counter.factory({"items": ["new"]}),
            force_refresh=True, refresh_cooldown_minutes=15,
        ))
    assert counter.calls == 0
    assert exc_info.value.retry_after_seconds > 0


def test_force_refresh_after_cooldown_calls_factory(db, fresh_org):
    org = fresh_org()
    row = OfSnapshotCache(
        organization_id=org["org_id"], resource="widgets",
        payload={"items": ["old"]},
        fetched_at=datetime.utcnow() - timedelta(minutes=30),
    )
    db.add(row)
    db.commit()

    counter = _Counter()
    result = asyncio.run(get_or_fetch(
        db, org["org_id"], "widgets", counter.factory({"items": ["new"]}),
        force_refresh=True, refresh_cooldown_minutes=15,
    ))
    assert counter.calls == 1
    assert result["items"] == ["new"]


def test_live_fetch_failure_falls_back_to_stale_cache(db, fresh_org):
    org = fresh_org()
    row = OfSnapshotCache(
        organization_id=org["org_id"], resource="widgets",
        payload={"items": ["last-good"]},
        fetched_at=datetime.utcnow() - timedelta(hours=48),
    )
    db.add(row)
    db.commit()

    counter = _Counter()
    result = asyncio.run(get_or_fetch(
        db, org["org_id"], "widgets",
        counter.factory(raise_exc=RuntimeError("provider down")),
        max_age_hours=20,
    ))
    assert counter.calls == 1
    assert result["items"] == ["last-good"]
    assert result["source"] == "stale_cache"
    assert "provider down" in result["error"]


def test_live_fetch_failure_with_no_cache_propagates(db, fresh_org):
    org = fresh_org()
    counter = _Counter()
    with pytest.raises(RuntimeError):
        asyncio.run(get_or_fetch(
            db, org["org_id"], "widgets",
            counter.factory(raise_exc=RuntimeError("provider down")),
        ))


def test_cache_rows_are_org_isolated(db, fresh_org):
    org_a = fresh_org()
    org_b = fresh_org()
    counter_a = _Counter()
    counter_b = _Counter()

    asyncio.run(get_or_fetch(db, org_a["org_id"], "widgets", counter_a.factory({"items": ["a-data"]})))
    asyncio.run(get_or_fetch(db, org_b["org_id"], "widgets", counter_b.factory({"items": ["b-data"]})))

    result_a = asyncio.run(get_or_fetch(db, org_a["org_id"], "widgets", counter_a.factory({"items": ["SHOULD NOT APPEAR"]})))
    result_b = asyncio.run(get_or_fetch(db, org_b["org_id"], "widgets", counter_b.factory({"items": ["SHOULD NOT APPEAR"]})))

    assert counter_a.calls == 1  # served from org_a's own cache row, not org_b's
    assert counter_b.calls == 1
    assert result_a["items"] == ["a-data"]
    assert result_b["items"] == ["b-data"]


def test_non_dict_payload_is_wrapped_before_caching(db, fresh_org):
    org = fresh_org()
    counter = _Counter()
    result = asyncio.run(get_or_fetch(db, org["org_id"], "widgets", counter.factory(["a", "b"])))
    assert result["items"] == ["a", "b"]
    assert result["source"] == "live"


# --------------------------------------------------------------------- #
# route-level: /accounts and /transactions must never build an OF client
# --------------------------------------------------------------------- #
def _raise_if_client_built(*args, **kwargs):
    raise AssertionError("Open Finance client must not be constructed for a DB-backed read route")


def test_accounts_route_never_builds_of_client(client, owner, monkeypatch):
    import cfo.api.routes.open_finance as of_routes
    monkeypatch.setattr(of_routes, "get_open_finance_client", _raise_if_client_built)

    org_id = owner["user"]["organization_id"]
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_id, name="Bank Leumi Checking",
            account_type=AccountType.BANK, source="open_finance",
            external_id="open_finance:acc-1", balance=1000, currency="ILS",
        ))
        db.commit()
    finally:
        db.close()

    r = client.get("/api/open-finance/accounts", headers=owner["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] >= 1
    assert any(a["external_id"] == "open_finance:acc-1" for a in body["items"])


def test_transactions_route_never_builds_of_client(client, owner, monkeypatch):
    import cfo.api.routes.open_finance as of_routes
    monkeypatch.setattr(of_routes, "get_open_finance_client", _raise_if_client_built)

    org_id = owner["user"]["organization_id"]
    db = SessionLocal()
    try:
        db.add(BankTransaction(
            organization_id=org_id, external_id="of-txn-rsf030", source="open_finance",
            transaction_date=datetime(2026, 6, 15).date(), description="Test txn",
            amount=-50, currency="ILS",
        ))
        db.commit()
    finally:
        db.close()

    r = client.get("/api/open-finance/transactions", headers=owner["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(t["description"] == "Test txn" for t in body["items"])


def test_accounts_route_is_org_scoped(client, fresh_org, monkeypatch):
    import cfo.api.routes.open_finance as of_routes
    monkeypatch.setattr(of_routes, "get_open_finance_client", _raise_if_client_built)

    org_a = fresh_org()
    org_b = fresh_org()
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_a["org_id"], name="Org A account",
            account_type=AccountType.BANK, source="open_finance",
            external_id="open_finance:only-a",
        ))
        db.commit()
    finally:
        db.close()

    r = client.get("/api/open-finance/accounts", headers=org_b["headers"])
    assert r.status_code == 200
    assert r.json()["count"] == 0


# --------------------------------------------------------------------- #
# route-level: cached GET endpoints
# --------------------------------------------------------------------- #
@pytest.fixture
def of_configured_org(fresh_org):
    org = fresh_org()
    db = SessionLocal()
    try:
        db.add(IntegrationConnection(
            organization_id=org["org_id"], source="open_finance", status="active",
            credentials_encrypted=encrypt_credentials({
                "client_id": "test-client-id", "client_secret": "test-client-secret",
                "user_id": "test-user-id",
            }),
        ))
        db.commit()
    finally:
        db.close()
    return org


def test_payments_route_caches_after_first_live_call(client, of_configured_org, monkeypatch):
    from cfo.services.open_finance_client import OpenFinanceClient

    calls = {"n": 0}

    async def fake_list_payments(self):
        calls["n"] += 1
        return {"items": [{"id": "p1"}]}

    monkeypatch.setattr(OpenFinanceClient, "list_payments", fake_list_payments)

    r1 = client.get("/api/open-finance/payments", headers=of_configured_org["headers"])
    assert r1.status_code == 200, r1.text
    assert r1.json()["source"] == "live"
    assert calls["n"] == 1

    r2 = client.get("/api/open-finance/payments", headers=of_configured_org["headers"])
    assert r2.status_code == 200
    assert r2.json()["source"] == "cache"
    assert calls["n"] == 1  # no second live call on a fresh cache hit

    assert r2.json()["items"] == [{"id": "p1"}]


def test_payments_route_refresh_is_cooldown_gated(client, of_configured_org, monkeypatch):
    from cfo.services.open_finance_client import OpenFinanceClient

    calls = {"n": 0}

    async def fake_list_payments(self):
        calls["n"] += 1
        return {"items": [{"id": f"p{calls['n']}"}]}

    monkeypatch.setattr(OpenFinanceClient, "list_payments", fake_list_payments)

    r1 = client.get("/api/open-finance/payments?refresh=true", headers=of_configured_org["headers"])
    assert r1.status_code == 200
    assert calls["n"] == 1

    r2 = client.get("/api/open-finance/payments?refresh=true", headers=of_configured_org["headers"])
    assert r2.status_code == 429
    assert r2.json()["detail"]["error"] == "manual_refresh_cooldown"
    assert calls["n"] == 1  # cooldown blocked the second forced refresh
