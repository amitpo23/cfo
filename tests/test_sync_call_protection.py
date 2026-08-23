"""M1a -- sync call-protection core (RSF-020..032).

Covers: watermark computed from SyncCheckpoint and passed into connector
fetch calls, checkpoint persistence, the per-entity page cap (-> PARTIAL),
the circuit breaker (opens on a breaking 401/403/quota error, skips the next
run, never retries), the transient-5xx retry-with-backoff path, the Open
Finance daily budget gate, the manual-refresh cooldown, and the cross-run
advisory lock's SQLite no-op fallback / Postgres-simulated skip path.

No live external API calls anywhere -- every connector here is an in-memory
fake implementing only the fetch_* method(s) the test actually exercises.
"""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from cfo.config import settings
from cfo.database import SessionLocal, init_db
from cfo.models import Organization, SyncCheckpoint, SyncRun, SyncStatus
from cfo.services.connector_base import FetchResult
from cfo.services.sync_engine import SOURCE_CHECKPOINT_ENTITY, SyncEngine, SyncSkipped


@pytest.fixture(autouse=True, scope="module")
def _ensure_schema():
    init_db()


def _make_org(db, name="Call Protection Co"):
    org = Organization(name=name, is_active=True)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _get_checkpoint(db, org_id, source, entity_type):
    return db.query(SyncCheckpoint).filter(
        SyncCheckpoint.organization_id == org_id,
        SyncCheckpoint.source == source,
        SyncCheckpoint.entity_type == entity_type,
    ).first()


# ---- Fakes ----
# SyncEngine._sync_entity_type builds its {entity_type: fetch_method} map by
# attribute-accessing every fetch_* method up front (even though it only
# .get()s the one it needs), so every fake connector -- even ones scoped to a
# single entity_types=["invoices"] run -- must implement all eight fetch_*
# methods. _NoOpConnector supplies harmless defaults; subclasses override just
# fetch_invoices, the entity type these tests exercise.

class _NoOpConnector:
    async def fetch_accounts(self, updated_since=None, cursor=None, page_size=100):
        return FetchResult(items=[], has_more=False)

    async def fetch_customers(self, updated_since=None, cursor=None, page_size=100):
        return FetchResult(items=[], has_more=False)

    async def fetch_vendors(self, updated_since=None, cursor=None, page_size=100):
        return FetchResult(items=[], has_more=False)

    async def fetch_invoices(self, updated_since=None, cursor=None, page_size=100):
        return FetchResult(items=[], has_more=False)

    async def fetch_bills(self, updated_since=None, cursor=None, page_size=100):
        return FetchResult(items=[], has_more=False)

    async def fetch_payments(self, updated_since=None, cursor=None, page_size=100):
        return FetchResult(items=[], has_more=False)

    async def fetch_bank_transactions(self, updated_since=None, cursor=None, page_size=100):
        return FetchResult(items=[], has_more=False)

    async def fetch_journal_entries(self, updated_since=None, cursor=None, page_size=100):
        return FetchResult(items=[], has_more=False)


class _WatermarkCapturingConnector(_NoOpConnector):
    def __init__(self):
        self.calls = []

    async def fetch_invoices(self, updated_since=None, cursor=None, page_size=100):
        self.calls.append(updated_since)
        return FetchResult(items=[], has_more=False)


class _SucceedingConnector(_NoOpConnector):
    def __init__(self):
        self.calls = 0

    async def fetch_invoices(self, updated_since=None, cursor=None, page_size=100):
        self.calls += 1
        return FetchResult(items=[], has_more=False)


class _NeverEndingConnector(_NoOpConnector):
    """Always claims there's another page -- exercises the page cap."""

    def __init__(self):
        self.calls = 0

    async def fetch_invoices(self, updated_since=None, cursor=None, page_size=100):
        self.calls += 1
        return FetchResult(items=[], has_more=True, next_cursor=str(self.calls))


class _BreakingErrorConnector(_NoOpConnector):
    """Mirrors a hard SUMIT 403 (see sumit_integration.py: 'SUMIT API error
    <code>: <text>') -- never retried, opens the circuit."""

    def __init__(self, message="SUMIT API error 403: rate limited"):
        self.calls = 0
        self.message = message

    async def fetch_invoices(self, updated_since=None, cursor=None, page_size=100):
        self.calls += 1
        raise RuntimeError(self.message)


