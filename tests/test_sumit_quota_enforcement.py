"""המכסה נקראת מ-SUMIT — ואיסור מוחלט לעבור אותה.

**הממצא שהוליד את הקובץ (17/08/2026).** קריאה חינמית אחת ל-
`/website/companies/listquotas/` על תיק עמית פורת החזירה:

    ActionsBilling / Operations    Usage 0    Quota 50

זו מכסת הפעולות **בתשלום** — `getdetails` ו-`getpdf` נספרות שם.
התקרה הפנימית בקוד הייתה `25 ליום לארגון`. אם ה-50 חודשיים, 25/יום הם
750 בחודש — **פי 15 מהמכסה**.

כלומר התקרה שלנו מעולם לא הייתה תקרה: היא הייתה גדולה מהמכסה עצמה. זה
מסביר את ₪62.23/יום שחויבו ב-17/07 — המערכת חצתה את המכסה הכלולה ביומיים
וכל קריאה מעבר היא חיוב.

**התיקון:** לא לנחש את המכסה אלא לקרוא אותה. `listquotas` היא קריאה
חינמית (הוכח), ולכן היא נמשכת פעם ביום ונשמרת. התקרה נגזרת מהמדידה.

**honest-null מחמיר:** אין מדידה טרייה ⇒ פעולה בתשלום **נחסמת**. מכסה
לא-ידועה אינה מכסה פנויה.
"""
from datetime import datetime, timedelta, timezone

import pytest

from cfo.services import sumit_quota


class _Db:
    """DB מזויף מינימלי — הטסטים כאן בודקים הכרעה, לא persistence."""
    def __init__(self, rows=None):
        self.rows = rows or {}


@pytest.fixture
def fresh_quota():
    return sumit_quota.QuotaSnapshot(
        organization_id=1, used=0, limit=50,
        measured_at=datetime.now(timezone.utc),
    )


# ==================================================================== #
# פענוח תשובת SUMIT
# ==================================================================== #
LISTQUOTAS_RESPONSE = {
    "Data": [
        {"ApplicationName": "OutgoingEmails", "StatisticName": "Mails",
         "Usage": 3, "Quota": 5000},
        {"ApplicationName": "ActionsBilling", "StatisticName": "Operations",
         "Usage": 12, "Quota": 50},
        {"ApplicationName": "ActionsBilling", "StatisticName": "Obligo",
         "Usage": 1656, "Quota": 535662},
    ],
}


def test_the_paid_operations_quota_is_extracted():
    """`ActionsBilling/Operations` היא המכסה שעולה כסף — לא מיילים,
    לא אחסון, ולא Obligo (שהיא מסגרת אשראי, לא פעולות)."""
    snap = sumit_quota.parse_quota_response(LISTQUOTAS_RESPONSE, organization_id=1)

    assert snap.used == 12
    assert snap.limit == 50


def test_a_response_without_the_operations_row_is_honest_null():
    """מכסה שלא נמצאה אינה מכסה פנויה."""
    snap = sumit_quota.parse_quota_response(
        {"Data": [{"ApplicationName": "Files", "StatisticName": "Storage",
                   "Usage": 1, "Quota": 5000}]},
        organization_id=1,
    )

    assert snap is None


def test_a_malformed_response_does_not_invent_a_quota():
    for bad in ({}, {"Data": None}, {"Data": "nope"}, None):
        assert sumit_quota.parse_quota_response(bad, organization_id=1) is None


# ==================================================================== #
# האיסור המוחלט
# ==================================================================== #
def test_a_paid_action_is_allowed_below_the_quota(fresh_quota):
    sumit_quota.assert_paid_action_within_quota(fresh_quota, endpoint="getdetails")


def test_reaching_the_quota_blocks_absolutely(fresh_quota):
    """**איסור מוחלט**: ניצול ששווה למכסה חוסם. לא אזהרה, לא 'עוד אחת'."""
    at_limit = fresh_quota.__class__(
        organization_id=1, used=50, limit=50, measured_at=fresh_quota.measured_at)

    with pytest.raises(sumit_quota.SumitQuotaExhausted):
        sumit_quota.assert_paid_action_within_quota(at_limit, endpoint="getdetails")


def test_exceeding_the_quota_blocks(fresh_quota):
    over = fresh_quota.__class__(
        organization_id=1, used=73, limit=50, measured_at=fresh_quota.measured_at)

    with pytest.raises(sumit_quota.SumitQuotaExhausted):
        sumit_quota.assert_paid_action_within_quota(over, endpoint="getpdf")


