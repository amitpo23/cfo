"""תוכנית ההפעלה 19/08/2026 — סעיפים 4.1, 4.3, 4.6.

4.1 — כלי תקציב למושקו: "כמה קריאות נשארו" מה-DB בלבד, אפס קריאות API.
4.3 — הכנת דוח מע"מ לשידור ידני: הרכבה + אימות משולש, הכל מקומי.
4.6 — שער עלות אחיד: כל endpoint שעולה כסף עובר שער תקציב פעולות-בתשלום,
      לא רק getdetails/getpdf.
"""
from datetime import datetime, timezone

import pytest

from cfo.database import SessionLocal
from cfo.integrations import sumit_integration
from cfo.integrations.sumit_integration import (
    PAID_ACTION_ENDPOINTS,
    SumitIntegration,
)
from cfo.models import ProviderRequestBudget
from cfo.services import sumit_quota, sumit_request_budget
from cfo.services.ai_chat_tools import TOOLS
from cfo.services.sumit_quota import SumitQuotaExhausted, SumitQuotaUnknown
from cfo.services.sumit_request_budget import SumitRequestLimiter


REALISTIC_KEY = "9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23"
VERIFY_ENDPOINT = "/website/companies/getdetails/"


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
        "Data": {"Company": {"CorporateNumber": corporate_number, "Name": "בדיקות"}},
    })


@pytest.fixture(autouse=True)
def _clear_environment_cache():
    sumit_integration._SUMIT_ENVIRONMENT_CACHE.clear()
    yield
    sumit_integration._SUMIT_ENVIRONMENT_CACHE.clear()


@pytest.fixture
def cleared_request_budgets(client):
    db = SessionLocal()
    try:
        db.query(ProviderRequestBudget).delete()
        db.commit()
        yield
    finally:
        db.query(ProviderRequestBudget).delete()
        db.commit()
        db.close()


# ---------- 4.6 — שער עלות אחיד ----------

def test_paid_action_endpoints_cover_every_billed_operation():
    # הא-סימטריה ההיסטורית: רק getdetails/getpdf היו מוגנים. הסט חייב
    # לכסות כל מה שעולה כסף אצל SUMIT.
    for endpoint in (
        "/accounting/documents/create/",
        "/accounting/documents/send/",
        "/accounting/documents/addexpense/",
        "/sms/sms/send/",
        "/sms/sms/sendmultiple/",
        "/fax/fax/send/",
        "/billing/payments/charge/",
        "/billing/payments/multivendorcharge/",
        "/billing/recurring/charge/",
        "/creditguy/gateway/transaction/",
    ):
        assert endpoint in PAID_ACTION_ENDPOINTS, endpoint


@pytest.mark.asyncio
async def test_paid_endpoint_consumes_monthly_paid_budget_in_test_mode(
    monkeypatch, fresh_org, cleared_request_budgets,
):
    org_id = fresh_org()["org_id"]
    for mod in (sumit_integration, sumit_request_budget, sumit_quota):
        monkeypatch.setattr(mod.settings, "sumit_environment", "test")
        monkeypatch.setattr(mod.settings, "sumit_global_requests_per_minute", 10)
        monkeypatch.setattr(mod.settings, "sumit_org_daily_request_limit", 20)
        monkeypatch.setattr(mod.settings, "sumit_test_monthly_request_limit", 200)
        monkeypatch.setattr(mod.settings, "sumit_test_monthly_paid_action_limit", 1)

    client_obj = SumitIntegration(
        api_key=REALISTIC_KEY, company_id="1",
        request_limiter=SumitRequestLimiter(org_id),
    )
    # W2.5 (20/08): גם ב-test נדרשת מדידת מכסה טרייה — מזריקים אחת עם
    # יתרה, כך שהחסימה שנבדקת כאן היא של המונה החודשי (limit=1) בלבד.
    from datetime import datetime, timezone
    client_obj.quota_snapshot = sumit_quota.QuotaSnapshot(
        organization_id=org_id, used=0, limit=50,
        measured_at=datetime.now(timezone.utc),
    )

    async def fake_request(*, url, **_kwargs):
        if url == VERIFY_ENDPOINT:
            return _company_response("999999998")
        return _Response({"Status": 0, "Data": {"DocumentID": 1}})

    monkeypatch.setattr(client_obj.client, "request", fake_request)

    await client_obj._make_request("/accounting/documents/create/", data={})
    with pytest.raises(SumitQuotaExhausted):
        await client_obj._make_request("/accounting/documents/create/", data={})
    await client_obj.client.aclose()