class _FlakyTransientConnector(_NoOpConnector):
    """Fails with a transient 5xx `fail_times` times, then succeeds."""

    def __init__(self, fail_times):
        self.calls = 0
        self.fail_times = fail_times

    async def fetch_invoices(self, updated_since=None, cursor=None, page_size=100):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("API error 503: temporarily unavailable")
        return FetchResult(items=[], has_more=False)


class _NeverCalledConnector(_NoOpConnector):
    def __init__(self):
        self.calls = 0

    async def fetch_invoices(self, updated_since=None, cursor=None, page_size=100):
        self.calls += 1
        return FetchResult(items=[], has_more=False)


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


# ---- Watermark ----

def test_watermark_passed_to_connector_computed_from_checkpoint_minus_overlap():
    db = SessionLocal()
    try:
        org_id = _make_org(db, "Watermark Co").id
        last_success = datetime.utcnow() - timedelta(days=10)
        db.add(SyncCheckpoint(
            organization_id=org_id, source="sumit", entity_type="invoices",
            last_success_at=last_success,
        ))
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        connector = _WatermarkCapturingConnector()
        engine = SyncEngine(db, connector, org_id, "sumit")
        asyncio.run(engine.run_full_sync(entity_types=["invoices"]))
    finally:
        db.close()

    assert len(connector.calls) == 1
    expected = last_success - timedelta(days=settings.sync_overlap_days)
    assert connector.calls[0] is not None
    assert abs((connector.calls[0] - expected).total_seconds()) < 2


def test_watermark_is_none_on_first_sync_no_checkpoint_yet():
    db = SessionLocal()
    try:
        org_id = _make_org(db, "First Sync Co").id
    finally:
        db.close()

    db = SessionLocal()
    try:
        connector = _WatermarkCapturingConnector()
        engine = SyncEngine(db, connector, org_id, "sumit")
        asyncio.run(engine.run_full_sync(entity_types=["invoices"]))
    finally:
        db.close()

    assert connector.calls == [None]


def test_explicit_updated_since_overrides_per_entity_checkpoint():
    db = SessionLocal()
    try:
        org_id = _make_org(db, "Override Co").id
        db.add(SyncCheckpoint(
            organization_id=org_id, source="sumit", entity_type="invoices",
            last_success_at=datetime.utcnow() - timedelta(days=10),
        ))
        db.commit()
    finally:
        db.close()

    forced = datetime.utcnow() - timedelta(hours=1)
    db = SessionLocal()
    try:
        connector = _WatermarkCapturingConnector()
        engine = SyncEngine(db, connector, org_id, "sumit")
        asyncio.run(engine.run_full_sync(entity_types=["invoices"], updated_since=forced))
    finally:
        db.close()

    assert connector.calls == [forced]


# ---- Checkpoint persistence ----

def test_checkpoint_persisted_after_successful_sync():
    db = SessionLocal()
    try:
        org_id = _make_org(db, "Persist Co").id
    finally:
        db.close()

    db = SessionLocal()
    try:
        engine = SyncEngine(db, _SucceedingConnector(), org_id, "sumit")
        asyncio.run(engine.run_full_sync(entity_types=["invoices"]))
    finally:
        db.close()

    db = SessionLocal()
    try:
        cp = _get_checkpoint(db, org_id, "sumit", "invoices")
        assert cp is not None
        assert cp.last_success_at is not None
        assert cp.consecutive_failures == 0
        assert cp.circuit_open_until is None
        assert cp.cursor is None
    finally:
        db.close()


# ---- Page cap -> PARTIAL ----

def test_page_cap_stops_run_and_marks_partial(monkeypatch):
    monkeypatch.setattr(settings, "sync_max_pages_per_entity", 3)

    db = SessionLocal()
    try:
        org_id = _make_org(db, "Page Cap Co").id
    finally:
        db.close()

    db = SessionLocal()
    try:
        connector = _NeverEndingConnector()
        engine = SyncEngine(db, connector, org_id, "sumit")
        sync_run = asyncio.run(engine.run_full_sync(entity_types=["invoices"]))
    finally:
        db.close()

    assert connector.calls == 3
    assert sync_run.status == SyncStatus.PARTIAL
    assert sync_run.counts["invoices"]["status"] == "PARTIAL"

    db = SessionLocal()
    try:
        cp = _get_checkpoint(db, org_id, "sumit", "invoices")
        assert cp.cursor == "3"  # resumable
        assert cp.last_success_at is None  # page cap is not a "success"
    finally:
        db.close()


