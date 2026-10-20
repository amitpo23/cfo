"""Live SUMIT caps stay inside the exempt plan, and usage is ledgered.

Owner directive 2026-10-20: the office account is on SUMIT's exempt plan
(about 50 included API calls / month, 10 included actions). Live mode must
not silently raise the daily, minute, monthly or paid-action caps. Document
issuance stays off unless SUMIT_DOCUMENT_ISSUANCE_ENABLED is set.
"""
from datetime import datetime, timedelta, timezone

import pytest

from cfo.config import Settings, settings
from cfo.database import SessionLocal
from cfo.integrations.sumit_integration import (
    SUMIT_TEST_CORPORATE_NUMBER,
    SumitIntegration,
)
from cfo.models import Alert, ProviderCallLog
from cfo.services.sumit_quota import (
    QuotaSnapshot,
    SumitQuotaExhausted,
    assert_paid_action_within_quota,
)
from cfo.services.sumit_request_budget import SumitRequestLimiter
from cfo.services.sumit_usage import record_sumit_call


def test_live_mode_clamps_to_exempt_plan_and_does_not_raise_caps():
    live = Settings(
        _env_file=None,
        sumit_environment="live",
        sumit_org_daily_request_limit=300,
        sumit_global_requests_per_minute=80,
        sumit_live_monthly_request_limit=200,
        sumit_live_monthly_paid_action_limit=90,
        sumit_live_org_daily_request_limit=99,
        sumit_live_requests_per_minute=80,
    )
    assert live.sumit_live_monthly_request_limit == 50
    assert live.sumit_org_daily_request_limit == 10
    assert live.sumit_global_requests_per_minute == 10
    assert live.sumit_live_monthly_paid_action_limit == 0
    assert live.sumit_document_issuance_enabled is False

    lowered = Settings(
        _env_file=None,
        sumit_environment="live",
        sumit_org_daily_request_limit=4,
        sumit_live_org_daily_request_limit=4,
        sumit_global_requests_per_minute=2,
        sumit_live_requests_per_minute=2,
        sumit_live_monthly_request_limit=12,
    )
    assert lowered.sumit_org_daily_request_limit == 4
    assert lowered.sumit_global_requests_per_minute == 2
    assert lowered.sumit_live_monthly_request_limit == 12


def test_document_issuance_stays_off_until_explicitly_enabled():
    enabled = Settings(
        _env_file=None,
        sumit_environment="live",
        sumit_document_issuance_enabled=True,
        sumit_live_monthly_paid_action_limit=90,
    )
    assert enabled.sumit_live_monthly_paid_action_limit == 10


