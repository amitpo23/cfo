"""מפתח placeholder לעולם לא יוצא לרשת — שכבה שנייה, בקוד הייצור.

חומת הרשת ב-`conftest.py` מגנה על הסוויטה. היא אינה מגנה על סקריפט
ידני, קונסולה, notebook או סביבת dev שבה מישהו הגדיר בטעות מפתח
דמה — וכל אחד מאלה מייצר את אותה חסימה על אותה כתובת IP.

הכלל: `SumitIntegration` מסרב לצאת לרשת עם מפתח שנראה כמו placeholder,
**לפני** בניית הבקשה. עדיף להיכשל מיידית עם הסבר מאשר לצבור ניסיונות
אימות כושלים שחוסמים את הבעלים.

זה אינו תחליף לשערי העלות: `_assert_paid_actions_enabled` חוסם פעולות
מסמך בתשלום, והשער הזה חוסם קרדנשל שאינו אמיתי. שני סיכונים שונים —
חיוב מול חסימה.
"""
import pytest

from cfo.integrations.sumit_integration import (
    PlaceholderCredentialsRefused, SumitIntegration,
)


PLACEHOLDERS = [
    "test-env-sumit-key",
    "test-key",
    "dummy",
    "placeholder",
    "changeme",
    "your-api-key-here",
    "xxxxxxxx",
]


class _UnlimitedTestBudget:
    def claim(self, _kind):
        return None


@pytest.mark.parametrize("key", PLACEHOLDERS)
@pytest.mark.asyncio
async def test_a_placeholder_key_never_reaches_the_network(key):
    """`_make_request` היא נקודת הרשת היחידה. הסירוב קורה בתוכה, לפני
    בניית הבקשה — ולכן גם `_post`, גם `_post_binary` וגם כל קורא עתידי
    מכוסים בלי לזכור להוסיף שער."""
    client = SumitIntegration(api_key=key, company_id="1")

    with pytest.raises(PlaceholderCredentialsRefused):
        await client._make_request("/accounting/documents/list/", data={})


@pytest.mark.asyncio
async def test_the_refusal_explains_the_consequence():
    """מי שנתקל בשער חייב להבין למה — אחרת יעקוף אותו."""
    client = SumitIntegration(api_key="test-env-sumit-key", company_id="1")

    with pytest.raises(PlaceholderCredentialsRefused) as err:
        await client._make_request("/accounting/documents/list/", data={})

    text = str(err.value).lower()
    assert "placeholder" in text
    assert "block" in text


@pytest.mark.asyncio
async def test_an_empty_key_is_refused_too():
    client = SumitIntegration(api_key="", company_id="1")

    with pytest.raises(PlaceholderCredentialsRefused):
        await client._make_request("/accounting/documents/list/", data={})


@pytest.mark.asyncio
async def test_a_realistic_key_is_not_refused(monkeypatch):
    """שער נגדי: חסימה גורפת מדי הייתה משביתה את הפרוד.

    המפתח פיקטיבי אך אינו נראה כמו placeholder, ולכן הבקשה ממשיכה —
    וכאן נעצרת בשכבת ה-HTTP המזויפת, לא ברשת."""
    client = SumitIntegration(
        api_key="9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23",
        company_id="1",
        request_limiter=_UnlimitedTestBudget(),
    )

    sent = []

    class _FakeResponse:
        status_code = 200
        text = '{"Status":0,"Data":{}}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"Status": 0, "Data": {}}

    async def _capture(method=None, url=None, **kw):
        sent.append(url)
        return _FakeResponse()

    monkeypatch.setattr(client.client, "request", _capture)

    await client._make_request("/accounting/documents/list/", data={})

    assert sent == ["/accounting/documents/list/"]


@pytest.mark.asyncio
async def test_the_guard_covers_the_binary_path_too():
    """`_post_binary` (getpdf) עוקף את `_post` — הוא חייב שער משלו."""
    client = SumitIntegration(api_key="test-env-sumit-key", company_id="1")

    with pytest.raises(PlaceholderCredentialsRefused):
        await client._post_binary("/accounting/documents/getpdf/", {})
