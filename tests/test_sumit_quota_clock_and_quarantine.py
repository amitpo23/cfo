"""P0-A תיקונים 2+3 (סקירת קודקס 23/08/2026) — פער-שעון והסגר inferred.

**תיקון 2 — פער-שעון.** `SumitRequestLimiter.claim`/`_claim_monthly_paid_action`
גזרו את חלונות היום/חודש משעון-התהליך (`datetime.now(timezone.utc)`).
שני instances של Vercel עם שעונים לא-מסונכרנים (לדוגמה סביב תפנית חודש)
היו יכולים לתבוע `window_start` שונה לאותו רגע אמיתי — כל אחד מקבל
תקציב חודשי נפרד משלו, כלומר המכסה בפועל מוכפלת. התיקון: `_db_now`
שואב זמן קנוני מה-DB (משותף לכל ה-instances), לא משעון-התהליך.

**תיקון 3 — הסגר inferred.** endpoints מהדרגה 'inferred' ב-FREE_ENDPOINTS
אינם מאומתים ישירות — עד כה ההגנה היחידה הייתה התרעת 80%. זה חושף
חלון-זמן ממשי: התפרצות שימוש ב-01:30, מדידה הבאה רק ב-03:30, והתרעה
רק כשעוברים 80% מהמכסה — כסף כבר יצא לפני שמישהו ידע. כאן: כל רענון
מכסה מתאם את ה-delta האמיתי מול מה שהמערכת עצמה תבעה; פער בלתי-מוסבר
מעל סף (config) מסגיר מיידית את כל שכבת ה-inferred (paid-gated), עד
שחרור ידני — לא רק התרעה.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from cfo.config import settings
from cfo.database import SessionLocal
from cfo.integrations.sumit_integration import (
    INFERRED_FREE_ENDPOINTS,
    VERIFIED_FREE_ENDPOINTS,
    SumitIntegration,
)
from cfo.models import CfoInsight, ProviderRequestBudget, SumitQuotaMeasurement
from cfo.services import sumit_quota
from cfo.services import sumit_request_budget as budget_mod
from cfo.services.sumit_request_budget import SumitRequestLimiter


REALISTIC_KEY = "9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23"


@pytest.fixture(autouse=True)
def _clean(client):
    db = SessionLocal()
    try:
        db.query(SumitQuotaMeasurement).delete()
        db.query(ProviderRequestBudget).delete()
        db.query(CfoInsight).delete()
        db.commit()
        yield
    finally:
        db.query(SumitQuotaMeasurement).delete()
        db.query(ProviderRequestBudget).delete()
        db.query(CfoInsight).delete()
        db.commit()
        db.close()


def _integration(org_id: int) -> SumitIntegration:
    return SumitIntegration(
        api_key=REALISTIC_KEY, company_id="1",
        request_limiter=SumitRequestLimiter(org_id),
    )


class _FakeQuotaIntegration:
    def __init__(self, *, used: int, limit: int = 50):
        self.used = used
        self.limit = limit

    async def _make_request(self, endpoint, data=None, **_kwargs):
        return {
            "Data": [
                {"ApplicationName": "ActionsBilling", "StatisticName": "Operations",
                 "Usage": self.used, "Quota": self.limit},
            ],
        }


# ==================================================================== #
# תיקון 2 — זמן קנוני מה-DB, לא משעון-התהליך
# ==================================================================== #

def test_two_instances_with_skewed_clocks_share_the_same_canonical_window(
    monkeypatch, fresh_org,
):
    """לפני התיקון: instance עם שעון שגוי בחודש שלם היה תובע window_start
    שונה (חודש אחר) מ-instance עם שעון תקין — כל אחד מקבל תקציב חודשי
    נפרד משלו (המכסה האפקטיבית מוכפלת). אחרי: שניהם נגזרים מזמן ה-DB
    הקנוני (SQLite CURRENT_TIMESTAMP בטסטים — לא מושפע ממוקפצ'-ה-Python
    datetime.now) — אותו window_start בדיוק, אותה שורת-מכסה."""
    org_id = fresh_org()["org_id"]
    real_now = datetime.now(timezone.utc)

    class _SkewedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return real_now + timedelta(days=40)

    limiter_a = SumitRequestLimiter(org_id)
    limiter_a.claim("endpoint-a")  # "instance" עם שעון תקין

    monkeypatch.setattr(budget_mod, "datetime", _SkewedDatetime)
    limiter_b = SumitRequestLimiter(org_id)
    limiter_b.claim("endpoint-b")  # "instance" עם שעון שקוע 40 יום קדימה

    db = SessionLocal()
    try:
        rows = (
            db.query(ProviderRequestBudget)
            .filter(
                ProviderRequestBudget.scope_key == f"org:{org_id}",
                ProviderRequestBudget.window_kind == "month",
            )
            .all()
        )
        assert len(rows) == 1, [r.window_start for r in rows]
        assert rows[0].used == 2
    finally:
        db.close()


def test_the_daily_sync_run_gate_also_uses_canonical_time(monkeypatch, fresh_org):
    """אותו תיקון על `claim_daily_sync_run` — לא רק `SumitRequestLimiter.claim`."""
    org_id = fresh_org()["org_id"]
    real_now = datetime.now(timezone.utc)

    class _SkewedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return real_now + timedelta(days=40)

    budget_mod.claim_daily_sync_run("real-clock-key-aaaaaaaaaaaaaaaa", organization_id=org_id)

    monkeypatch.setattr(budget_mod, "datetime", _SkewedDatetime)
    with pytest.raises(budget_mod.SumitRequestBudgetExceeded):
        # אותו מפתח — אם ה-window היה נגזר משעון-התהליך המקפיץ, זה היה
        # window_start אחר (חודש אחר) והתביעה השנייה הייתה עוברת בטעות.
        budget_mod.claim_daily_sync_run("real-clock-key-aaaaaaaaaaaaaaaa", organization_id=org_id)


# ==================================================================== #
# תיקון 3 — הסגר inferred
# ==================================================================== #

def test_unexplained_usage_delta_triggers_immediate_quarantine(fresh_org):
    """התפרצות ב-01:30 → מדידה ב-03:30: המערכת לא תבעה כלום (0 קריאות
    paid-gated), אבל ה-Usage אצל הספק עלה ב-3 — פער בלתי-מוסבר מעל
    הסף (2 כברירת מחדל) מסגיר מיידית, לא מחכה ל-80%."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        asyncio.run(sumit_quota.refresh_quota_measurement(
            db, org_id, _FakeQuotaIntegration(used=10, limit=50),
        ))
    finally:
        db.close()

    # שום קריאה paid-gated לא נעשתה בינתיים — הכל אמור להיות "בלתי-מוסבר".
    db = SessionLocal()
    try:
        asyncio.run(sumit_quota.refresh_quota_measurement(
            db, org_id, _FakeQuotaIntegration(used=13, limit=50),
        ))
    finally:
        db.close()

    db = SessionLocal()
    try:
        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "sumit_inferred_endpoint_quarantine",
        ).first()
        assert insight is not None
        assert insight.status == "active"
        assert insight.severity == "critical"
        assert insight.evidence["unexplained_delta"] == 3
    finally:
        db.close()

    assert sumit_quota.is_inferred_endpoint_quarantined(
        SessionLocal(), organization_id=org_id, environment=settings.sumit_environment,
    ) is True


