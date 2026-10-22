"""Account-wide SUMIT ceilings: one monthly total, no automatic calls.

The per-office window treats an unlinked file as its own office, so a
50-call cap per office is 50 times the number of offices. These tests
pin the shared account window and the default-off automatic-call flag.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import event

from cfo.config import Settings, settings
from cfo.database import SessionLocal, engine
from cfo.integrations.sumit_integration import (
    SUMIT_TEST_CORPORATE_NUMBER,
    SumitIntegration,
    _SUMIT_ENVIRONMENT_CACHE,
)
from cfo.models import Organization, ProviderRequestBudget, SumitCompany
from cfo.services.collection_service import PlannedReminder
from cfo.services.sumit_quota import (
    ACCOUNT_PAID_SCOPE,
    QuotaSnapshot,
    SumitQuotaExhausted,
    account_monthly_paid_limit,
    assert_paid_action_within_quota,
)
from cfo.services.sumit_request_budget import (
    ACCOUNT_REQUEST_SCOPE,
    LIVE_ACCOUNT_REQUEST_HARD_CAP,
    SumitRequestBudgetExceeded,
    SumitRequestLimiter,
    account_monthly_request_limit,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clear_budgets(client):
    db = SessionLocal()
    try:
        db.query(ProviderRequestBudget).delete()
        db.commit()
        yield
    finally:
        db.query(ProviderRequestBudget).delete()
        db.commit()
        db.close()


def _link_offices(pairs: list[tuple[int, int]]) -> None:
    db = SessionLocal()
    try:
        for office_id, client_id in pairs:
            db.add(SumitCompany(
                office_organization_id=office_id,
                company_id=f"acct-{office_id}-{client_id}",
                name=f"file-{client_id}",
                target_organization_id=client_id,
                status="active",
            ))
        db.commit()
    finally:
        db.close()


def _used(scope_key: str) -> int:
    db = SessionLocal()
    try:
        row = db.query(ProviderRequestBudget.used).filter_by(
            provider="sumit", scope_key=scope_key, window_kind="month",
        ).one()
        return int(row[0])
    finally:
        db.close()


def _live_request_ceiling(monkeypatch) -> None:
    """Live account cap stays 50 even if the setting is raised.

    The minute ceiling is lifted only inside this test so 51 claims can
    happen in one UTC minute. The account function still refuses anything
    above 50.
    """
    monkeypatch.setattr(settings, "sumit_environment", "live")
    monkeypatch.setattr(settings, "sumit_live_monthly_request_limit", 999)
    monkeypatch.setattr(settings, "sumit_global_requests_per_minute", 80)
    monkeypatch.setattr(settings, "sumit_org_daily_request_limit", 80)


def test_account_cap_blocks_the_51st_request_across_offices(monkeypatch, fresh_org):
    _live_request_ceiling(monkeypatch)
    offices = [fresh_org()["org_id"] for _ in range(3)]
    clients = [fresh_org()["org_id"] for _ in range(3)]
    _link_offices(list(zip(offices, clients)))

    counts = (20, 20, 10)
    for org_id, count in zip(clients, counts):
        limiter = SumitRequestLimiter(org_id, per_minute_limit=80, daily_limit=80)
        for index in range(count):
            limiter.claim(f"/{org_id}/{index}")

    with pytest.raises(SumitRequestBudgetExceeded, match="account monthly"):
        SumitRequestLimiter(clients[0], per_minute_limit=80, daily_limit=80).claim("/51")

    assert account_monthly_request_limit() == LIVE_ACCOUNT_REQUEST_HARD_CAP
    assert _used(ACCOUNT_REQUEST_SCOPE) == 50
    for office_id, count in zip(offices, counts):
        assert _used(f"office:{office_id}") == count


def test_concurrent_claims_stop_at_the_account_cap(monkeypatch, fresh_org):
    _live_request_ceiling(monkeypatch)
    org_id = fresh_org()["org_id"]
    successes: list[int] = []
    failures: list[str] = []

    def _busy(dbapi_connection, _record, _proxy):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    event.listen(engine, "checkout", _busy)

    def _once(index: int) -> None:
        try:
            SumitRequestLimiter(
                org_id, per_minute_limit=80, daily_limit=80,
            ).claim(f"/race-{index}")
        except SumitRequestBudgetExceeded as exc:
            failures.append(str(exc))
        else:
            successes.append(index)

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(_once, range(70)))
    finally:
        event.remove(engine, "checkout", _busy)

    assert len(successes) == LIVE_ACCOUNT_REQUEST_HARD_CAP
    assert len(failures) == 20
    assert all("account monthly" in item for item in failures)
    assert _used(ACCOUNT_REQUEST_SCOPE) == LIVE_ACCOUNT_REQUEST_HARD_CAP


def test_paid_account_cap_blocks_the_11th_action_across_offices(
    monkeypatch, fresh_org,
):
    monkeypatch.setattr(settings, "sumit_environment", "live")
    monkeypatch.setattr(settings, "sumit_document_issuance_enabled", True)
    monkeypatch.setattr(settings, "sumit_live_monthly_paid_action_limit", 100)
    monkeypatch.setattr(
        "cfo.services.sumit_quota.paced_daily_limit",
        lambda **kwargs: kwargs["configured_daily"],
    )
    offices = [fresh_org()["org_id"] for _ in range(3)]
    clients = [fresh_org()["org_id"] for _ in range(3)]
    _link_offices(list(zip(offices, clients)))
    measured = datetime.now(timezone.utc)

    def _claim(org_id: int) -> None:
        assert_paid_action_within_quota(
            QuotaSnapshot(
                organization_id=org_id, used=0, limit=50, measured_at=measured,
            ),
            endpoint="/accounting/documents/create/",
        )

    for org_id, count in zip(clients, (4, 3, 3)):
        for _ in range(count):
            _claim(org_id)

    with pytest.raises(SumitQuotaExhausted, match="account monthly paid-action"):
        _claim(clients[1])

    assert account_monthly_paid_limit() == 10
    assert _used(ACCOUNT_PAID_SCOPE) == 10
    for office_id, count in zip(offices, (4, 3, 3)):
        assert _used(f"paid:office:{office_id}") == count


def test_environment_verification_consumes_the_account_budget(
    monkeypatch, fresh_org,
):
    org_id = fresh_org()["org_id"]
    monkeypatch.setattr(settings, "sumit_environment", "test")
    monkeypatch.setattr(settings, "sumit_test_monthly_request_limit", 1)
    client = SumitIntegration(
        api_key="c0ffee00-1111-4222-8333-444455556666",
        company_id="1",
        request_limiter=SumitRequestLimiter(org_id, per_minute_limit=10, daily_limit=10),
    )
    _SUMIT_ENVIRONMENT_CACHE.pop(client._environment_cache_key(), None)
    seen: list[str] = []

    async def fake_request(*, url, **_kwargs):
        seen.append(url)
        return _CompanyResponse()

    monkeypatch.setattr(client.client, "request", fake_request)
    import asyncio
    with pytest.raises(SumitRequestBudgetExceeded, match="account monthly"):
        asyncio.run(client._make_request("/accounting/documents/list/"))
    asyncio.run(client.client.aclose())

    assert seen == ["/website/companies/getdetails/"]
    assert _used(ACCOUNT_REQUEST_SCOPE) == 1


class _CompanyResponse:
    status_code = 200
    text = "{}"

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "Status": 0,
            "Data": {"Company": {"CorporateNumber": SUMIT_TEST_CORPORATE_NUMBER}},
        }


def test_automatic_sumit_calls_default_off():
    loaded = Settings(_env_file=None)
    assert loaded.sumit_automatic_calls_enabled is False


def test_crons_make_zero_sumit_requests_when_automatic_calls_are_off(platform_admin, 
    client, owner, fresh_org, monkeypatch,
):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        org = db.get(Organization, org_id)
        org.collection_reminders_enabled = True
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(settings, "sumit_automatic_calls_enabled", False)
    calls: list[str] = []

    async def forbidden(self, *args, **kwargs):
        calls.append(getattr(self, "base_url", None) and str(args[:1]))
        raise AssertionError(f"SUMIT HTTP was called: {args!r} {kwargs!r}")

    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "post", forbidden)

    async def forbidden_make(self, endpoint, *args, **kwargs):
        calls.append(endpoint)
        raise AssertionError(f"SUMIT _make_request was called: {endpoint}")

    monkeypatch.setattr(SumitIntegration, "_make_request", forbidden_make)
    monkeypatch.setattr(
        "cfo.api.routes.cron.CollectionService.plan_reminders",
        lambda self, _today: [PlannedReminder(
            contact_id=1,
            contact_name="לקוח",
            email="customer@example.com",
            phone="0500000000",
            invoice_numbers=["INV-1"],
            total_amount=10.0,
            days_overdue=3,
            reminder_type="overdue",
            message="pay",
        )] if self.org_id == org_id else [],
    )

    async def no_email(*_args, **_kwargs):
        return False

    monkeypatch.setattr("cfo.api.routes.cron.send_email_smtp", no_email)
    denied = client.get(
        "/api/cron/sync-sumit",
        headers={"Authorization": "Bearer test-cron-secret"},
    )
    assert denied.status_code == 401
    headers = platform_admin["headers"]
    responses = {}
    for path in (
        "/api/cron/refresh-sumit-quota",
        "/api/cron/sync-sumit",
        "/api/cron/sync",
        "/api/cron/enrich-expenses",
        "/api/cron/process-ocr",
        "/api/cron/collection-reminders",
    ):
        response = client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        responses[path] = response.json()

    for path in (
        "/api/cron/refresh-sumit-quota",
        "/api/cron/sync-sumit",
        "/api/cron/sync",
        "/api/cron/enrich-expenses",
        "/api/cron/process-ocr",
    ):
        assert responses[path]["skipped"] == "sumit_automatic_calls_disabled"
        assert responses[path]["results"] == []
    summary = responses["/api/cron/collection-reminders"]["summary"]
    assert summary["skipped_sumit_automatic_disabled"] >= 1
    assert calls == []

    schedule = json.loads((ROOT / "vercel.json").read_text())
    scheduled = {job["path"] for job in schedule["crons"]}
    for path in (
        "/api/cron/sync-sumit",
        "/api/cron/sync",
        "/api/cron/refresh-sumit-quota",
        "/api/cron/collection-reminders",
        "/api/cron/enrich-expenses",
        "/api/cron/process-ocr",
    ):
        assert path not in scheduled


def test_refresh_reaches_sumit_only_after_the_flag_is_enabled(platform_admin, 
    client, owner, monkeypatch,
):
    """An admin request reaches SUMIT only after the flag is on.
    The cron secret cannot call the route."""
    monkeypatch.setattr(settings, "sumit_automatic_calls_enabled", True)
    reached = {"connector": 0}

    class _Client:
        async def aclose(self):
            return None

    class _Integration:
        client = _Client()

    class _Connector:
        async def _get_client(self):
            reached["connector"] += 1
            return _Integration()

    monkeypatch.setattr(
        "cfo.services.sync_engine.get_connector_for_org",
        lambda *_args, **_kwargs: (_Connector(), 1, "sumit"),
    )

    async def _refresh(*_args, **_kwargs):
        reached["connector"] += 1
        return None

    monkeypatch.setattr(
        "cfo.services.sumit_quota.refresh_quota_measurement",
        _refresh,
    )
    secret = client.get(
        "/api/cron/refresh-sumit-quota",
        headers={"Authorization": "Bearer test-cron-secret"},
    )
    assert secret.status_code == 401
    response = client.get("/api/cron/refresh-sumit-quota", headers=platform_admin["headers"])
    assert response.status_code == 200, response.text
    assert response.json().get("skipped") != "sumit_automatic_calls_disabled"
    assert reached["connector"] >= 1


_ON_DEMAND_SUMIT_ROUTES = (
    "/api/cron/refresh-sumit-quota",
    "/api/cron/sync-sumit",
    "/api/cron/sync",
    "/api/cron/enrich-expenses",
    "/api/cron/process-ocr",
    "/api/cron/collection-reminders",
)


def test_on_demand_sumit_routes_refuse_an_organization_admin(client, owner, fresh_org):
    """They run for every organization, so a tenant admin cannot start them."""
    tenant_admin = fresh_org()
    for headers in (owner["headers"], tenant_admin["headers"]):
        for path in _ON_DEMAND_SUMIT_ROUTES:
            assert client.get(path, headers=headers).status_code == 403, path


def _forbid_sumit_clients(monkeypatch) -> list[str]:
    from cfo.services.sumit_connector import SumitConnector

    built: list[str] = []

    def no_integration(self, *args, **kwargs):
        built.append("SumitIntegration")
        raise AssertionError("SumitIntegration was constructed")

    def no_connector(self, *args, **kwargs):
        built.append("SumitConnector")
        raise AssertionError("SumitConnector was constructed")

    monkeypatch.setattr(SumitIntegration, "__init__", no_integration)
    monkeypatch.setattr(SumitConnector, "__init__", no_connector)
    return built


def test_every_scheduled_cron_builds_no_sumit_client(client, owner, monkeypatch):
    """Whatever stays on the Vercel schedule must not reach SUMIT.

    Org 1 has the env SUMIT key in tests, so any path that resolves a SUMIT
    client for it would construct one here.
    """
    monkeypatch.setattr(settings, "sumit_automatic_calls_enabled", False)
    built = _forbid_sumit_clients(monkeypatch)
    schedule = json.loads((ROOT / "vercel.json").read_text())
    for job in schedule["crons"]:
        response = client.get(job["path"], headers={"Authorization": "Bearer test-cron-secret"})
        assert response.status_code < 500, (job["path"], response.text)
    assert built == []


def test_sumit_webhook_and_credential_save_start_no_sumit_work(client, fresh_org, monkeypatch):
    import asyncio

    from cfo.services import onboarding_service, webhook_delta_sync as wds

    monkeypatch.setattr(settings, "sumit_automatic_calls_enabled", False)
    built = _forbid_sumit_clients(monkeypatch)
    claimed: list[int] = []
    monkeypatch.setattr(wds, "_resolve_sumit_org", lambda _db, _payload: 1)
    monkeypatch.setattr(wds, "_claim_webhook_budget", lambda org_id, _src: claimed.append(org_id))
    db = SessionLocal()
    try:
        result = asyncio.run(wds.handle_sumit_trigger_event(db, {"DocumentID": "7"}))
    finally:
        db.close()
    assert result["reason"] == "sumit_automatic_calls_disabled"
    assert claimed == []

    started: list[tuple] = []

    async def record(org_id, source="sumit"):
        started.append((org_id, source))

    monkeypatch.setattr(onboarding_service, "run_onboarding_bg", record)
    saved = client.post("/api/integration/sumit/configure", json={
        "api_key": "wide-cap-test-key", "company_id": "wide-cap-test-file",
    }, headers=fresh_org()["headers"])
    assert saved.status_code == 200, saved.text
    assert started == []
    assert built == []
