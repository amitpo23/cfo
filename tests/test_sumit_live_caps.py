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

    for _ in range(3):
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
        assert alerts[0].meta["today_count"] == 3
        assert alerts[0].meta["median_14d"] == 1
    finally:
        db.close()


def test_no_spike_without_a_baseline(fresh_org):
    org_id = fresh_org()["org_id"]
    now = datetime(2026, 6, 20, 15, tzinfo=timezone.utc)
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
    finally:
        db.close()
