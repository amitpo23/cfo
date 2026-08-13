"""Hard, database-backed SUMIT request ceilings at the network boundary."""
import asyncio

import pytest

from cfo.database import SessionLocal
from cfo.models import ProviderRequestBudget
from cfo.integrations.sumit_integration import (
    SumitIntegration,
    SumitRequestBudgetRequired,
)
from cfo.services.sumit_request_budget import (
    SumitRequestBudgetExceeded,
    SumitRequestLimiter,
)


@pytest.fixture(autouse=True)
def _clear_request_budgets():
    db = SessionLocal()
    try:
        db.query(ProviderRequestBudget).delete()
        db.commit()
        yield
    finally:
        db.query(ProviderRequestBudget).delete()
        db.commit()
        db.close()


def test_separate_limiter_instances_share_one_atomic_daily_counter(fresh_org):
    org_id = fresh_org()["org_id"]
    first = SumitRequestLimiter(org_id, per_minute_limit=10, daily_limit=2)
    second = SumitRequestLimiter(org_id, per_minute_limit=10, daily_limit=2)

    first.claim("/one")
    second.claim("/two")
    with pytest.raises(SumitRequestBudgetExceeded, match="daily"):
        first.claim("/three")


def test_global_minute_ceiling_is_shared_across_organizations(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    SumitRequestLimiter(org_a, per_minute_limit=2, daily_limit=20).claim("/one")
    SumitRequestLimiter(org_b, per_minute_limit=2, daily_limit=20).claim("/two")

    with pytest.raises(SumitRequestBudgetExceeded, match="minute"):
        SumitRequestLimiter(org_a, per_minute_limit=2, daily_limit=20).claim("/three")


def test_low_level_client_refuses_real_request_without_limiter(monkeypatch):
    client = SumitIntegration(
        api_key="9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23",
        company_id="1",
    )
    reached = {"network": 0}

    async def forbidden(*_args, **_kwargs):
        reached["network"] += 1
        raise AssertionError("network was reached")

    monkeypatch.setattr(client.client, "request", forbidden)
    with pytest.raises(SumitRequestBudgetRequired):
        asyncio.run(client._make_request("/accounting/documents/list/"))
    assert reached["network"] == 0
    asyncio.run(client.client.aclose())


def test_low_level_client_claims_before_network(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    events = []

    class Limiter:
        def claim(self, endpoint):
            events.append(("claim", endpoint))

    class Response:
        status_code = 200
        text = "{}"

        def raise_for_status(self):
            return None

        def json(self):
            return {"Status": 0, "Data": {}}

    client = SumitIntegration(
        api_key="9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23",
        company_id="1",
        request_limiter=Limiter(),
    )

    async def fake_request(*_args, **_kwargs):
        events.append(("network", None))
        return Response()

    monkeypatch.setattr(client.client, "request", fake_request)
    asyncio.run(client._make_request("/accounting/documents/list/"))
    assert events == [
        ("claim", "/accounting/documents/list/"),
        ("network", None),
    ]
    asyncio.run(client.client.aclose())
