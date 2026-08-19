"""Strict SUMIT test-track isolation and monthly budget regression tests."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from cfo.config import Settings
from cfo.database import SessionLocal
from cfo.integrations import sumit_integration
from cfo.integrations.sumit_integration import (
    SUMIT_TEST_CORPORATE_NUMBER,
    SumitEnvironmentMismatch,
    SumitIntegration,
)
from cfo.models import ProviderRequestBudget
from cfo.services import sumit_quota, sumit_request_budget
from cfo.services.sumit_request_budget import (
    SumitRequestBudgetExceeded,
    SumitRequestLimiter,
)


REALISTIC_KEY = "9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23"
VERIFY_ENDPOINT = "/website/companies/getdetails/"
LIST_ENDPOINT = "/accounting/documents/list/"


class _RecordingLimiter:
    def __init__(self):
        self.claims = []

    def claim(self, endpoint):
        self.claims.append(endpoint)


class _Response:
    status_code = 200
    text = "{}"
    headers = {"content-type": "application/json"}
    content = b""

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _company_response(corporate_number):
    return _Response({
        "Status": 0,
        "Data": {
            "Company": {
                "CorporateNumber": corporate_number,
                "Name": "Company",
            },
        },
    })


@pytest.fixture(autouse=True)
def _clear_sumit_test_state():
    sumit_integration._SUMIT_ENVIRONMENT_CACHE.clear()
    yield
    sumit_integration._SUMIT_ENVIRONMENT_CACHE.clear()


@pytest.fixture
def cleared_request_budgets(client):
    """The app lifespan creates the local tables before budget tests run."""
    db = SessionLocal()
    try:
        db.query(ProviderRequestBudget).delete()
        db.commit()
        yield
    finally:
        db.query(ProviderRequestBudget).delete()
        db.commit()
        db.close()


def test_settings_default_to_test_and_invalid_values_fail_closed(monkeypatch):
    monkeypatch.delenv("SUMIT_ENVIRONMENT", raising=False)

    assert Settings(_env_file=None).sumit_environment == "test"
    assert Settings(_env_file=None, sumit_environment=" LIVE ").sumit_environment == "live"
    assert Settings(_env_file=None, sumit_environment="production").sumit_environment == "test"
    assert Settings(_env_file=None, sumit_environment=None).sumit_environment == "test"


def test_test_mode_clamps_never_raise_the_kill_switch():
    killed = Settings(
        _env_file=None,
        sumit_environment="test",
        sumit_global_requests_per_minute=0,
        sumit_org_daily_request_limit=0,
    )
    oversized = Settings(
        _env_file=None,
        sumit_environment="test",
        sumit_global_requests_per_minute=80,
        sumit_org_daily_request_limit=300,
    )

    assert killed.sumit_global_requests_per_minute == 0
    assert killed.sumit_org_daily_request_limit == 0
    assert oversized.sumit_global_requests_per_minute == 10
    assert oversized.sumit_org_daily_request_limit == 20


@pytest.mark.asyncio
async def test_test_mode_rejects_a_live_company_before_the_requested_call(monkeypatch):
    monkeypatch.setattr(sumit_integration.settings, "sumit_environment", "test")
    limiter = _RecordingLimiter()
    client = SumitIntegration(
        api_key=REALISTIC_KEY,
        company_id="1",
        request_limiter=limiter,
    )
    sent = []

    async def fake_request(*, url, **_kwargs):
        sent.append(url)
        if url == VERIFY_ENDPOINT:
            return _company_response("515151515")
        raise AssertionError("non-verification request reached SUMIT")

    monkeypatch.setattr(client.client, "request", fake_request)
    with pytest.raises(SumitEnvironmentMismatch):
        await client._make_request(LIST_ENDPOINT)

    assert sent == [VERIFY_ENDPOINT]
    assert limiter.claims == [VERIFY_ENDPOINT]
    await client.client.aclose()


@pytest.mark.asyncio
async def test_test_mode_allows_a_verified_test_company(monkeypatch):
    monkeypatch.setattr(sumit_integration.settings, "sumit_environment", "test")
    limiter = _RecordingLimiter()
    client = SumitIntegration(
        api_key=REALISTIC_KEY,
        company_id="1",
        request_limiter=limiter,
    )
    sent = []

    async def fake_request(*, url, **_kwargs):
        sent.append(url)
        if url == VERIFY_ENDPOINT:
            return _company_response(SUMIT_TEST_CORPORATE_NUMBER)
        return _Response({"Status": 0, "Data": {}})

    monkeypatch.setattr(client.client, "request", fake_request)
    await client._make_request(LIST_ENDPOINT)

    assert sent == [VERIFY_ENDPOINT, LIST_ENDPOINT]
    assert limiter.claims == [VERIFY_ENDPOINT, LIST_ENDPOINT]
    await client.client.aclose()


@pytest.mark.asyncio
async def test_live_mode_rejects_a_test_company(monkeypatch):
    monkeypatch.setattr(sumit_integration.settings, "sumit_environment", "live")
    limiter = _RecordingLimiter()
    client = SumitIntegration(
        api_key=REALISTIC_KEY,
        company_id="1",
        request_limiter=limiter,
    )

    async def fake_request(*, url, **_kwargs):
        if url == VERIFY_ENDPOINT:
            return _company_response(SUMIT_TEST_CORPORATE_NUMBER)
        raise AssertionError("non-verification request reached SUMIT")

    monkeypatch.setattr(client.client, "request", fake_request)
    with pytest.raises(SumitEnvironmentMismatch):
        await client._make_request(LIST_ENDPOINT)

    assert limiter.claims == [VERIFY_ENDPOINT]
    await client.client.aclose()


@pytest.mark.parametrize("failure", ["network", "malformed"])
@pytest.mark.asyncio
async def test_verification_failure_is_an_environment_mismatch(monkeypatch, failure):
    monkeypatch.setattr(sumit_integration.settings, "sumit_environment", "test")
    limiter = _RecordingLimiter()
    client = SumitIntegration(
        api_key=REALISTIC_KEY,
        company_id="1",
        request_limiter=limiter,
    )

    async def fake_request(*, url, **_kwargs):
        assert url == VERIFY_ENDPOINT
        if failure == "network":
            raise httpx.ConnectError("offline failure")
        return _Response({"Status": 0, "Data": {"Company": {}}})

    monkeypatch.setattr(client.client, "request", fake_request)
    with pytest.raises(SumitEnvironmentMismatch):
        await client._make_request(LIST_ENDPOINT)

    assert limiter.claims == [VERIFY_ENDPOINT]
    await client.client.aclose()


@pytest.mark.asyncio
async def test_verification_is_cached_across_clients_with_the_same_key(monkeypatch):
    monkeypatch.setattr(sumit_integration.settings, "sumit_environment", "test")
    first_limiter = _RecordingLimiter()
    second_limiter = _RecordingLimiter()
    first = SumitIntegration(
        api_key=REALISTIC_KEY,
        company_id="1",
        request_limiter=first_limiter,
    )
    second = SumitIntegration(
        api_key=REALISTIC_KEY,
        company_id="1",
        request_limiter=second_limiter,
    )
    sent = []

    async def fake_request(*, url, **_kwargs):
        sent.append(url)
        if url == VERIFY_ENDPOINT:
            return _company_response(SUMIT_TEST_CORPORATE_NUMBER)
        return _Response({"Status": 0, "Data": {}})

    monkeypatch.setattr(first.client, "request", fake_request)
    monkeypatch.setattr(second.client, "request", fake_request)
    await first._make_request(LIST_ENDPOINT)
    await second._make_request(LIST_ENDPOINT)

    assert sent == [VERIFY_ENDPOINT, LIST_ENDPOINT, LIST_ENDPOINT]
    assert first_limiter.claims == [VERIFY_ENDPOINT, LIST_ENDPOINT]
    assert second_limiter.claims == [LIST_ENDPOINT]
    await first.client.aclose()
    await second.client.aclose()


@pytest.mark.asyncio
async def test_environment_cache_expires_after_twenty_hours(monkeypatch):
    monkeypatch.setattr(sumit_integration.settings, "sumit_environment", "test")

    class _Clock(datetime):
        current = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(sumit_integration, "datetime", _Clock)
    sent = []

    async def fake_request(*, url, **_kwargs):
        sent.append(url)
        if url == VERIFY_ENDPOINT:
            return _company_response(SUMIT_TEST_CORPORATE_NUMBER)
        return _Response({"Status": 0, "Data": {}})

    first = SumitIntegration(
        api_key=REALISTIC_KEY,
        company_id="1",
        request_limiter=_RecordingLimiter(),
    )
    monkeypatch.setattr(first.client, "request", fake_request)
    await first._make_request(LIST_ENDPOINT)

    _Clock.current += timedelta(hours=20)
    second = SumitIntegration(
        api_key=REALISTIC_KEY,
        company_id="1",
        request_limiter=_RecordingLimiter(),
    )
    monkeypatch.setattr(second.client, "request", fake_request)
    await second._make_request(LIST_ENDPOINT)

    assert sent == [VERIFY_ENDPOINT, LIST_ENDPOINT, VERIFY_ENDPOINT, LIST_ENDPOINT]
    await first.client.aclose()
    await second.client.aclose()


@pytest.mark.asyncio
async def test_binary_path_checks_environment_before_sending_binary_request(monkeypatch):
    monkeypatch.setattr(sumit_integration.settings, "sumit_environment", "test")
    limiter = _RecordingLimiter()
    client = SumitIntegration(
        api_key=REALISTIC_KEY,
        company_id="1",
        request_limiter=limiter,
    )

    async def fake_request(*, url, **_kwargs):
        assert url == VERIFY_ENDPOINT
        return _company_response("515151515")

    async def forbidden_binary(*_args, **_kwargs):
        raise AssertionError("binary request reached SUMIT")

    monkeypatch.setattr(client.client, "request", fake_request)
    monkeypatch.setattr(client.client, "post", forbidden_binary)
    with pytest.raises(SumitEnvironmentMismatch):
        await client._post_binary("/accounting/documents/getpdf/", {})

    assert limiter.claims == [VERIFY_ENDPOINT]
    await client.client.aclose()


@pytest.mark.asyncio
async def test_environment_verification_respects_a_zero_budget(monkeypatch):
    monkeypatch.setattr(sumit_integration.settings, "sumit_environment", "test")

    class _Killed:
        def __init__(self):
            self.claims = []

        def claim(self, endpoint):
            self.claims.append(endpoint)
            raise SumitRequestBudgetExceeded("kill switch")

    limiter = _Killed()
    client = SumitIntegration(
        api_key=REALISTIC_KEY,
        company_id="1",
        request_limiter=limiter,
    )

    async def forbidden_network(*_args, **_kwargs):
        raise AssertionError("verification bypassed the kill switch")

    monkeypatch.setattr(client.client, "request", forbidden_network)
    with pytest.raises(SumitRequestBudgetExceeded, match="kill switch"):
        await client._make_request(LIST_ENDPOINT)

    assert limiter.claims == [VERIFY_ENDPOINT]
    await client.client.aclose()


def test_test_request_monthly_limit_blocks_and_resets_next_month(
    monkeypatch, fresh_org, cleared_request_budgets,
):
    org_id = fresh_org()["org_id"]
    monkeypatch.setattr(sumit_request_budget.settings, "sumit_environment", "test")
    monkeypatch.setattr(sumit_request_budget.settings, "sumit_global_requests_per_minute", 10)
    monkeypatch.setattr(sumit_request_budget.settings, "sumit_org_daily_request_limit", 20)
    monkeypatch.setattr(sumit_request_budget.settings, "sumit_test_monthly_request_limit", 2)

    class _Clock(datetime):
        current = datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(sumit_request_budget, "datetime", _Clock)
    limiter = SumitRequestLimiter(org_id)

    limiter.claim("/one")
    limiter.claim("/two")
    with pytest.raises(SumitRequestBudgetExceeded, match="monthly"):
        limiter.claim("/three")

    _Clock.current = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
    limiter.claim("/new-month")


def test_test_paid_action_monthly_limit_blocks_and_resets_next_month(
    monkeypatch, fresh_org, cleared_request_budgets,
):
    org_id = fresh_org()["org_id"]
    monkeypatch.setattr(sumit_quota.settings, "sumit_environment", "test")
    monkeypatch.setattr(sumit_quota.settings, "sumit_test_monthly_paid_action_limit", 2)

    class _Clock(datetime):
        current = datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(sumit_quota, "datetime", _Clock)

    def snapshot():
        return sumit_quota.QuotaSnapshot(
            organization_id=org_id,
            used=0,
            limit=500,
            measured_at=_Clock.current,
        )

    sumit_quota.assert_paid_action_within_quota(snapshot(), endpoint="getdetails")
    sumit_quota.assert_paid_action_within_quota(snapshot(), endpoint="getpdf")
    with pytest.raises(sumit_quota.SumitQuotaExhausted, match="monthly"):
        sumit_quota.assert_paid_action_within_quota(snapshot(), endpoint="getdetails")

    _Clock.current = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
    sumit_quota.assert_paid_action_within_quota(snapshot(), endpoint="getdetails")