# ---- Circuit breaker ----

def test_circuit_breaker_opens_on_403_and_never_retries():
    db = SessionLocal()
    try:
        org_id = _make_org(db, "Circuit Co").id
    finally:
        db.close()

    db = SessionLocal()
    try:
        connector = _BreakingErrorConnector()
        engine = SyncEngine(db, connector, org_id, "sumit")
        sync_run = asyncio.run(engine.run_full_sync(entity_types=["invoices"]))
    finally:
        db.close()

    assert connector.calls == 1  # no retry on a breaking error
    assert sync_run.status in (SyncStatus.PARTIAL, SyncStatus.FAILED)
    assert "403" in sync_run.counts["invoices"]["error"]

    db = SessionLocal()
    try:
        cp = _get_checkpoint(db, org_id, "sumit", "invoices")
        assert cp.consecutive_failures == 1
        assert cp.circuit_open_until is not None
        assert cp.circuit_open_until > datetime.utcnow()
    finally:
        db.close()

    # Next run: circuit is open, connector must not be called again.
    db = SessionLocal()
    try:
        engine2 = SyncEngine(db, connector, org_id, "sumit")
        sync_run2 = asyncio.run(engine2.run_full_sync(entity_types=["invoices"]))
    finally:
        db.close()

    assert connector.calls == 1  # still 1 -- skipped, not called
    assert sync_run2.counts["invoices"].get("skipped_circuit_open") is True


# ---- Transient 5xx retry ----

def test_transient_5xx_retries_up_to_twice_then_succeeds(monkeypatch):
    monkeypatch.setattr(settings, "sync_retry_base_delay_seconds", 0.01)

    db = SessionLocal()
    try:
        org_id = _make_org(db, "Flaky Success Co").id
    finally:
        db.close()

    db = SessionLocal()
    try:
        connector = _FlakyTransientConnector(fail_times=2)
        engine = SyncEngine(db, connector, org_id, "sumit")
        sync_run = asyncio.run(engine.run_full_sync(entity_types=["invoices"]))
    finally:
        db.close()

    assert connector.calls == 3  # initial attempt + 2 retries
    assert "error" not in sync_run.counts["invoices"]
    assert sync_run.status == SyncStatus.COMPLETED


def test_transient_5xx_gives_up_after_two_retries_without_opening_circuit(monkeypatch):
    monkeypatch.setattr(settings, "sync_retry_base_delay_seconds", 0.01)

    db = SessionLocal()
    try:
        org_id = _make_org(db, "Flaky Failure Co").id
    finally:
        db.close()

    db = SessionLocal()
    try:
        connector = _FlakyTransientConnector(fail_times=5)  # never recovers
        engine = SyncEngine(db, connector, org_id, "sumit")
        sync_run = asyncio.run(engine.run_full_sync(entity_types=["invoices"]))
    finally:
        db.close()

    assert connector.calls == 3  # initial attempt + 2 retries, no more
    assert "error" in sync_run.counts["invoices"]

    db = SessionLocal()
    try:
        cp = _get_checkpoint(db, org_id, "sumit", "invoices")
        # Transient 5xx is not a "breaking" error -- must not open the circuit.
        assert cp.circuit_open_until is None
    finally:
        db.close()


# ---- Open Finance daily budget gate ----

def test_of_daily_budget_gate_skips_within_interval_and_allows_after():
    from cfo.api.routes.cron import _of_budget_gate

    db = SessionLocal()
    try:
        org_id = _make_org(db, "OF Budget Co").id
        db.add(SyncCheckpoint(
            organization_id=org_id, source="open_finance", entity_type=SOURCE_CHECKPOINT_ENTITY,
            last_success_at=datetime.utcnow() - timedelta(hours=1),
        ))
        db.commit()

        gated = _of_budget_gate(db, org_id, "open_finance")
        assert gated is not None
        assert gated["skipped"] == "daily_budget"

        cp = _get_checkpoint(db, org_id, "open_finance", SOURCE_CHECKPOINT_ENTITY)
        cp.last_success_at = datetime.utcnow() - timedelta(hours=settings.of_sync_min_interval_hours + 1)
        db.commit()

        assert _of_budget_gate(db, org_id, "open_finance") is None
    finally:
        db.close()


