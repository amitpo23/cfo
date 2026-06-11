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