def test_missing_measurement_blocks_rather_than_opens():
    """אין מדידה ⇒ אין פעולה בתשלום. מכסה לא-ידועה אינה מכסה פנויה —
    וזו בדיוק הנקודה שבה תקרה שנפתחת בשקט עולה כסף."""
    with pytest.raises(sumit_quota.SumitQuotaUnknown):
        sumit_quota.assert_paid_action_within_quota(None, endpoint="getdetails")


def test_a_stale_measurement_blocks(fresh_quota):
    """מדידה מלפני יומיים אינה ראיה למצב היום."""
    stale = fresh_quota.__class__(
        organization_id=1, used=0, limit=50,
        measured_at=datetime.now(timezone.utc) - timedelta(days=2),
    )

    with pytest.raises(sumit_quota.SumitQuotaUnknown):
        sumit_quota.assert_paid_action_within_quota(stale, endpoint="getdetails")


def test_the_remaining_headroom_is_reported(fresh_quota):
    assert fresh_quota.remaining == 50

    used = fresh_quota.__class__(
        organization_id=1, used=44, limit=50, measured_at=fresh_quota.measured_at)
    assert used.remaining == 6


def test_high_utilisation_is_flagged_before_it_blocks(fresh_quota):
    """80% הוא סף התרעה — כדי שהבעלים יידע לפני שנחסם, לא אחרי."""
    warn = fresh_quota.__class__(
        organization_id=1, used=41, limit=50, measured_at=fresh_quota.measured_at)

    assert warn.is_near_limit is True
    assert fresh_quota.is_near_limit is False


def test_a_zero_quota_blocks_everything(fresh_quota):
    """מכסה 0 אינה 'ללא הגבלה'."""
    zero = fresh_quota.__class__(
        organization_id=1, used=0, limit=0, measured_at=fresh_quota.measured_at)

    with pytest.raises(sumit_quota.SumitQuotaExhausted):
        sumit_quota.assert_paid_action_within_quota(zero, endpoint="getdetails")


# ==================================================================== #
# הקריאה עצמה חינמית
# ==================================================================== #
def test_the_refresh_endpoint_is_the_free_one():
    """אם רענון המכסה היה עולה כסף, הוא היה חלק מהבעיה."""
    assert sumit_quota.QUOTA_ENDPOINT == "/website/companies/listquotas/"
    assert "getdetails" not in sumit_quota.QUOTA_ENDPOINT
    assert "getpdf" not in sumit_quota.QUOTA_ENDPOINT


# ==================================================================== #
# החיבור לקליינט — האיסור יושב במסלול, לא אצל הקוראים
# ==================================================================== #
@pytest.mark.asyncio
async def test_the_client_blocks_a_paid_action_without_a_quota_snapshot():
    """`getdetails` בלי מדידת מכסה — נחסם לפני הרשת.

    זה מה שהופך את האיסור למוחלט: הוא במסלול הבקשה, ולכן קורא חדש,
    סקריפט ידני או קונסול אינם יכולים לעקוף אותו.
    """
    from cfo.integrations.sumit_integration import SumitIntegration

    class _AllowAll:
        def claim(self, endpoint):
            return None

    client = SumitIntegration(
        api_key="9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23", company_id="1",
        request_limiter=_AllowAll(),
    )

    with pytest.raises(sumit_quota.SumitQuotaError):
        await client.get_document_supplier_details("123")


@pytest.mark.asyncio
async def test_a_free_call_is_not_blocked_by_the_quota_gate(monkeypatch):
    """שער נגדי: `list` אינה פעולה בתשלום. חסימתה הייתה עוצרת את
    הסנכרון היומי בלי להפחית עלות."""
    from cfo.integrations.sumit_integration import SumitIntegration
    from cfo.integrations.sumit_models import DocumentListRequest

    class _AllowAll:
        def claim(self, endpoint):
            return None

    client = SumitIntegration(
        api_key="9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23", company_id="1",
        request_limiter=_AllowAll(),
    )

    sent = []

    async def _post(path, payload=None, **kw):
        sent.append(path)
        return {"Items": []}

    monkeypatch.setattr(client, "_post", _post)

    await client.list_documents(DocumentListRequest())

    assert sent, "קריאת רשימה נחסמה בטעות על ידי שער המכסה"
