"""P0-A (23/08/2026) — איחוד ledger המכסה: סגירת שני הממצאים של ביקורת קודקס.

**ממצא 1 (זה הקובץ).** `assert_paid_action_within_quota` בדק את מדידת
הספק (`used/limit`) ואז תבע משבצת מ-מונה חודשי **נפרד** — שלא אותחל
מ-`snapshot.used` ולא נחסם ע"י `snapshot.remaining`. תוצאה: מדידה של
49/50 מהספק (remaining=1) עדיין נתנה לגייט לאשר עד לתקרה הפנימית (90),
כי המונה הפנימי מתחיל אפס בלי קשר למדידה. כאן מוכח שהחור נסגר: מדידה
כמעט-מוצתה חוסמת אחרי פעולה אחת בלבד, בלי קשר לכמה נותר במונה הפנימי.

הבדיקות טוענות מדידה ל-DB ואז קוראות ל-`_enforce_paid_action_budget`
בשתי קריאות **נפרדות** (לא אותו אובייקט Python מוזרק) — כל קריאה טוענת
את המדידה מחדש מה-DB דרך `_current_quota_snapshot`, בדיוק כפי שקורה
בייצור.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from cfo.config import settings
from cfo.database import SessionLocal
from cfo.integrations.sumit_integration import SumitIntegration
from cfo.models import ProviderRequestBudget, SumitQuotaMeasurement
from cfo.services import sumit_quota
from cfo.services.sumit_request_budget import SumitRequestLimiter


REALISTIC_KEY = "9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23"


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


def _store(org_id: int, *, used: int, limit: int,
           measured_at: datetime | None = None) -> None:
    db = SessionLocal()
    try:
        sumit_quota.store_measurement(db, sumit_quota.QuotaSnapshot(
            organization_id=org_id, used=used, limit=limit,
            measured_at=measured_at or datetime.now(timezone.utc),
        ))
        db.commit()
    finally:
        db.close()


def _integration(org_id: int) -> SumitIntegration:
    return SumitIntegration(
        api_key=REALISTIC_KEY, company_id="1",
        request_limiter=SumitRequestLimiter(org_id),
    )


def test_near_exhausted_provider_snapshot_blocks_after_one_action(fresh_org):
    """הממצא עצמו: 49/50 (remaining=1) חוסם אחרי פעולה אחת — לא אחרי 90."""
    org_id = fresh_org()["org_id"]
    _store(org_id, used=49, limit=50)

    integration = _integration(org_id)
    integration._enforce_paid_action_budget("/accounting/documents/getpdf/")
    with pytest.raises(sumit_quota.SumitQuotaExhausted):
        integration._enforce_paid_action_budget("/accounting/documents/getpdf/")


def test_a_fully_exhausted_snapshot_blocks_the_very_first_action(fresh_org):
    """נשען על הבדיקה הישנה יותר (remaining<=0 → SumitQuotaExhausted מוקדם),
    אך כאן מוודאים שהיא עדיין נכונה גם אחרי השינוי למונה המאוחד."""
    org_id = fresh_org()["org_id"]
    _store(org_id, used=50, limit=50)

    integration = _integration(org_id)
    with pytest.raises(sumit_quota.SumitQuotaExhausted):
        integration._enforce_paid_action_budget("/accounting/documents/getpdf/")


def test_generous_provider_snapshot_still_bounded_by_internal_monthly_cap(
    fresh_org, monkeypatch,
):
    """כיוון הפוך: מדידה נדיבה מהספק (1000 remaining) לא מבטלת את התקרה
    הפנימית העמידה — 'לעולם לא מגדילה מעבר לתקרה הפנימית'.

    הקצב היומי (`paced_daily_limit`) מנוטרל כאן במכוון: המטרה של הבדיקה
    הזו היא בידוד הגבול החודשי בלבד, לא האינטראקציה בין קצב-יומי לחודשי
    (זו נבדקת בנפרד עבור מגבלת הבקשות הכללית ב-test_sumit_hard_request_budget.py)."""
    monkeypatch.setattr(settings, "sumit_test_monthly_paid_action_limit", 2)
    monkeypatch.setattr(
        sumit_quota, "paced_daily_limit",
        lambda **kwargs: kwargs["monthly_limit"],
    )
    org_id = fresh_org()["org_id"]
    _store(org_id, used=0, limit=1000)

    integration = _integration(org_id)
    integration._enforce_paid_action_budget("/x/")
    integration._enforce_paid_action_budget("/x/")
    with pytest.raises(sumit_quota.SumitQuotaExhausted, match="monthly"):
        integration._enforce_paid_action_budget("/x/")


def test_a_fresh_measurement_opens_a_new_since_snapshot_window(fresh_org):
    """מדידה חדשה (measured_at אחר) פותחת חלון טרי — מכסה שנחסמה על
    מדידה ישנה לא נשארת חסומה לצמיתות ברגע שיש מדידה עדכנית יותר.

    **הערה (סקירת קודקס 23/08, תיקון 1):** הבדיקה הזו כותבת ל-DB דרך
    `store_measurement` ישירות (לא `refresh_quota_measurement`), ולכן
    **אינה** עוברת את `_reconcile_generation` (carry-forward) — היא
    מוכיחה רק שמפתח-החלון משתנה עם `measured_at`, לא את סגירת מרוץ-
    הדורות. את המרוץ עצמו, דרך הזרימה האמיתית (`refresh_quota_measurement`),
    מוכיחות הבדיקות תחת 'מרוץ-דורות' למטה."""
    org_id = fresh_org()["org_id"]
    old_measured_at = datetime.now(timezone.utc) - timedelta(hours=2)
    _store(org_id, used=49, limit=50, measured_at=old_measured_at)

    integration = _integration(org_id)
    integration._enforce_paid_action_budget("/x/")
    with pytest.raises(sumit_quota.SumitQuotaExhausted):
        integration._enforce_paid_action_budget("/x/")

    # רענון: מדידה חדשה יותר, remaining גדול יותר.
    _store(org_id, used=5, limit=50)
    integration._enforce_paid_action_budget("/x/")


def test_claim_failure_rolls_back_the_snapshot_window_atomically(fresh_org, monkeypatch):
    """אם התביעה החודשית נכשלת, גם משבצת ה-since_snapshot לא נשארת
    תפוסה — הכול-או-כלום, כמו ב-SumitRequestLimiter.claim."""
    monkeypatch.setattr(settings, "sumit_test_monthly_paid_action_limit", 1)
    org_id = fresh_org()["org_id"]
    _store(org_id, used=0, limit=50)

    integration = _integration(org_id)
    integration._enforce_paid_action_budget("/x/")
    with pytest.raises(sumit_quota.SumitQuotaExhausted, match="monthly"):
        integration._enforce_paid_action_budget("/x/")

    db = SessionLocal()
    try:
        row = (
            db.query(ProviderRequestBudget)
            .filter(
                ProviderRequestBudget.scope_key == f"paid:org:{org_id}",
                ProviderRequestBudget.window_kind == "snapshot",
            )
            .one()
        )
        # רק התביעה הראשונה (שהצליחה) נספרה — לא השנייה, שנכשלה על "month".
        assert row.used == 1
    finally:
        db.close()


# ==================================================================== #
# תיקון 1 (סקירת קודקס 23/08) — מרוץ-דורות: carry-forward דרך הזרימה
# האמיתית (refresh_quota_measurement, לא store_measurement ישיר)
# ==================================================================== #

class _FakeQuotaIntegration:
    """מדמה SumitIntegration לצורך refresh_quota_measurement בלבד —
    מחזיר תמיד את אותה שורת ActionsBilling/Operations."""

    def __init__(self, *, used: int, limit: int = 50):
        self.used = used
        self.limit = limit
        self.calls: list[str] = []

    async def _make_request(self, endpoint, data=None, **_kwargs):
        self.calls.append(endpoint)
        return {
            "Data": [
                {"ApplicationName": "ActionsBilling", "StatisticName": "Operations",
                 "Usage": self.used, "Quota": self.limit},
            ],
        }


def test_snapshot_generation_race_rejects_claim_loaded_before_refresh(fresh_org):
    """שזירה אמיתית: claim קורא דור ישן ב-session א', refresh ב-session
    ב' מפרסם דור חדש, ורק אז ה-claim הישן מנסה לתבוע. הוא חייב להיחסם
    כ-stale; אחרת הוא נרשם בדור הישן אחרי שה-refresh כבר קרא prior_claimed,
    והדור החדש עדיין מאפשר claim נוסף — שתי פעולות מול remaining=1."""
    org_id = fresh_org()["org_id"]
    claim_reader = SessionLocal()
    refresher = SessionLocal()
    try:
        asyncio.run(sumit_quota.refresh_quota_measurement(
            claim_reader, org_id, _FakeQuotaIntegration(used=49, limit=50),
        ))
        stale_snapshot = sumit_quota.load_latest_snapshot(claim_reader, org_id)
        assert stale_snapshot is not None
        # שלב הקריאה של claim א' הסתיים; משחררים את read transaction כדי
        # ש-session ב' יוכל לפרסם את הדור החדש ב-SQLite של הסוויטה.
        claim_reader.rollback()

        asyncio.run(sumit_quota.refresh_quota_measurement(
            refresher, org_id, _FakeQuotaIntegration(used=49, limit=50),
        ))

        with pytest.raises(sumit_quota.SumitQuotaUnknown, match="newer quota"):
            sumit_quota._claim_monthly_paid_action(
                organization_id=org_id, endpoint="/stale/",
                snapshot=stale_snapshot,
            )
    finally:
        claim_reader.close()
        refresher.close()

    integration = _integration(org_id)
    integration._enforce_paid_action_budget("/current/")
    with pytest.raises(sumit_quota.SumitQuotaExhausted):
        integration._enforce_paid_action_budget("/current/")


def test_confirmed_claims_are_not_carried_forward_once_usage_catches_up(
    fresh_org, monkeypatch,
):
    """כיוון הפוך: כשה-Usage בפועל עולה מספיק כדי להסביר את התביעות
    הישנות (delta==prior_claimed), אין carry — הדור החדש נפתח נקי.

    הקצב היומי מנוטרל כאן במכוון (כמו ב-
    test_generous_provider_snapshot_still_bounded_by_internal_monthly_cap
    למעלה) — המטרה כאן היא בידוד ה-carry-forward, לא האינטראקציה עם
    פיזור-הקצב היומי; זו נבדקת בנפרד ב-test_paced_daily_limit_is_bounded_by_provider_remaining."""
    monkeypatch.setattr(
        sumit_quota, "paced_daily_limit",
        lambda **kwargs: kwargs["monthly_limit"],
    )
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        asyncio.run(sumit_quota.refresh_quota_measurement(
            db, org_id, _FakeQuotaIntegration(used=40, limit=50),
        ))
    finally:
        db.close()

    integration = _integration(org_id)
    integration._enforce_paid_action_budget("/x/")
    integration._enforce_paid_action_budget("/x/")  # 2 תביעות תחת הדור הזה

    db = SessionLocal()
    try:
        # Usage עלה ב-2 בדיוק — מסביר את שתי התביעות. אין carry.
        asyncio.run(sumit_quota.refresh_quota_measurement(
            db, org_id, _FakeQuotaIntegration(used=42, limit=50),
        ))
    finally:
        db.close()

    # הדור החדש: remaining=8 (50-42), בלי carry — לא נחסם.
    integration._enforce_paid_action_budget("/x/")


# ==================================================================== #
# תיקון 2 (סקירת קודקס 23/08) — מדידה עתידית לא עוברת כ"טרייה"
# ==================================================================== #

def test_a_future_dated_measurement_is_rejected_as_unknown():
    """age שלילי (measured_at עתידי, פער-שעון) לא אמור להיחשב 'טרי' —
    בלי הבדיקה המפורשת, `age > MAX_MEASUREMENT_AGE` הוא False תמיד
    כש-age שלילי, בלי קשר לכמה רחוק בעתיד המדידה."""
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    snapshot = sumit_quota.QuotaSnapshot(
        organization_id=1, used=0, limit=50, measured_at=future,
    )
    with pytest.raises(sumit_quota.SumitQuotaUnknown):
        sumit_quota.assert_paid_action_within_quota(
            snapshot, endpoint="/x/", claim_budget=False,
        )


def test_a_measurement_within_the_future_tolerance_still_passes():
    """סבילות קטנה (jitter סביר בין instances) לא אמורה לחסום מדידה
    אמיתית — רק חריגה משמעותית."""
    almost_now = datetime.now(timezone.utc) + timedelta(seconds=30)
    snapshot = sumit_quota.QuotaSnapshot(
        organization_id=1, used=0, limit=50, measured_at=almost_now,
    )
    sumit_quota.assert_paid_action_within_quota(
        snapshot, endpoint="/x/", claim_budget=False,
    )


def test_paid_claim_refuses_process_time_when_db_time_is_unavailable(
    fresh_org, monkeypatch,
):
    """גם `now` תקין שסופק לבדיקה המוקדמת אינו תחליף לזמן DB ב-claim."""
    org_id = fresh_org()["org_id"]
    snapshot = sumit_quota.QuotaSnapshot(
        organization_id=org_id, used=0, limit=50,
        measured_at=datetime.now(timezone.utc),
    )

    def unavailable(_db):
        raise sumit_quota.SumitRequestBudgetUnavailable("db time unavailable")

    monkeypatch.setattr(sumit_quota, "_db_now", unavailable)
    with pytest.raises(sumit_quota.SumitQuotaUnknown):
        sumit_quota.assert_paid_action_within_quota(
            snapshot, endpoint="/x/", now=datetime.now(timezone.utc),
        )


def test_integration_paid_gate_blocks_when_canonical_db_time_fails(
    fresh_org, monkeypatch,
):
    from cfo.services import sumit_request_budget

    org_id = fresh_org()["org_id"]
    _store(org_id, used=0, limit=50)

    def unavailable(_db):
        raise sumit_request_budget.SumitRequestBudgetUnavailable(
            "db time unavailable",
        )

    monkeypatch.setattr(sumit_request_budget, "_db_now", unavailable)
    with pytest.raises(sumit_quota.SumitQuotaUnknown):
        _integration(org_id)._enforce_paid_action_budget("/x/")


# ==================================================================== #
# תיקון 5 (סקירת קודקס 23/08) — קצב יומי נגזר מהיתרה האפקטיבית
# ==================================================================== #

def test_paced_daily_limit_is_bounded_by_provider_remaining():
    from cfo.services.sumit_request_budget import paced_daily_limit

    # תקרה פנימית גדולה (90), אבל הספק משאיר רק 2 — הקצב היומי חייב
    # להיות מוגבל ע"י ה-2, לא ע"י ה-90 הפנימי בלבד (ceil(2/30)=1, לא
    # ceil(90/30)=3).
    assert paced_daily_limit(
        configured_daily=90, monthly_limit=90, month_used=0, day_used=0,
        days_left=30, provider_remaining=2,
    ) == 1
    # בלי provider_remaining — ההתנהגות הקודמת (מבוסס תקרה פנימית בלבד).
    assert paced_daily_limit(
        configured_daily=90, monthly_limit=90, month_used=0, day_used=0,
        days_left=30,
    ) == 3
    # יתרת-ספק שעדיין מאפשרת יותר מיום אחד להתפזר על פניו כרגיל.
    assert paced_daily_limit(
        configured_daily=90, monthly_limit=90, month_used=0, day_used=0,
        days_left=10, provider_remaining=25,
    ) == 3  # ceil(25/10)=3, קטן מ-ceil(90/10)=9


def test_provider_pace_does_not_loosen_after_an_intraday_claim():
    from cfo.services.sumit_request_budget import paced_daily_limit

    # יתרת ספק קבועה של 2 לשני ימים נותנת תקרה יומית 1. אחרי claim אחד
    # day_used גדל, אבל יתרת הספק שנמדדה לא הפכה ל-3 ולכן התקרה נשארת 1.
    assert paced_daily_limit(
        configured_daily=90, monthly_limit=90, month_used=0, day_used=0,
        days_left=2, provider_remaining=2,
    ) == 1
    assert paced_daily_limit(
        configured_daily=90, monthly_limit=90, month_used=1, day_used=1,
        days_left=2, provider_remaining=2,
    ) == 1