def test_live_paid_action_is_refused_without_the_issuance_flag(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    monkeypatch.setattr(settings, "sumit_environment", "live")
    monkeypatch.setattr(settings, "sumit_document_issuance_enabled", False)
    monkeypatch.setattr(settings, "sumit_live_monthly_paid_action_limit", 5)
    snapshot = QuotaSnapshot(
        organization_id=org_id, used=0, limit=50,
        measured_at=datetime.now(timezone.utc),
    )
    with pytest.raises(SumitQuotaExhausted, match="monthly"):
        assert_paid_action_within_quota(snapshot, endpoint="/accounting/documents/create/")


def test_usage_reaches_seventy_percent_once(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    monkeypatch.setattr(settings, "sumit_environment", "test")
    monkeypatch.setattr(settings, "sumit_test_monthly_request_limit", 10)
    now = datetime(2026, 6, 20, 12, tzinfo=timezone.utc)
    for _ in range(7):
        record_sumit_call(
            organization_id=org_id,
            endpoint="/accounting/documents/list/?api_key=should-not-be-stored",
            outcome="success",
            purpose="sync",
            now=now,
        )
    db = SessionLocal()
    try:
        rows = db.query(ProviderCallLog).filter_by(organization_id=org_id).all()
        assert len(rows) == 7
        assert all("api_key" not in row.endpoint for row in rows)
        assert all(row.endpoint == "/accounting/documents/list/" for row in rows)
        alerts = db.query(Alert).filter_by(
            organization_id=org_id, alert_type="sumit_usage_cap",
        ).all()
        assert len(alerts) == 1
    finally:
        db.close()

    record_sumit_call(
        organization_id=org_id, endpoint="/accounting/documents/list/",
        outcome="success", purpose="sync", now=now,
    )
    db = SessionLocal()
    try:
        assert db.query(Alert).filter_by(
            organization_id=org_id, alert_type="sumit_usage_cap",
        ).count() == 1
    finally:
        db.close()


def test_daily_usage_above_twice_the_14_day_median_alerts_once(fresh_org):
    org_id = fresh_org()["org_id"]
    now = datetime(2026, 6, 20, 15, tzinfo=timezone.utc)
    db = SessionLocal()
    try:
        for offset in range(1, 15):
            db.add(ProviderCallLog(
                provider="sumit",
                organization_id=org_id,
                purpose="sync",
                endpoint_class="inferred",
                endpoint="/accounting/documents/list/",
                outcome="success",
                at=now - timedelta(days=offset),
            ))
        db.commit()
    finally:
        db.close()

    for _ in range(5):
        record_sumit_call(
            organization_id=org_id,
            endpoint="/accounting/documents/list/",
            outcome="success",
            purpose="sync",
            now=now,
        )
    db = SessionLocal()
    try:
        alerts = db.query(Alert).filter_by(
            organization_id=org_id, alert_type="sumit_usage_spike",
        ).all()
        assert len(alerts) == 1
        assert alerts[0].meta["today_count"] == 5
        assert alerts[0].meta["median_14d"] == 1
        assert alerts[0].meta["threshold"] == 5
    finally:
        db.close()


def test_fewer_than_five_calls_are_not_a_spike(fresh_org):
    org_id = fresh_org()["org_id"]
    now = datetime(2026, 6, 20, 15, tzinfo=timezone.utc)
    for _ in range(4):
        record_sumit_call(
            organization_id=org_id, endpoint="/accounting/documents/list/",
            outcome="success", purpose="sync", now=now,
        )
    db = SessionLocal()
    try:
        assert db.query(Alert).filter_by(
            organization_id=org_id, alert_type="sumit_usage_spike",
        ).count() == 0
    finally:
        db.close()


def test_cap_alert_is_keyed_by_month(fresh_org, monkeypatch):
    org_id = fresh_org()["org_id"]
    monkeypatch.setattr(settings, "sumit_environment", "test")
    monkeypatch.setattr(settings, "sumit_test_monthly_request_limit", 10)
    june = datetime(2026, 6, 20, 12, tzinfo=timezone.utc)
    july = datetime(2026, 7, 2, 12, tzinfo=timezone.utc)
    for moment in (june, july):
        for _ in range(7):
            record_sumit_call(
                organization_id=org_id, endpoint="/accounting/documents/list/",
                outcome="success", purpose="sync", now=moment,
            )
    db = SessionLocal()
    try:
        alerts = db.query(Alert).filter_by(
            organization_id=org_id, alert_type="sumit_usage_cap",
        ).all()
        assert {row.meta["month"] for row in alerts} == {"2026-06", "2026-07"}
    finally:
        db.close()


def test_office_window_is_shared_across_client_files(fresh_org, monkeypatch):
    office = fresh_org()["org_id"]
    first = fresh_org()["org_id"]
    second = fresh_org()["org_id"]
    monkeypatch.setattr(settings, "sumit_environment", "live")
    monkeypatch.setattr(settings, "sumit_live_monthly_request_limit", 2)
    monkeypatch.setattr(settings, "sumit_live_org_daily_request_limit", 10)
    monkeypatch.setattr(
        "cfo.services.sumit_request_budget.paced_daily_limit",
        lambda **kwargs: kwargs["configured_daily"],
    )
    from cfo.models import SumitCompany
    db = SessionLocal()
    try:
        db.add(SumitCompany(
            office_organization_id=office, company_id="11", name="א",
            target_organization_id=first, status="active",
        ))
        db.add(SumitCompany(
            office_organization_id=office, company_id="12", name="ב",
            target_organization_id=second, status="active",
        ))
        db.commit()
    finally:
        db.close()
    from cfo.services.sumit_request_budget import SumitRequestBudgetExceeded
    SumitRequestLimiter(first, per_minute_limit=10, daily_limit=10).claim("/one")
    SumitRequestLimiter(second, per_minute_limit=10, daily_limit=10).claim("/two")
    with pytest.raises(SumitRequestBudgetExceeded, match="office monthly"):
        SumitRequestLimiter(first, per_minute_limit=10, daily_limit=10).claim("/three")
    record_sumit_call(
        organization_id=first, endpoint="/accounting/documents/list/",
        outcome="success", purpose="sync",
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    db = SessionLocal()
    try:
        row = db.query(ProviderCallLog).filter_by(organization_id=first).one()
        assert row.office_organization_id == office
    finally:
        db.close()


def test_inactive_office_link_is_not_the_shared_window(fresh_org):
    file_org = fresh_org()["org_id"]
    old_office = fresh_org()["org_id"]
    new_office = fresh_org()["org_id"]
    from cfo.models import SumitCompany
    from cfo.services.sumit_request_budget import resolve_office_organization_id

    db = SessionLocal()
    try:
        db.add(SumitCompany(
            office_organization_id=old_office, company_id="old", name="ישן",
            target_organization_id=file_org, status="inactive",
        ))
        db.add(SumitCompany(
            office_organization_id=new_office, company_id="new", name="חדש",
            target_organization_id=file_org, status="active",
        ))
        db.commit()
        assert resolve_office_organization_id(db, file_org) == new_office
        current = db.query(SumitCompany).filter_by(company_id="new").one()
        current.status = "inactive"
        db.commit()
        assert resolve_office_organization_id(db, file_org) == file_org
    finally:
        db.close()


def test_office_paid_action_cap_is_ten_across_client_files(fresh_org, monkeypatch):
    office = fresh_org()["org_id"]
    first = fresh_org()["org_id"]
    second = fresh_org()["org_id"]
    monkeypatch.setattr(settings, "sumit_environment", "live")
    monkeypatch.setattr(settings, "sumit_document_issuance_enabled", True)
    monkeypatch.setattr(settings, "sumit_live_monthly_paid_action_limit", 100)
    monkeypatch.setattr(
        "cfo.services.sumit_quota.paced_daily_limit",
        lambda **kwargs: kwargs["configured_daily"],
    )
    from cfo.models import SumitCompany
    db = SessionLocal()
    try:
        db.add(SumitCompany(
            office_organization_id=office, company_id="21", name="א",
            target_organization_id=first, status="active",
        ))
        db.add(SumitCompany(
            office_organization_id=office, company_id="22", name="ב",
            target_organization_id=second, status="inactive",
        ))
        db.add(SumitCompany(
            office_organization_id=office, company_id="23", name="ג",
            target_organization_id=second, status="active",
        ))
        db.commit()
    finally:
        db.close()
    measured = datetime.now(timezone.utc)

    def _claim(org_id: int) -> None:
        assert_paid_action_within_quota(
            QuotaSnapshot(organization_id=org_id, used=0, limit=50, measured_at=measured),
            endpoint="/accounting/documents/create/",
        )

    for _ in range(6):
        _claim(first)
    for _ in range(4):
        _claim(second)
    with pytest.raises(SumitQuotaExhausted, match="office monthly paid-action"):
        _claim(first)


class _Response:
    status_code = 200
    text = "{}"

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


@pytest.mark.asyncio
async def test_make_request_writes_a_ledger_row_and_no_secret(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    monkeypatch.setattr(settings, "sumit_environment", "test")
    client = SumitIntegration(
        api_key="9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23",
        company_id="1",
        request_limiter=SumitRequestLimiter(org_id),
    )
    secret = client.api_key

    async def fake_request(*, url, **_kwargs):
        assert secret not in url
        if url == "/website/companies/getdetails/":
            return _Response({
                "Status": 0,
                "Data": {"Company": {"CorporateNumber": SUMIT_TEST_CORPORATE_NUMBER}},
            })
        return _Response({"Status": 0, "Data": {}})

    monkeypatch.setattr(client.client, "request", fake_request)
    await client._make_request("/accounting/documents/list/", data={"Credentials": {"APIKey": secret}})
    await client.client.aclose()

    db = SessionLocal()
    try:
        rows = db.query(ProviderCallLog).filter_by(organization_id=org_id).all()
        assert rows
        blob = " ".join(row.endpoint for row in rows)
        assert secret not in blob
        assert "APIKey" not in blob
        assert any(row.purpose == "ops" for row in rows)
        assert all(row.office_organization_id == org_id for row in rows)
    finally:
        db.close()


@pytest.mark.asyncio
async def test_getpdf_records_a_failed_attempt(monkeypatch, fresh_org):
    import httpx
    from cfo.integrations.sumit_integration import SumitAPIError, _SUMIT_ENVIRONMENT_CACHE

    org_id = fresh_org()["org_id"]
    monkeypatch.setattr(settings, "sumit_environment", "test")
    client = SumitIntegration(
        api_key="9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23",
        company_id="1",
        request_limiter=SumitRequestLimiter(org_id),
    )
    monkeypatch.setattr(client, "_enforce_paid_action_budget", lambda _endpoint: None)
    _SUMIT_ENVIRONMENT_CACHE[client._environment_cache_key()] = datetime.now(timezone.utc)

    async def fake_post(url, json=None, **_kwargs):
        request = httpx.Request("POST", "https://api.sumit.co.il" + url)
        return httpx.Response(404, request=request, text="missing")

    monkeypatch.setattr(client.client, "post", fake_post)
    with pytest.raises(SumitAPIError):
        await client._post_binary("/accounting/documents/getpdf/", {})
    await client.client.aclose()

    db = SessionLocal()
    try:
        row = db.query(ProviderCallLog).filter_by(
            organization_id=org_id, endpoint="/accounting/documents/getpdf/",
        ).one()
        assert row.outcome == "http_error"
        assert row.office_organization_id == org_id
    finally:
        db.close()