def test_a_small_explained_delta_does_not_trigger_quarantine(fresh_org):
    """delta קטן מהסף (או מוסבר ע"י תביעות שלנו) לא מסגיר — false
    positive עולה חיכוך תפעולי, לא רק כסף."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        asyncio.run(sumit_quota.refresh_quota_measurement(
            db, org_id, _FakeQuotaIntegration(used=10, limit=50),
        ))
    finally:
        db.close()
    db = SessionLocal()
    try:
        # delta=1, מתחת לסף (2) — לא מסגיר.
        asyncio.run(sumit_quota.refresh_quota_measurement(
            db, org_id, _FakeQuotaIntegration(used=11, limit=50),
        ))
    finally:
        db.close()

    db = SessionLocal()
    try:
        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "sumit_inferred_endpoint_quarantine",
        ).first()
        assert insight is None
    finally:
        db.close()


def test_quarantined_inferred_endpoint_blocks_without_a_snapshot(fresh_org):
    """אחרי הסגר: endpoint 'inferred' (למשל list מסמכים) עובר לשער-התשלום
    הרגיל — בלי מדידה טרייה מוזרקת, הוא נחסם fail-closed בדיוק כמו
    endpoint paid רגיל."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        sumit_quota._trigger_inferred_endpoint_quarantine(
            db, organization_id=org_id, environment=settings.sumit_environment,
            unexplained_delta=5, evidence={"note": "manual test seed"},
        )
        db.commit()
    finally:
        db.close()

    integration = _integration(org_id)
    inferred_endpoint = next(iter(INFERRED_FREE_ENDPOINTS))
    assert integration._inferred_tier_is_quarantined() is True
    with pytest.raises(sumit_quota.SumitQuotaError):
        integration._enforce_paid_action_budget(inferred_endpoint)


