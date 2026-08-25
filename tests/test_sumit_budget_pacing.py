"""W2.2+W2.3 — תקרה חודשית בכל סביבה + קצב יומי שנגזר מהחודשי.

הפערים שנמצאו בחקירת 20/08:
- החלון החודשי נתבע רק כש-`sumit_environment == "test"` — ב-live אין בלם
  חודשי בכלל (300/יום ≈ 9,000/חודש).
- ה-20/יום קבוע ומנותק מה-200/חודש (20×30=600) — המכסה החודשית נשרפת עד
  יום ~10 ואז חסימה מלאה עד סוף החודש, בלי pacing.
"""
import pytest

from cfo.config import settings
from cfo.database import SessionLocal
from cfo.models import ProviderRequestBudget
from cfo.services.sumit_request_budget import (
    SumitRequestBudgetExceeded,
    SumitRequestLimiter,
    paced_daily_limit,
)


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


# ==================================================================== #
# W2.2 — תקרה חודשית גם ב-live
# ==================================================================== #

def test_monthly_window_is_claimed_in_live_environment(monkeypatch, fresh_org):
    """ב-live החלון החודשי חייב להיתבע — לא רק ב-test. בלעדיו התקרה
    האפקטיבית היא 300/יום בלי שום בלם חודשי."""
    org_id = fresh_org()["org_id"]
    monkeypatch.setattr(settings, "sumit_environment", "live")
    monkeypatch.setattr(settings, "sumit_live_monthly_request_limit", 2)
    # מנטרלים את הקצב היומי (נבחן בנפרד) כדי לבודד את החלון החודשי.
    import cfo.services.sumit_request_budget as budget_module
    monkeypatch.setattr(budget_module, "paced_daily_limit", lambda **_kw: 50)

    limiter = SumitRequestLimiter(org_id, per_minute_limit=50, daily_limit=50)
    limiter.claim("/one")
    limiter.claim("/two")
    with pytest.raises(SumitRequestBudgetExceeded, match="monthly"):
        limiter.claim("/three")


def test_live_monthly_limit_cannot_be_raised_above_code_ceiling():
    """שדה הקונפיג של live מוצמד לתקרה קשיחה — env לא יכול להרים אותו.

    הנחיית בעלים (25/08/2026): 200/חודש הוא תקרה קשיחה **גם ב-live**,
    לא רק ב-test — אין הבדל-פי-10 בין הסביבות."""
    from cfo.config import Settings
    loosened = Settings(sumit_live_monthly_request_limit=999_999)
    assert loosened.sumit_live_monthly_request_limit <= 200


def test_live_monthly_default_matches_test_track_ceiling():
    """בלי override כלשהו, ברירת המחדל עצמה כבר 200 — לא רק התקרה."""
    from cfo.config import Settings
    s = Settings()
    assert s.sumit_live_monthly_request_limit <= 200


# ==================================================================== #
# W2.3 — קצב יומי נגזר מהחודשי
# ==================================================================== #

def test_paced_daily_limit_spreads_remaining_budget_over_days_left():
    # נשארו 100 מתוך 200, נשארו 10 ימים → 10 ליום, לא 20.
    assert paced_daily_limit(
        configured_daily=20, monthly_limit=200, month_used=100, days_left=10,
    ) == 10


def test_paced_daily_limit_never_exceeds_the_configured_daily():
    # תחילת חודש: remaining=200, days_left=30 → ceil=7 < 20 → קצב.
    assert paced_daily_limit(
        configured_daily=20, monthly_limit=200, month_used=0, days_left=30,
    ) == 7


def test_paced_daily_limit_is_zero_when_month_is_exhausted():
    assert paced_daily_limit(
        configured_daily=20, monthly_limit=200, month_used=200, days_left=5,
    ) == 0


def test_claim_uses_the_paced_daily_limit(monkeypatch, fresh_org):
    """הקצב נאכף בפועל: כשהחישוב מחזיר 1 — התביעה השנייה באותו יום נופלת
    על התקרה היומית, גם אם התקרה המוגדרת גבוהה בהרבה."""
    org_id = fresh_org()["org_id"]
    import cfo.services.sumit_request_budget as budget_module

    monkeypatch.setattr(
        budget_module, "paced_daily_limit",
        lambda **_kwargs: 1,
    )
    limiter = SumitRequestLimiter(org_id, per_minute_limit=50, daily_limit=50)
    limiter.claim("/one")
    with pytest.raises(SumitRequestBudgetExceeded, match="daily"):
        limiter.claim("/two")
