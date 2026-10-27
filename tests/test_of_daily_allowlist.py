"""Owner decision 26/10/2026: a daily Open Finance refresh for Eliav only.

`OPEN_FINANCE_SCHEDULED_SYNC_ORG_IDS` names the organizations the scheduled
route may refresh. The global flag stays off. Every existing gate (consent,
the 20-hour budget, the attempt cooldown) still runs for an allowed
organization. No provider calls: the sync loop is replaced.
"""
from decimal import Decimal

from cfo.config import Settings, settings
from cfo.database import SessionLocal
from cfo.models import IntegrationConnection

HEADERS = {"Authorization": "Bearer test-cron-secret"}


def _connect(org_id):
    with SessionLocal() as db:
        db.add(IntegrationConnection(organization_id=org_id, source="open_finance", status="active"))
        db.commit()


def _record(monkeypatch, consent=lambda _db, _org: None):
    from cfo.api.routes import cron

    attempted = []

    async def record(_db, targets, **_kwargs):
        attempted.append(set(targets))
        return []

    monkeypatch.setattr(cron, "roster_sync_targets", lambda _db: [])
    monkeypatch.setattr(cron, "_run_sync_targets", record)
    monkeypatch.setattr(cron, "_of_consent_gate", consent)
    monkeypatch.setattr(cron, "_of_budget_gate", lambda _db, _org, _src: None)
    monkeypatch.setattr(cron, "_claim_open_finance_sync_attempt", lambda _db, _org: None)
    return attempted


def test_the_scheduled_refresh_runs_only_for_allowlisted_organizations(client, fresh_org, monkeypatch):
    allowed, other = fresh_org()["org_id"], fresh_org()["org_id"]
    _connect(allowed)
    _connect(other)
    attempted = _record(monkeypatch)
    monkeypatch.setattr(settings, "open_finance_scheduled_sync_enabled", False)
    monkeypatch.setattr(settings, "open_finance_scheduled_sync_org_ids", str(allowed))

    response = client.get("/api/cron/sync-open-finance", headers=HEADERS)

    assert response.status_code == 200, response.text
    targets = set().union(*attempted)
    assert targets == {(allowed, "open_finance")}


def test_an_allowlisted_organization_still_passes_the_existing_gates(client, fresh_org, monkeypatch):
    allowed = fresh_org()["org_id"]
    _connect(allowed)
    skipped = {"organization_id": allowed, "source": "open_finance", "skipped": "consent_expired"}
    attempted = _record(monkeypatch, consent=lambda _db, org: skipped if org == allowed else None)
    monkeypatch.setattr(settings, "open_finance_scheduled_sync_enabled", False)
    monkeypatch.setattr(settings, "open_finance_scheduled_sync_org_ids", str(allowed))

    body = client.get("/api/cron/sync-open-finance", headers=HEADERS).json()

    assert all((allowed, "open_finance") not in targets for targets in attempted)
    assert skipped in body["results"]


def test_with_no_allowlist_and_the_flag_off_nothing_is_refreshed(client, monkeypatch):
    attempted = _record(monkeypatch)
    monkeypatch.setattr(settings, "open_finance_scheduled_sync_enabled", False)
    monkeypatch.setattr(settings, "open_finance_scheduled_sync_org_ids", "")

    body = client.get("/api/cron/sync-open-finance", headers=HEADERS).json()

    assert body["skipped"] == "open_finance_scheduled_sync_disabled"
    assert attempted == []


def test_the_allowlist_reads_organization_ids_and_fails_closed_on_anything_else():
    assert Settings(open_finance_scheduled_sync_org_ids="2, 6").open_finance_scheduled_sync_org_id_set == {2, 6}
    assert Settings(open_finance_scheduled_sync_org_ids="").open_finance_scheduled_sync_org_id_set == set()
    # A typo must not widen the refresh: the whole value is ignored.
    assert Settings(open_finance_scheduled_sync_org_ids="2,all").open_finance_scheduled_sync_org_id_set == set()


def test_credit_limit_arrives_as_a_number_or_as_an_amount_object():
    """The API reference documents a number. The plan's liquidity evidence for Eliav
    was recorded from ``CHECKING.creditLimit.amount``. Both read the same; an object
    without an amount stays unknown."""
    from cfo.services.open_finance_connector import _credit_limit

    assert _credit_limit({"creditLimit": 15000}) == Decimal("15000")
    assert _credit_limit({"creditLimit": {"amount": 15000, "currency": "ILS"}}) == Decimal("15000")
    assert _credit_limit({"creditLimit": {"amount": "80000.00"}}) == Decimal("80000.00")
    assert _credit_limit({"creditLimit": {"currency": "ILS"}}) is None
