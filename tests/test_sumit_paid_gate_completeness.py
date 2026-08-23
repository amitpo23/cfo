"""W2.5 + P0-A — השלמת שער הפעולות-בתשלום.

הפערים שנמצאו בחקירת 20/08:
- `getdetails`/`getpdf` — הפעולות שגרמו לחיוב האמיתי ב-17/07 — לא היו
  ב-`PAID_ACTION_ENDPOINTS`; הוגנו רק ברמת המתודה, ו-`_post_binary` לא
  בדק את הרשימה בכלל.
- המונה החודשי לפעולות-בתשלום נתבע רק ב-test — ב-live ההגנה היחידה היא
  המדידה מהספק, בלי מונה עמיד משלנו.

**P0-A (23/08/2026, ביקורת קודקס — ממצא 2).** `PAID_ACTION_ENDPOINTS`
עצמה הייתה רשימת-היתר ידנית: כל endpoint שלא הוזכר בה עבר "חינם" דרך
תקרת הבקשות הכללית בלבד, בלי לגעת בשער הפעולות-בתשלום — כך ברחו
create-customer, createbatch, cancel-document, move-to-books ועוד.
הסגר: ברירת המחדל התהפכה ל-paid; `FREE_ENDPOINTS` היא הרשימה הקטנה
והמפורשת, ושער הרשת בודק `endpoint not in FREE_ENDPOINTS` — לא
`in PAID_ACTION_ENDPOINTS`. הבדיקות למטה מוכיחות את שני הכיוונים:
(1) endpoint שלא סווג בכוונה נחסם כברירת מחדל, לא בורח; (2) כל
endpoint שהקוד באמת קורא לו מסווג במפורש לאחת משתי הרשימות (AST, לא
grep — אותו דפוס כמו `tests/test_sumit_rate_limit_hard_rule.py`).
"""
import ast
import asyncio
import pathlib
from datetime import datetime, timezone

import pytest

from cfo.config import settings
from cfo.database import SessionLocal
from cfo.models import ProviderRequestBudget
from cfo.integrations.sumit_integration import (
    FREE_ENDPOINTS,
    PAID_ACTION_ENDPOINTS,
    SumitIntegration,
)
from cfo.services import sumit_quota
from cfo.services.sumit_request_budget import SumitRequestLimiter


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


# ==================================================================== #
# P0-A — ברירת-מחדל paid, כיסוי מלא של הקונקטור
# ==================================================================== #

REPO_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "cfo"
_SUMIT_INTEGRATION_FILE = REPO_SRC / "integrations" / "sumit_integration.py"

_GATED_METHOD_NAMES = {"_post", "_make_request", "_post_binary"}


def _endpoint_literals_called_by_the_connector() -> set[str]:
    """כל מחרוזת endpoint שהקוד קורא לה בפועל דרך `_post`/`_make_request`/
    `_post_binary`, ב-AST — לא grep, כדי לא לפספס קריאה מרובת-שורות
    ולא להיתפס ע"י מחרוזת שמופיעה רק בהערה או ב-frozenset ההגדרה."""
    source = _SUMIT_INTEGRATION_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_SUMIT_INTEGRATION_FILE))
    literals: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not isinstance(fn, ast.Attribute) or fn.attr not in _GATED_METHOD_NAMES:
            continue
        if not (isinstance(fn.value, ast.Name) and fn.value.id == "self"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            literals.add(first.value)
    return literals


def test_free_and_paid_endpoint_sets_are_disjoint():
    assert FREE_ENDPOINTS.isdisjoint(PAID_ACTION_ENDPOINTS), (
        "endpoint לא יכול להיות גם free וגם paid — סימן לטעות סיווג"
    )


def test_every_endpoint_the_connector_calls_is_explicitly_classified():
    """הבדיקה שהמשימה ביקשה: אין endpoint שלא סווג בכוונה לאחת משתי
    הרשימות. תוספת endpoint חדש לקוד בלי לסווג אותו מפילה את הבדיקה
    הזו — לא בורחת בשקט כמו שקרה עם create-customer/createbatch/וגו'."""
    called = _endpoint_literals_called_by_the_connector()
    known = FREE_ENDPOINTS | PAID_ACTION_ENDPOINTS
    unclassified = called - known
    assert not unclassified, (
        f"endpoint לא מסווג ב-FREE_ENDPOINTS/PAID_ACTION_ENDPOINTS: {unclassified}"
    )


def test_the_audit_flagged_gaps_are_now_paid():
    """ממצא 2 של ביקורת קודקס, במפורש: create-customer, createbatch,
    cancel-document, move-to-books לא היו ברשימת ההיתר הידנית."""
    for endpoint in (
        "/accounting/customers/create/",
        "/books/transactions/createbatch/",
        "/accounting/documents/cancel/",
        "/accounting/documents/movetobooks/",
    ):
        assert endpoint in PAID_ACTION_ENDPOINTS, endpoint
        assert endpoint not in FREE_ENDPOINTS, endpoint


def test_an_unclassified_endpoint_defaults_to_paid_and_blocks_without_a_snapshot(
    fresh_org,
):
    """ליבת ממצא 2: לפני P0-A, endpoint שלא הופיע ב-PAID_ACTION_ENDPOINTS
    היה עובר ישר לרשת (בלי מדידת מכסה). אחרי: ברירת המחדל paid, ובלי
    מדידה טרייה — נחסם fail-closed, בדיוק כמו endpoint ידוע-בתשלום."""
    org_id = fresh_org()["org_id"]
    integration = SumitIntegration(
        api_key="9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23", company_id="1",
        request_limiter=SumitRequestLimiter(org_id),
    )
    made_up_endpoint = "/accounting/documents/some-new-mutation-nobody-classified/"
    assert made_up_endpoint not in FREE_ENDPOINTS
    assert made_up_endpoint not in PAID_ACTION_ENDPOINTS

    with pytest.raises(sumit_quota.SumitQuotaError):
        integration._enforce_paid_action_budget(made_up_endpoint)


def test_a_verified_free_endpoint_never_touches_the_paid_budget(monkeypatch, fresh_org):
    """הכיוון ההפוך, קצה-לקצה: `_make_request` על listquotas מצליח **בלי
    שום מדידת מכסה קיימת** — אחרת listquotas עצמה הייתה לא-ניתנת-לרענון
    (בעיית ה-bootstrap שהוזכרה ב-advisor: אין דרך לרענן מכסה אם רענון
    המכסה עצמו דורש מכסה קיימת)."""
    from cfo.integrations import sumit_integration as mod

    org_id = fresh_org()["org_id"]
    mod._SUMIT_ENVIRONMENT_CACHE.clear()
    integration = SumitIntegration(
        api_key="9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23", company_id="1",
        request_limiter=SumitRequestLimiter(org_id),
    )

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

    # אין אף SumitQuotaMeasurement ב-DB לארגון הזה, ו-quota_snapshot לא
    # הוזרק — endpoint לא-חינמי היה נחסם כאן. listquotas לא נוגע בשער.
    result = asyncio.run(integration._make_request("/website/companies/listquotas/"))
    assert result["Status"] == 0
    asyncio.run(integration.client.aclose())
    mod._SUMIT_ENVIRONMENT_CACHE.clear()