@pytest.mark.asyncio
async def test_read_endpoint_does_not_touch_the_paid_budget(
    monkeypatch, fresh_org, cleared_request_budgets,
):
    org_id = fresh_org()["org_id"]
    for mod in (sumit_integration, sumit_request_budget, sumit_quota):
        monkeypatch.setattr(mod.settings, "sumit_environment", "test")
        monkeypatch.setattr(mod.settings, "sumit_global_requests_per_minute", 10)
        monkeypatch.setattr(mod.settings, "sumit_org_daily_request_limit", 20)
        monkeypatch.setattr(mod.settings, "sumit_test_monthly_request_limit", 200)
        monkeypatch.setattr(mod.settings, "sumit_test_monthly_paid_action_limit", 1)

    client_obj = SumitIntegration(
        api_key=REALISTIC_KEY, company_id="1",
        request_limiter=SumitRequestLimiter(org_id),
    )

    async def fake_request(*, url, **_kwargs):
        if url == VERIFY_ENDPOINT:
            return _company_response("999999998")
        return _Response({"Status": 0, "Data": {"Documents": []}})

    monkeypatch.setattr(client_obj.client, "request", fake_request)

    # שתי קריאות-קריאה: אף אחת לא צורכת את משבצת התשלום היחידה.
    await client_obj._make_request("/accounting/documents/list/", data={})
    await client_obj._make_request("/accounting/documents/list/", data={})

    db = SessionLocal()
    try:
        paid = db.query(ProviderRequestBudget).filter_by(
            provider="sumit", scope_key=f"paid:org:{org_id}",
        ).first()
        assert paid is None
    finally:
        db.close()
    await client_obj.client.aclose()


@pytest.mark.asyncio
async def test_live_mode_blocks_paid_endpoint_without_measured_quota(
    monkeypatch, fresh_org, cleared_request_budgets,
):
    org_id = fresh_org()["org_id"]
    for mod in (sumit_integration, sumit_request_budget, sumit_quota):
        monkeypatch.setattr(mod.settings, "sumit_environment", "live")
        monkeypatch.setattr(mod.settings, "sumit_global_requests_per_minute", 10)
        monkeypatch.setattr(mod.settings, "sumit_org_daily_request_limit", 20)

    client_obj = SumitIntegration(
        api_key=REALISTIC_KEY, company_id="1",
        request_limiter=SumitRequestLimiter(org_id),
    )

    async def fake_request(*, url, **_kwargs):
        if url == VERIFY_ENDPOINT:
            return _company_response("515151515")
        raise AssertionError("paid request must be refused before the network")

    monkeypatch.setattr(client_obj.client, "request", fake_request)

    with pytest.raises(SumitQuotaUnknown):
        await client_obj._make_request("/accounting/documents/create/", data={})
    await client_obj.client.aclose()


# ---------- 4.1 — כלי התקציב של מושקו ----------

@pytest.mark.asyncio
async def test_budget_status_tool_reads_counters_without_any_api_call(
    monkeypatch, fresh_org, cleared_request_budgets,
):
    org_id = fresh_org()["org_id"]
    for mod in (sumit_request_budget,):
        monkeypatch.setattr(mod.settings, "sumit_environment", "test")
        monkeypatch.setattr(mod.settings, "sumit_global_requests_per_minute", 10)
        monkeypatch.setattr(mod.settings, "sumit_org_daily_request_limit", 20)
        monkeypatch.setattr(mod.settings, "sumit_test_monthly_request_limit", 200)

    limiter = SumitRequestLimiter(org_id)
    limiter.claim("/a")
    limiter.claim("/b")
    limiter.claim("/c")

    from cfo.services.ai_chat_tools import _get_sumit_budget_status

    db = SessionLocal()
    try:
        out = await _get_sumit_budget_status(db, org_id)
    finally:
        db.close()

    assert out["environment"] in ("test", "live")
    assert out["month"]["used"] == 3
    assert out["month"]["remaining"] == out["month"]["limit"] - 3
    assert out["day"]["used"] == 3
    assert out["paid_month"]["used"] == 0
    assert out["source"] == "local_db"


def test_budget_status_tool_is_registered_as_a_read_tool():
    tool = TOOLS["get_sumit_budget_status"]
    assert tool.category == "read"
    assert tool.policy_action is None


# ---------- 4.3 — הכנת דוח מע"מ לשידור ידני ----------

@pytest.mark.asyncio
async def test_prepare_vat_filing_returns_verification_and_manual_instructions(
    fresh_org,
):
    org_id = fresh_org()["org_id"]
    from cfo.services.ai_chat_tools import _prepare_vat_filing

    db = SessionLocal()
    try:
        out = await _prepare_vat_filing(db, org_id, year=2026, month=7)
    finally:
        db.close()

    assert "verification" in out and "checks" in out["verification"]
    assert "report" in out
    assert out["transmission"] == "manual_only"
    assert "רצף" in out["notice"] and "משדרת" in out["notice"]
    assert isinstance(out["ready_to_transmit"], bool)


def test_prepare_vat_filing_is_registered_as_a_read_tool():
    tool = TOOLS["prepare_vat_filing"]
    assert tool.category == "read"
    assert tool.policy_action is None