def test_of_daily_budget_gate_allows_when_no_prior_success():
    from cfo.api.routes.cron import _of_budget_gate

    db = SessionLocal()
    try:
        org_id = _make_org(db, "OF First Timer Co").id
        assert _of_budget_gate(db, org_id, "open_finance") is None
    finally:
        db.close()


def test_of_failed_cron_attempt_enters_cooldown_before_retry(
    client, fresh_org, monkeypatch,
):
    """A failed Vercel retry must stop before the provider-sync loop."""
    from cfo.api.routes import cron
    from cfo.models import IntegrationConnection, ProviderRequestBudget

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(IntegrationConnection(
            organization_id=org_id,
            source="open_finance",
            status="active",
        ))
        db.query(SyncCheckpoint).filter(
            SyncCheckpoint.organization_id == org_id,
            SyncCheckpoint.source == "open_finance",
        ).delete(synchronize_session=False)
        db.query(ProviderRequestBudget).filter(
            ProviderRequestBudget.provider == "open_finance",
            ProviderRequestBudget.organization_id == org_id,
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

    attempted_targets = []

    async def fail_sync(_db, targets):
        attempted_targets.append(set(targets))
        return [
            {
                "organization_id": target_org_id,
                "source": source,
                "error": "provider unavailable",
            }
            for target_org_id, source in sorted(targets)
        ]

    monkeypatch.setattr(cron, "roster_sync_targets", lambda _db: [])
    monkeypatch.setattr(cron, "_run_sync_targets", fail_sync)
    headers = {"Authorization": "Bearer test-cron-secret"}

    first = client.get("/api/cron/sync-open-finance", headers=headers)
    second = client.get("/api/cron/sync-open-finance", headers=headers)

    assert first.status_code == 200, first.text
    assert sum(org_id in {item[0] for item in targets} for targets in attempted_targets) == 1
    retry = next(
        item for item in second.json()["results"]
        if item["organization_id"] == org_id
    )
    assert retry["skipped"] == "failure_cooldown"
    assert retry["retry_at"]

    db = SessionLocal()
    try:
        checkpoint = _get_checkpoint(
            db, org_id, "open_finance", "scheduled_sync_attempt",
        )
        assert checkpoint.consecutive_failures == 1
        assert checkpoint.cooldown_until > datetime.utcnow()
    finally:
        db.close()


def test_of_daily_attempt_cap_blocks_third_attempt_even_after_cooldown(
    client, fresh_org, monkeypatch,
):
    from cfo.api.routes import cron
    from cfo.models import IntegrationConnection, ProviderRequestBudget

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(IntegrationConnection(
            organization_id=org_id,
            source="open_finance",
            status="active",
        ))
        db.query(ProviderRequestBudget).filter(
            ProviderRequestBudget.provider == "open_finance",
            ProviderRequestBudget.organization_id == org_id,
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

    provider_path_calls = 0

    async def fail_sync(_db, targets):
        nonlocal provider_path_calls
        provider_path_calls += sum(target_org_id == org_id for target_org_id, _ in targets)
        return [
            {
                "organization_id": target_org_id,
                "source": source,
                "error": "provider unavailable",
            }
            for target_org_id, source in sorted(targets)
        ]

    monkeypatch.setattr(cron, "roster_sync_targets", lambda _db: [])
    monkeypatch.setattr(cron, "_run_sync_targets", fail_sync)
    headers = {"Authorization": "Bearer test-cron-secret"}

    for attempt in range(3):
        response = client.get("/api/cron/sync-open-finance", headers=headers)
        assert response.status_code == 200, response.text
        if attempt < 2:
            db = SessionLocal()
            try:
                checkpoint = _get_checkpoint(
                    db, org_id, "open_finance", "scheduled_sync_attempt",
                )
                checkpoint.cooldown_until = datetime.utcnow() - timedelta(seconds=1)
                db.commit()
            finally:
                db.close()

    target = next(
        item for item in response.json()["results"]
        if item["organization_id"] == org_id
    )
    assert target["skipped"] == "daily_attempt_budget"
    assert provider_path_calls == 2


def test_of_attempt_counter_failure_is_fail_closed(
    client, fresh_org, monkeypatch,
):
    from cfo.api.routes import cron
    from cfo.models import IntegrationConnection

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(IntegrationConnection(
            organization_id=org_id,
            source="open_finance",
            status="active",
        ))
        db.commit()
    finally:
        db.close()

    async def must_not_run(_db, targets):
        assert org_id not in {target_org_id for target_org_id, _ in targets}
        return []

    monkeypatch.setattr(cron, "roster_sync_targets", lambda _db: [])
    monkeypatch.setattr(cron, "_run_sync_targets", must_not_run)
    monkeypatch.setattr(
        cron,
        "_claim_daily_counter_slots",
        lambda **_kwargs: {"claimed": 0, "skipped": "budget_unavailable"},
        raising=False,
    )

    response = client.get(
        "/api/cron/sync-open-finance",
        headers={"Authorization": "Bearer test-cron-secret"},
    )

    assert response.status_code == 200, response.text
    target = next(
        item for item in response.json()["results"]
        if item["organization_id"] == org_id
    )
    assert target["skipped"] == "budget_unavailable"


def test_of_consent_gate_stops_pending_journey_before_daily_budget():
    from cfo.api.routes.cron import _of_consent_gate
    from cfo.models import BankConnection

    db = SessionLocal()
    try:
        org_id = _make_org(db, "OF Pending Consent Co").id
        db.add(BankConnection(
            organization_id=org_id,
            source="open_finance",
            connection_id="pending-consent-1",
            connect_url="https://consent.example.com/pending-consent-1",
            status="INACTIVE",
        ))
        db.commit()

        gated = _of_consent_gate(db, org_id)
        assert gated == {
            "organization_id": org_id,
            "source": "open_finance",
            "skipped": "consent_pending",
            "connection_statuses": ["INACTIVE"],
        }
        assert (
            db.query(SyncCheckpoint)
            .filter(
                SyncCheckpoint.organization_id == org_id,
                SyncCheckpoint.source == "open_finance",
                SyncCheckpoint.entity_type == SOURCE_CHECKPOINT_ENTITY,
            )
            .count()
            == 0
        )

        db.query(BankConnection).filter(
            BankConnection.organization_id == org_id,
        ).update({"status": "ACTIVE"}, synchronize_session=False)
        db.commit()
        assert _of_consent_gate(db, org_id) is None
    finally:
        db.close()


def test_touch_source_checkpoint_only_on_clean_full_completed_sync():
    """A full (entity_types=None), unforced (updated_since=None) run that
    completes cleanly should set the source-level checkpoint the OF budget
    gate reads; a scoped/partial run must not."""
    db = SessionLocal()
    try:
        org_id = _make_org(db, "Touch Checkpoint Co").id
    finally:
        db.close()

    db = SessionLocal()
    try:
        engine = SyncEngine(db, _NoOpConnector(), org_id, "open_finance")
        sync_run = asyncio.run(engine.run_full_sync())
        assert sync_run.status == SyncStatus.COMPLETED
    finally:
        db.close()

    db = SessionLocal()
    try:
        cp = _get_checkpoint(db, org_id, "open_finance", SOURCE_CHECKPOINT_ENTITY)
        assert cp is not None
        assert cp.last_success_at is not None
    finally:
        db.close()

    # A scoped sync (explicit entity_types) must NOT touch the source checkpoint.
    org2_id = None
    db = SessionLocal()
    try:
        org2_id = _make_org(db, "Touch Checkpoint Scoped Co").id
    finally:
        db.close()

    db = SessionLocal()
    try:
        engine = SyncEngine(db, _NoOpConnector(), org2_id, "open_finance")
        asyncio.run(engine.run_full_sync(entity_types=["invoices"]))
    finally:
        db.close()

    db = SessionLocal()
    try:
        cp2 = _get_checkpoint(db, org2_id, "open_finance", SOURCE_CHECKPOINT_ENTITY)
        assert cp2 is None
    finally:
        db.close()


# ---- Manual-refresh cooldown ----

def test_manual_refresh_cooldown_blocks_then_expires():
    from cfo.api.routes.cfo_sync import _manual_refresh_cooldown_check, _start_manual_refresh_cooldown

    db = SessionLocal()
    try:
        org_id = _make_org(db, "Cooldown Co").id

        assert _manual_refresh_cooldown_check(db, org_id, "sumit") is None

        _start_manual_refresh_cooldown(db, org_id, "sumit")

        blocked = _manual_refresh_cooldown_check(db, org_id, "sumit")
        assert blocked is not None
        assert blocked["error"] == "manual_refresh_cooldown"
        assert blocked["retry_after_seconds"] > 0

        # A different source for the same org is independent.
        assert _manual_refresh_cooldown_check(db, org_id, "open_finance") is None

        # Simulate cooldown expiry.
        cp = _get_checkpoint(db, org_id, "sumit", SOURCE_CHECKPOINT_ENTITY)
        cp.cooldown_until = datetime.utcnow() - timedelta(seconds=1)
        db.commit()

        assert _manual_refresh_cooldown_check(db, org_id, "sumit") is None
    finally:
        db.close()


# ---- Cross-run advisory lock ----

def test_lock_is_a_noop_on_sqlite_always_proceeds():
    db = SessionLocal()
    try:
        org_id = _make_org(db, "Lock Sqlite Co").id
    finally:
        db.close()

    db = SessionLocal()
    try:
        engine = SyncEngine(db, _SucceedingConnector(), org_id, "sumit")
        assert engine._dialect_name() == "sqlite"
        assert engine._acquire_lock() is True
        engine._release_lock()  # must not raise
    finally:
        db.close()


def test_run_full_sync_returns_skipped_when_postgres_lock_not_acquired(monkeypatch):
    db = SessionLocal()
    try:
        org_id = _make_org(db, "Lock Contention Co").id
    finally:
        db.close()

    db = SessionLocal()
    try:
        connector = _NeverCalledConnector()
        engine = SyncEngine(db, connector, org_id, "sumit")
        monkeypatch.setattr(engine, "_dialect_name", lambda: "postgresql")
        monkeypatch.setattr(engine.db, "execute", lambda *a, **kw: _FakeScalarResult(False))

        result = asyncio.run(engine.run_full_sync(entity_types=["invoices"]))
    finally:
        db.close()

    assert isinstance(result, SyncSkipped)
    assert result.locked is True
    assert result.id is None
    assert connector.calls == 0  # never even reached the connector


# --------------------------------------------------------------------------- #
# Hard cost-protection settings (owner directive 2026-07-17 after real SUMIT
# API-overage charges billed to a client company): daily sync only, never
# exceed quota — enforced in CODE, not just in the cron schedule.
# --------------------------------------------------------------------------- #

def test_sumit_budget_gate_skips_within_interval():
    """SUMIT scheduled syncs must be code-gated to one successful full sync
    per org per interval — the cron schedule alone is not a hard guarantee."""
    from cfo.api.routes.cron import _daily_budget_gate

    db = SessionLocal()
    try:
        org_id = _make_org(db, "SUMIT Budget Co").id
        db.add(SyncCheckpoint(
            organization_id=org_id, source="sumit", entity_type=SOURCE_CHECKPOINT_ENTITY,
            last_success_at=datetime.utcnow() - timedelta(hours=1),
        ))
        db.commit()

        gated = _daily_budget_gate(db, org_id, "sumit")
        assert gated is not None
        assert gated["skipped"] == "daily_budget"

        cp = _get_checkpoint(db, org_id, "sumit", SOURCE_CHECKPOINT_ENTITY)
        cp.last_success_at = datetime.utcnow() - timedelta(hours=settings.sumit_sync_min_interval_hours + 1)
        db.commit()

        assert _daily_budget_gate(db, org_id, "sumit") is None
    finally:
        db.close()


def test_cost_protection_settings_have_hard_floors():
    """Env misconfiguration must not be able to loosen the cost protections:
    intervals are clamped to hard minimums at Settings construction."""
    from cfo.config import Settings

    s = Settings(
        of_sync_min_interval_hours=1,
        sumit_sync_min_interval_hours=0,
        sumit_enrichment_daily_action_limit=999,
        ocr_daily_document_limit=999,
        chat_receipt_daily_limit=999,
        collection_reminder_batch_limit=999,
        channel_push_daily_limit=999,
        manual_refresh_cooldown_minutes=1,
    )
    assert s.of_sync_min_interval_hours >= 20
    assert s.sumit_sync_min_interval_hours >= 20
    assert s.sumit_enrichment_daily_action_limit <= 25
    assert s.ocr_daily_document_limit <= 25
    assert s.chat_receipt_daily_limit <= 50
    assert s.collection_reminder_batch_limit <= 20
    assert s.channel_push_daily_limit <= 50
    assert s.manual_refresh_cooldown_minutes >= 15


def test_collection_cron_caps_and_claims_channel_deliveries_including_email(
    client, fresh_org, monkeypatch,
):
    from cfo.api.routes import cron
    from cfo.config import settings
    from cfo.models import Organization, ProviderRequestBudget
    from cfo.services.collection_service import PlannedReminder

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        org = db.get(Organization, org_id)
        org.collection_reminders_enabled = True
        db.query(ProviderRequestBudget).filter(
            ProviderRequestBudget.provider == "notifications",
            ProviderRequestBudget.organization_id == org_id,
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

    template = PlannedReminder(
        contact_id=1,
        contact_name="לקוח",
        email="customer@example.com",
        phone="0500000000",
        invoice_numbers=["INV-1"],
        total_amount=100.0,
        days_overdue=1,
        reminder_type="overdue",
        message="pay",
    )
    planned = [replace(template, contact_id=index) for index in range(1, 26)]
    sent_emails = []

    monkeypatch.setattr(settings, "collection_reminder_batch_limit", 20, raising=False)
    monkeypatch.setattr(
        cron.CollectionService,
        "plan_reminders",
        lambda self, _today: planned if self.org_id == org_id else [],
    )
    monkeypatch.setattr(cron, "sumit_for_org", lambda _db, _org_id: None)

    async def fake_email(to, subject, body, _settings):
        sent_emails.append((to, subject, body))
        return True

    monkeypatch.setattr(cron, "send_email_smtp", fake_email)
    headers = {"Authorization": "Bearer test-cron-secret"}

    first = client.get("/api/cron/collection-reminders", headers=headers)
    second = client.get("/api/cron/collection-reminders", headers=headers)

    assert first.status_code == 200, first.text
    first_summary = first.json()["summary"]
    assert first_summary["delivery_attempts"] == 20
    assert first_summary["email_sent"] == 10
    assert first_summary["failed"] == 10
    assert first_summary["budget_skipped"] == 30
    assert len(sent_emails) == 10

    assert second.status_code == 200, second.text
    assert second.json()["summary"]["delivery_attempts"] == 0
    assert second.json()["summary"]["budget_skipped"] == 50
    assert len(sent_emails) == 10


def test_expense_enrichment_is_hard_gated_to_one_provider_attempt_per_day(
    client, owner, monkeypatch
):
    """Repeat invocations stop before a SUMIT connector can be used."""
    from cfo.database import SessionLocal
    from cfo.models import SyncCheckpoint

    org_id = owner["user"]["organization_id"]
    db = SessionLocal()
    try:
        db.query(SyncCheckpoint).filter(
            SyncCheckpoint.organization_id == org_id,
            SyncCheckpoint.source == "sumit",
            SyncCheckpoint.entity_type == "expense_supplier_enrichment",
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

    calls = []

    async def fake_resolve(self, limit=None, delay=0.4):
        calls.append((self.organization_id, limit))
        return {
            "resolved": 0,
            "tax_ids": 0,
            "reclassified": 0,
            "scanned": 0,
            "rate_limited": False,
        }

    monkeypatch.setattr(
        "cfo.services.expense_filing_service.ExpenseFilingService.resolve_supplier_names",
        fake_resolve,
    )
    headers = {"Authorization": "Bearer test-cron-secret"}

    first = client.get("/api/cron/enrich-expenses", headers=headers)
    second = client.get("/api/cron/enrich-expenses", headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert calls.count((org_id, 25)) == 1
    target_result = next(
        item for item in second.json()["results"]
        if item["organization_id"] == org_id
    )
    assert target_result == {
        "organization_id": org_id,
        "source": "sumit",
        "skipped": "daily_budget",
    }


def test_failed_expense_enrichment_keeps_daily_cooldown(
    client, owner, monkeypatch
):
    """Failure is not permission to retry a billable provider operation."""
    from cfo.database import SessionLocal
    from cfo.models import SyncCheckpoint

    org_id = owner["user"]["organization_id"]
    db = SessionLocal()
    try:
        db.query(SyncCheckpoint).filter(
            SyncCheckpoint.organization_id == org_id,
            SyncCheckpoint.source == "sumit",
            SyncCheckpoint.entity_type == "expense_supplier_enrichment",
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

    calls = []

    async def failing_resolve(self, limit=None, delay=0.4):
        calls.append(self.organization_id)
        raise RuntimeError("SUMIT 403")

    monkeypatch.setattr(
        "cfo.services.expense_filing_service.ExpenseFilingService.resolve_supplier_names",
        failing_resolve,
    )
    headers = {"Authorization": "Bearer test-cron-secret"}

    first = client.get("/api/cron/enrich-expenses", headers=headers)
    second = client.get("/api/cron/enrich-expenses", headers=headers)

    assert first.status_code == 200
    first_target = next(
        item for item in first.json()["results"]
        if item["organization_id"] == org_id
    )
    second_target = next(
        item for item in second.json()["results"]
        if item["organization_id"] == org_id
    )
    assert first_target["error"] == "SUMIT 403"
    assert second_target["skipped"] == "daily_budget"
    assert calls.count(org_id) == 1

    db = SessionLocal()
    try:
        checkpoint = db.query(SyncCheckpoint).filter(
            SyncCheckpoint.organization_id == org_id,
            SyncCheckpoint.source == "sumit",
            SyncCheckpoint.entity_type == "expense_supplier_enrichment",
        ).one()
        assert checkpoint.last_success_at is None
        assert checkpoint.consecutive_failures == 1
        assert checkpoint.cooldown_until > datetime.utcnow()
    finally:
        db.close()


def test_ocr_cron_stops_before_sumit_when_llm_is_disabled(
    client, monkeypatch
):
    from cfo.config import settings

    calls = []

    async def must_not_run(self, *args, **kwargs):
        calls.append(True)
        raise AssertionError("OCR scheduler reached while LLM is disabled")

    monkeypatch.setattr(settings, "ocr_llm_enabled", False)
    monkeypatch.setattr(
        "cfo.services.expense_ocr_scheduler.ExpenseOCRScheduler.run_scheduled_ocr",
        must_not_run,
    )

    response = client.get(
        "/api/cron/process-ocr",
        headers={"Authorization": "Bearer test-cron-secret"},
    )

    assert response.status_code == 200
    assert response.json()["skipped"] == "ocr_llm_disabled"
    assert calls == []


def test_ocr_cron_claims_daily_budget_before_processing(
    client, owner, monkeypatch
):
    from cfo.config import settings
    from cfo.database import SessionLocal
    from cfo.models import IntegrationConnection, SyncCheckpoint

    org_id = owner["user"]["organization_id"]
    db = SessionLocal()
    try:
        connection = db.query(IntegrationConnection).filter(
            IntegrationConnection.organization_id == org_id,
            IntegrationConnection.source == "sumit",
        ).one_or_none()
        if connection is None:
            db.add(IntegrationConnection(
                organization_id=org_id,
                source="sumit",
                status="active",
            ))
        else:
            connection.status = "active"
        db.query(SyncCheckpoint).filter(
            SyncCheckpoint.organization_id == org_id,
            SyncCheckpoint.source == "sumit",
            SyncCheckpoint.entity_type == "expense_ocr_pipeline",
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

    calls = []

    async def fake_run(self, organization_id, limit=50, auto_file=True, **kwargs):
        calls.append((organization_id, limit, auto_file))
        return {"scanned": 0, "filed": 0, "flagged": 0, "errors": 0, "results": []}

    monkeypatch.setattr(settings, "ocr_llm_enabled", True)
    monkeypatch.setattr(settings, "ocr_daily_document_limit", 10, raising=False)
    monkeypatch.setattr(
        "cfo.services.expense_ocr_scheduler.ExpenseOCRScheduler.run_scheduled_ocr",
        fake_run,
    )
    headers = {"Authorization": "Bearer test-cron-secret"}

    first = client.get("/api/cron/process-ocr", headers=headers)
    second = client.get("/api/cron/process-ocr", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls.count((org_id, 10, True)) == 1
    target_result = next(
        item for item in second.json()["results"]
        if item["organization_id"] == org_id
    )
    assert target_result == {
        "organization_id": org_id,
        "source": "sumit",
        "skipped": "daily_budget",
    }
