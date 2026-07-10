"""fetch_* methods on SumitConnector silently swallow every API failure (bad
credentials, rate limit, network error) and return an empty-but-"successful"
FetchResult -- run_full_sync() then reports status=COMPLETED with
error_summary=None even when literally every SUMIT call failed. Found live
2026-07-04: orgs 2/3/4's invalid SUMIT credentials ("CompanyID/APIKey are
incorrect") were completely invisible via GET /api/integration/status, which
kept reporting connections.sumit == "active" and error_summary == null.

FetchResult now carries an optional `error`; _sync_entity_type raises when
it's set, which the existing error-aggregation in run_full_sync (errors list,
error_summary, error_details, SyncStatus.PARTIAL) already picks up -- no new
aggregation logic needed, just a path for the swallowed error to reach it.
"""
import asyncio

import pytest

from cfo.database import SessionLocal, init_db
from cfo.models import IntegrationConnection, Organization, SyncRun, SyncStatus
from cfo.services.connector_base import FetchResult
from cfo.services.sync_engine import SyncEngine

CRED_ERROR = "SUMIT API error: Invalid Credentials (CompanyID/APIKey are incorrect)"


@pytest.fixture(autouse=True, scope="module")
def _ensure_schema():
    init_db()


def _make_org(db, name="Broken Creds Co"):
    org = Organization(name=name, is_active=True)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


class _BrokenCredsConnector:
    """Mirrors SumitConnector's real shape when every live call fails: the
    two locally-synthesized entity types (accounts, journal_entries/vendors)
    still succeed since they never touch SUMIT; every real API call fails."""

    async def fetch_accounts(self, updated_since=None, cursor=None, page_size=100):
        return FetchResult(items=[], has_more=False)

    async def fetch_customers(self, updated_since=None, cursor=None, page_size=100):
        return FetchResult(items=[], has_more=False, error=CRED_ERROR)

    async def fetch_vendors(self, updated_since=None, cursor=None, page_size=100):
        return FetchResult(items=[], has_more=False)

    async def fetch_invoices(self, updated_since=None, cursor=None, page_size=100):
        return FetchResult(items=[], has_more=False, error=CRED_ERROR)

    async def fetch_bills(self, updated_since=None, cursor=None, page_size=100):
        return FetchResult(items=[], has_more=False, error=CRED_ERROR)

    async def fetch_payments(self, updated_since=None, cursor=None, page_size=100):
        return FetchResult(items=[], has_more=False, error=CRED_ERROR)

    async def fetch_bank_transactions(self, updated_since=None, cursor=None, page_size=100):
        return FetchResult(items=[], has_more=False, error=CRED_ERROR)

    async def fetch_journal_entries(self, updated_since=None, cursor=None, page_size=100):
        return FetchResult(items=[], has_more=False)


def test_run_full_sync_surfaces_error_when_every_real_fetch_fails():
    db = SessionLocal()
    try:
        org_id = _make_org(db).id
    finally:
        db.close()

    db = SessionLocal()
    try:
        engine = SyncEngine(db, _BrokenCredsConnector(), org_id, "sumit")
        sync_run = asyncio.run(engine.run_full_sync())

        assert sync_run.status == SyncStatus.PARTIAL
        assert sync_run.error_summary is not None
        assert CRED_ERROR in str(sync_run.error_details)
        failed_types = {d["entity_type"] for d in sync_run.error_details}
        assert failed_types == {"customers", "invoices", "bills", "payments", "bank_transactions"}
    finally:
        db.close()


def test_run_full_sync_stays_clean_when_every_fetch_succeeds():
    """No regression: a healthy connector (no .error set) still reports COMPLETED."""
    db = SessionLocal()
    try:
        org_id = _make_org(db, "Healthy Co").id
    finally:
        db.close()

    class _HealthyConnector(_BrokenCredsConnector):
        async def fetch_customers(self, updated_since=None, cursor=None, page_size=100):
            return FetchResult(items=[], has_more=False)

        async def fetch_invoices(self, updated_since=None, cursor=None, page_size=100):
            return FetchResult(items=[], has_more=False)

        async def fetch_bills(self, updated_since=None, cursor=None, page_size=100):
            return FetchResult(items=[], has_more=False)

        async def fetch_payments(self, updated_since=None, cursor=None, page_size=100):
            return FetchResult(items=[], has_more=False)

        async def fetch_bank_transactions(self, updated_since=None, cursor=None, page_size=100):
            return FetchResult(items=[], has_more=False)

    db = SessionLocal()
    try:
        engine = SyncEngine(db, _HealthyConnector(), org_id, "sumit")
        sync_run = asyncio.run(engine.run_full_sync())

        assert sync_run.status == SyncStatus.COMPLETED
        assert sync_run.error_summary is None
    finally:
        db.close()


def test_integration_status_surfaces_last_sync_error_without_flipping_connection_flag(client, fresh_org):
    """New `last_sync_errors` field exposes the real failure; `connections.sumit`
    and `configured.sumit` are left untouched (4 existing dashboards render
    connections.sumit truthily -- flipping its string would falsely read as a
    non-connection rather than a broken one, and configured means "has
    credentials", not "currently working")."""
    org = fresh_org()
    org_id = org["org_id"]

    db = SessionLocal()
    try:
        db.add(IntegrationConnection(organization_id=org_id, source="sumit", status="active"))
        db.add(SyncRun(
            organization_id=org_id, source="sumit", status=SyncStatus.PARTIAL,
            error_summary="1 entity types had errors",
            error_details=[{"entity_type": "invoices", "error": CRED_ERROR}],
        ))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/integration/status", headers=org["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["last_sync_errors"]["sumit"] == "1 entity types had errors"
    assert body["connections"]["sumit"] == "active"
    assert body["configured"]["sumit"] is True


def test_integration_status_omits_last_sync_error_when_none_recorded(client, fresh_org):
    org = fresh_org()
    resp = client.get("/api/integration/status", headers=org["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["last_sync_errors"] == {}
