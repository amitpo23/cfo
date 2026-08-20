"""W2.5 — השלמת שער הפעולות-בתשלום.

הפערים שנמצאו בחקירת 20/08:
- `getdetails`/`getpdf` — הפעולות שגרמו לחיוב האמיתי ב-17/07 — לא היו
  ב-`PAID_ACTION_ENDPOINTS`; הוגנו רק ברמת המתודה, ו-`_post_binary` לא
  בדק את הרשימה בכלל.
- המונה החודשי לפעולות-בתשלום נתבע רק ב-test — ב-live ההגנה היחידה היא
  המדידה מהספק, בלי מונה עמיד משלנו.
"""
import asyncio
from datetime import datetime, timezone

import pytest

from cfo.config import settings
from cfo.database import SessionLocal
from cfo.models import ProviderRequestBudget
from cfo.integrations.sumit_integration import (
    PAID_ACTION_ENDPOINTS,
    SumitIntegration,
)
from cfo.services import sumit_quota


@pytest.fixture(autouse=True)
def _clear_request_budgets(client):
    db = SessionLocal()
    try:
        db.query(ProviderRequestBudget).delete()
        db.commit()
        yield
    finally:
        db.query(ProviderRequestBudget).delete()
        db.commit()
        db.close()


def test_getdetails_and_getpdf_are_paid_endpoints():
    """הפעולות שחייבו בפועל ב-17/07 חייבות להיות בשער האחיד."""
    assert "/accounting/documents/getdetails/" in PAID_ACTION_ENDPOINTS
    assert "/accounting/documents/getpdf/" in PAID_ACTION_ENDPOINTS


def test_post_binary_enforces_the_paid_endpoint_gate(monkeypatch):
    """`_post_binary` הוא המסלול היחיד ל-getpdf — הוא חייב לעבור את שער
    הפעולות-בתשלום לפני שהרשת נגישה."""

    class _Limiter:
        organization_id = 1

        def claim(self, endpoint):
            pass

    client = SumitIntegration(
        api_key="9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23",
        company_id="1",
        request_limiter=_Limiter(),
    )

    class _Gate(RuntimeError):
        pass

    def gate(endpoint):
        raise _Gate(endpoint)

    async def verified():
        return None

    reached = {"network": 0}

    async def forbidden(*_args, **_kwargs):
        reached["network"] += 1
        raise AssertionError("network was reached")

    monkeypatch.setattr(client, "_enforce_paid_action_budget", gate)
    monkeypatch.setattr(client, "_ensure_environment_verified", verified)
    monkeypatch.setattr(client.client, "request", forbidden)
    monkeypatch.setattr(client.client, "post", forbidden)

    with pytest.raises(_Gate):
        asyncio.run(client._post_binary("/accounting/documents/getpdf/", {}))
    assert reached["network"] == 0
    asyncio.run(client.client.aclose())


def test_live_paid_action_claims_a_durable_monthly_counter(monkeypatch, fresh_org):
    """גם ב-live יש מונה חודשי עמיד משלנו — הגנה שנייה לצד המדידה מהספק."""
    org_id = fresh_org()["org_id"]
    monkeypatch.setattr(settings, "sumit_environment", "live")
    monkeypatch.setattr(settings, "sumit_live_monthly_paid_action_limit", 1)

    snapshot = sumit_quota.QuotaSnapshot(
        organization_id=org_id, used=0, limit=50,
        measured_at=datetime.now(timezone.utc),
    )
    sumit_quota.assert_paid_action_within_quota(snapshot, endpoint="/x/")
    with pytest.raises(sumit_quota.SumitQuotaExhausted, match="monthly"):
        sumit_quota.assert_paid_action_within_quota(snapshot, endpoint="/x/")
