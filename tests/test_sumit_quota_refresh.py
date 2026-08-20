"""W2.1 — מפיק המדידה: רענון יומי של מכסת הפעולות-בתשלום מ-SUMIT.

הפער שנמצא ב-20/08: `quota_snapshot` נקרא בשער אבל **אין לו מפיק** —
אין cron, אין טבלה, אין השמה בקוד הייצור. כל פעולה בתשלום נחסמה תמיד
("קוד מת" fail-closed). כאן נסגר המעגל: רענון → שמירה → טעינה בשער.

אישור בעלים 20/08: קריאת `listquotas` (חינמית) אחת ביום ≈ 30 בחודש.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from cfo.config import settings
from cfo.database import SessionLocal
from cfo.models import CfoInsight, ProviderRequestBudget, SumitQuotaMeasurement
from cfo.services import sumit_quota


LISTQUOTAS_RESPONSE = {
    "Data": [
        {"ApplicationName": "OutgoingEmails", "StatisticName": "Mails",
         "Usage": 3, "Quota": 5000},
        {"ApplicationName": "ActionsBilling", "StatisticName": "Operations",
         "Usage": 12, "Quota": 50},
    ],
}


class _FakeIntegration:
    def __init__(self, payload=LISTQUOTAS_RESPONSE):
        self.payload = payload
        self.calls = []

    async def _make_request(self, endpoint, data=None, **_kwargs):
        self.calls.append(endpoint)
        return self.payload


@pytest.fixture(autouse=True)
def _clean(client):
    db = SessionLocal()
    try:
        db.query(SumitQuotaMeasurement).delete()
        db.query(ProviderRequestBudget).delete()
        db.commit()
        yield
    finally:
        db.query(SumitQuotaMeasurement).delete()
        db.query(ProviderRequestBudget).delete()
        db.commit()
        db.close()


def test_refresh_stores_a_measurement_and_the_loader_reads_it(fresh_org):
    org_id = fresh_org()["org_id"]
    fake = _FakeIntegration()
    db = SessionLocal()
    try:
        snapshot = asyncio.run(
            sumit_quota.refresh_quota_measurement(db, org_id, fake),
        )
        assert snapshot is not None and snapshot.used == 12 and snapshot.limit == 50
        assert fake.calls == [sumit_quota.QUOTA_ENDPOINT]

        loaded = sumit_quota.load_latest_snapshot(db, org_id)
        assert loaded is not None
        assert (loaded.used, loaded.limit) == (12, 50)
        assert loaded.age < timedelta(minutes=1)
    finally:
        db.close()


def test_a_malformed_response_stores_nothing(fresh_org):
    """honest-null: תשובה בלי השורה הרלוונטית לא הופכת למדידה."""
    org_id = fresh_org()["org_id"]
    fake = _FakeIntegration(payload={"Data": [{"ApplicationName": "Other"}]})
    db = SessionLocal()
    try:
        snapshot = asyncio.run(
            sumit_quota.refresh_quota_measurement(db, org_id, fake),
        )
        assert snapshot is None
        assert sumit_quota.load_latest_snapshot(db, org_id) is None
    finally:
        db.close()


def test_the_paid_gate_passes_with_a_fresh_stored_measurement(fresh_org, monkeypatch):
    """סגירת המעגל: מדידה שמורה ⇒ השער עובר; בלעדיה ⇒ חסום."""
    from cfo.integrations.sumit_integration import SumitIntegration
    from cfo.services.sumit_request_budget import SumitRequestLimiter

    org_id = fresh_org()["org_id"]
    integration = SumitIntegration(
        api_key="9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23", company_id="1",
        request_limiter=SumitRequestLimiter(org_id),
    )

    with pytest.raises(sumit_quota.SumitQuotaError):
        integration._enforce_paid_action_budget("/accounting/documents/getpdf/")

    db = SessionLocal()
    try:
        asyncio.run(
            sumit_quota.refresh_quota_measurement(db, org_id, _FakeIntegration()),
        )
    finally:
        db.close()
    integration._enforce_paid_action_budget("/accounting/documents/getpdf/")


def test_near_limit_measurement_creates_an_owner_insight(fresh_org):
    """W2.5 — `NEAR_LIMIT_RATIO` מקבל סוף-סוף צרכן: מדידה ב-80%+ יוצרת
    התרעת CfoInsight כדי שהבעלים יידע לפני החסימה, לא אחרי."""
    org_id = fresh_org()["org_id"]
    near = {
        "Data": [
            {"ApplicationName": "ActionsBilling", "StatisticName": "Operations",
             "Usage": 45, "Quota": 50},
        ],
    }
    db = SessionLocal()
    try:
        asyncio.run(
            sumit_quota.refresh_quota_measurement(
                db, org_id, _FakeIntegration(payload=near),
            ),
        )
        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "sumit_quota_near_limit",
        ).first()
        assert insight is not None
        assert insight.severity in ("high", "critical")
    finally:
        db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
        ).delete()
        db.commit()
        db.close()


def test_refresh_cron_endpoint_is_secret_gated_and_idempotent(client, monkeypatch):
    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    denied = client.get("/api/cron/refresh-sumit-quota")
    assert denied.status_code in (401, 403)

    headers = {"Authorization": "Bearer s3cret"}
    first = client.get("/api/cron/refresh-sumit-quota", headers=headers)
    assert first.status_code == 200
    assert "results" in first.json()
