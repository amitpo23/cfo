"""כל מסלול רשת בקליינט תופס מכסה — כולל המסלול הבינארי.

`_make_request` תופס מכסה נכון (`request_limiter.claim`) ומסרב בלי
limiter. אבל `_post_binary` — המסלול של **`/accounting/documents/getpdf/`,
שהיא פעולה בתשלום פר-מסמך** — קורא ל-`self.client.post` ישירות ואינו
תופס דבר.

זו אותה צורת פער שכבר עלתה כסף פעמיים:

- 17/07/2026 — סנכרון רץ 24×/יום; SUMIT חייבה את חברת הלקוח ₪62.23/יום.
- 13/08/2026 — 116 קריאות לכל ריצת טסטים; ~1,000 כשלי אימות חסמו את
  ה-IP של המשרד.

בשני המקרים היו שערים, והם ישבו במקום אחד ולא בשני.

הכלל: **כל מסלול שיוצא לרשת תופס מכסה.** לא הרוב, לא "החשובים".
"""
import inspect

import pytest

from cfo.integrations import sumit_integration as mod
from cfo.integrations.sumit_integration import (
    SumitIntegration, SumitRequestBudgetRequired,
)


REAL_KEY = "9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23"

# כל מתודה בקליינט שפותחת חיבור בעצמה, ולא דרך `_make_request`.
NETWORK_METHODS = ("_make_request", "_post_binary")


@pytest.mark.parametrize("method_name", NETWORK_METHODS)
def test_every_network_path_claims_the_budget(method_name):
    """שער מבני: מסלול רשת בלי תפיסת מכסה הוא מסלול שעוקף את התקרה."""
    source = inspect.getsource(getattr(SumitIntegration, method_name))

    assert "request_limiter" in source, (
        f"{method_name} יוצא לרשת בלי לתפוס מכסה"
    )


@pytest.mark.parametrize("method_name", NETWORK_METHODS)
def test_every_network_path_refuses_without_a_limiter(method_name):
    """fail-closed: אין מונה ⇒ אין קריאה. תקרה שנפתחת כשאי-אפשר לספור
    אינה תקרה — וזו הדרישה המפורשת ברונבוק."""
    source = inspect.getsource(getattr(SumitIntegration, method_name))

    assert "SumitRequestBudgetRequired" in source, (
        f"{method_name} אינו מסרב כשאין limiter"
    )


@pytest.mark.asyncio
async def test_the_binary_path_refuses_without_a_limiter(monkeypatch):
    """הוכחה התנהגותית, לא רק מבנית: getpdf בלי מונה אינו יוצא."""
    client = SumitIntegration(api_key=REAL_KEY, company_id="1")

    async def _explode(*a, **kw):
        raise AssertionError("getpdf יצא לרשת בלי מכסה")

    monkeypatch.setattr(client.client, "post", _explode)

    with pytest.raises(SumitRequestBudgetRequired):
        await client._post_binary("/accounting/documents/getpdf/", {})


@pytest.mark.asyncio
async def test_the_binary_path_claims_before_the_network(monkeypatch):
    """התפיסה קורית **לפני** הבקשה, לא אחריה."""
    claimed = []

    class _Limiter:
        def claim(self, endpoint):
            claimed.append(endpoint)

    client = SumitIntegration(
        api_key=REAL_KEY, company_id="1", request_limiter=_Limiter(),
    )

    class _Resp:
        status_code = 200
        headers = {"content-type": "application/pdf"}
        content = b"%PDF-1.4"

        def raise_for_status(self):
            return None

    async def _post(endpoint, **kw):
        assert claimed, "יצאה בקשה בינארית לפני תפיסת מכסה"
        return _Resp()

    class _VerifyResp:
        status_code = 200
        text = "{}"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "Status": 0,
                "Data": {"Company": {"CorporateNumber": "999999998"}},
            }

    async def _verify(*_args, **_kwargs):
        return _VerifyResp()

    monkeypatch.setattr(client.client, "request", _verify)
    monkeypatch.setattr(client.client, "post", _post)

    await client._post_binary("/accounting/documents/getpdf/", {})

    assert claimed == [
        "/website/companies/getdetails/",
        "/accounting/documents/getpdf/",
    ]


@pytest.mark.asyncio
async def test_an_exhausted_budget_stops_the_binary_path(monkeypatch):
    from cfo.services.sumit_request_budget import SumitRequestBudgetExceeded

    class _Exhausted:
        def claim(self, endpoint):
            raise SumitRequestBudgetExceeded("daily cap reached")

    client = SumitIntegration(
        api_key=REAL_KEY, company_id="1", request_limiter=_Exhausted(),
    )

    async def _explode(*a, **kw):
        raise AssertionError("יצאה בקשה למרות שהמכסה נגמרה")

    monkeypatch.setattr(client.client, "post", _explode)

    with pytest.raises(SumitRequestBudgetExceeded):
        await client._post_binary("/accounting/documents/getpdf/", {})


def test_no_other_method_opens_a_connection_directly():
    """אם מישהו יוסיף מחר מתודה שקוראת ל-`self.client.<verb>` ישירות,
    היא תעקוף את התקרה — והשער הזה יתפוס אותה."""
    source = inspect.getsource(mod)
    offenders = []
    for name, fn in vars(SumitIntegration).items():
        if not callable(fn) or name in NETWORK_METHODS:
            continue
        try:
            body = inspect.getsource(fn)
        except (OSError, TypeError):
            continue
        # פעלי בקשה בלבד. `self.client.aclose()` ב-`__aexit__` סוגר
        # חיבור ואינו שולח בקשה — סימונו היה חיוב-שווא שמלמד להתעלם
        # מהשער.
        sends = any(
            f"self.client.{verb}(" in body
            for verb in ("request", "get", "post", "put", "patch", "delete", "send")
        )
        if sends and "request_limiter" not in body:
            offenders.append(name)

    assert not offenders, f"מסלולי רשת שעוקפים את התקרה: {offenders}"