def test_verified_free_endpoints_are_never_quarantined(monkeypatch, fresh_org):
    """listquotas/getdetails (bootstrap) פטורים מהסגר בכל מצב — אחרת
    המערכת לא יכולה אפילו לרענן מכסה כדי לצאת מהמצב."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        sumit_quota._trigger_inferred_endpoint_quarantine(
            db, organization_id=org_id, environment=settings.sumit_environment,
            unexplained_delta=5, evidence={"note": "manual test seed"},
        )
        db.commit()
    finally:
        db.close()

    from cfo.integrations import sumit_integration as mod

    mod._SUMIT_ENVIRONMENT_CACHE.clear()
    integration = _integration(org_id)

    class _Response:
        status_code = 200
        text = "{}"

        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    async def fake_request(*, url, **_kwargs):
        if url == "/website/companies/getdetails/":
            return _Response({
                "Status": 0,
                "Data": {"Company": {"CorporateNumber": "999999998"}},
            })
        return _Response({"Status": 0, "Data": []})

    monkeypatch.setattr(integration.client, "request", fake_request)

    # אין quota_snapshot בכלל — endpoint לא-חינמי היה נחסם כאן.
    result = asyncio.run(integration._make_request("/website/companies/listquotas/"))
    assert result["Status"] == 0
    asyncio.run(integration.client.aclose())
    mod._SUMIT_ENVIRONMENT_CACHE.clear()


def test_quarantine_clears_only_via_manual_status_update(fresh_org):
    """'שחרור ידני בלבד' — עדכון status ל-'resolved' (המסלול הקיים,
    PATCH /brain/insights/{id} או /insights/{id}/status) הוא הדרך
    היחידה לשחרר; שום רענון מכסה 'שקט' לא משחרר לבד."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        sumit_quota._trigger_inferred_endpoint_quarantine(
            db, organization_id=org_id, environment=settings.sumit_environment,
            unexplained_delta=5, evidence={},
        )
        db.commit()
    finally:
        db.close()

    assert sumit_quota.is_inferred_endpoint_quarantined(
        SessionLocal(), organization_id=org_id, environment=settings.sumit_environment,
    ) is True

    db = SessionLocal()
    try:
        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "sumit_inferred_endpoint_quarantine",
        ).one()
        insight.status = "resolved"
        db.commit()
    finally:
        db.close()

    assert sumit_quota.is_inferred_endpoint_quarantined(
        SessionLocal(), organization_id=org_id, environment=settings.sumit_environment,
    ) is False


def test_a_new_unexplained_delta_reopens_a_resolved_quarantine(fresh_org):
    """הכרעת עיצוב (מתועדת בדוח): שחרור ידני עוצר את ההסגר הקיים, אבל
    לא 'מחסן' לצמיתות מול אירוע **חדש** — פער בלתי-מוסבר עתידי פותח
    הסגר מחדש. הקריאה ההפוכה (fail-open לצמיתות אחרי כל שחרור) הייתה
    מסוכנת יותר לכסף."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        sumit_quota._trigger_inferred_endpoint_quarantine(
            db, organization_id=org_id, environment=settings.sumit_environment,
            unexplained_delta=5, evidence={},
        )
        db.commit()
        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "sumit_inferred_endpoint_quarantine",
        ).one()
        insight.status = "resolved"
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        sumit_quota._trigger_inferred_endpoint_quarantine(
            db, organization_id=org_id, environment=settings.sumit_environment,
            unexplained_delta=7, evidence={},
        )
        db.commit()
    finally:
        db.close()

    assert sumit_quota.is_inferred_endpoint_quarantined(
        SessionLocal(), organization_id=org_id, environment=settings.sumit_environment,
    ) is True
