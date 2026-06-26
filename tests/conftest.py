import os
import sys
import tempfile

# Must run before the app (and its settings) are imported.
_db_path = os.path.join(tempfile.mkdtemp(prefix="cfo_test_"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ.pop("REGISTRATION_SECRET", None)
os.environ["SUMIT_API_KEY"] = "test-env-sumit-key"
os.environ["CRON_SECRET"] = "test-cron-secret"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from fastapi.testclient import TestClient

from cfo.api import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def owner(client):
    """First registered user — admin of the default organization."""
    resp = client.post("/api/admin/auth/register", json={
        "email": "owner@example.com",
        "password": "secret123",
        "full_name": "Owner",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {"headers": {"Authorization": f"Bearer {data['access_token']}"}, "user": data["user"]}


_iso_counter = {"n": 0}


@pytest.fixture
def fresh_org(client, owner):
    """Factory for an isolated organization (its own user) per test.

    Use when a test asserts exact aggregate amounts derived across ALL of an org's
    documents (ledger trial balance, cumulative P&L, annual reports) — the
    session-scoped `owner` org is shared across files and would pollute such totals.

    Depends on `owner` so the default org (first registered user) is always claimed
    by owner@example.com before any isolated org is created, regardless of test order.
    """
    def _make():
        _iso_counter["n"] += 1
        email = f"iso{_iso_counter['n']}@example.com"
        resp = client.post("/api/admin/auth/register", json={
            "email": email, "password": "secret123", "full_name": "Iso",
        })
        assert resp.status_code == 201, resp.text
        data = resp.json()
        return {"headers": {"Authorization": f"Bearer {data['access_token']}"},
                "org_id": data["user"]["organization_id"]}
    return _make


@pytest.fixture(scope="session")
def tenant(client, owner):
    """Second self-registered user — gets an organization of their own."""
    resp = client.post("/api/admin/auth/register", json={
        "email": "tenant@example.com",
        "password": "secret123",
        "full_name": "Tenant",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {"headers": {"Authorization": f"Bearer {data['access_token']}"}, "user": data["user"]}
