"""GET /admin/cost-protection-status — חשיפת ערכי-האמת של הגנות-העלות
כפי שה-runtime באמת רואה אותם (30/08/2026).

הצורך: מ-24/08 הסנכרון היומי נכשל עם "SUMIT global minute request
budget exceeded" בהתנהגות של מגבלה=0, בעוד שניתוח הקוד+env צופה 10.
אי אפשר להכריע מרחוק מה ה-runtime של Vercel באמת טוען — הבעלים שואל
שוב ושוב "מה מוגדר כרגע?" והתשובה חייבת להגיע מהמערכת עצמה, לא
מהסקה. endpoint קריאה-בלבד, super-admin בלבד, אפס קריאות SUMIT.
"""
import pytest

from cfo.auth import create_access_token
from cfo.config import settings
from cfo.database import SessionLocal
from cfo.models import User, UserRole


@pytest.fixture
def super_admin(client, fresh_org):
    actor = fresh_org()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.organization_id == actor["org_id"]).first()
        user.role = UserRole.SUPER_ADMIN
        db.commit()
        token = create_access_token(data={
            "sub": str(user.id), "role": UserRole.SUPER_ADMIN.value,
            "org_id": user.organization_id,
        })
        org_id = user.organization_id
    finally:
        db.close()
    return {"headers": {"Authorization": f"Bearer {token}"}, "org_id": org_id}


def test_requires_super_admin(client, fresh_org):
    org = fresh_org()
    resp = client.get(
        "/api/admin/cost-protection-status", headers=org["headers"],
    )
    assert resp.status_code in (401, 403)


def test_reports_effective_sumit_limits(client, super_admin):
    resp = client.get(
        "/api/admin/cost-protection-status", headers=super_admin["headers"],
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    sumit = data["sumit"]
    assert sumit["environment"] == settings.sumit_environment
    assert sumit["global_requests_per_minute"] == settings.sumit_global_requests_per_minute
    assert sumit["org_daily_request_limit"] == settings.sumit_org_daily_request_limit
    assert sumit["test_monthly_request_limit"] == settings.sumit_test_monthly_request_limit
    assert sumit["live_monthly_request_limit"] == settings.sumit_live_monthly_request_limit
    assert sumit["enrichment_daily_action_limit"] == settings.sumit_enrichment_daily_action_limit
    # ההוכחה החשובה: מה שהמגביל בפועל היה מקבל עכשיו
    from cfo.services.sumit_request_budget import SumitRequestLimiter
    limiter = SumitRequestLimiter(super_admin["org_id"])
    assert sumit["effective_per_minute_limit"] == limiter.per_minute_limit
    assert sumit["effective_daily_limit"] == limiter.daily_limit
