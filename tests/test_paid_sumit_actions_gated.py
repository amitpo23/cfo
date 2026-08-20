"""כיבוי גורף של פעולות SUMIT בתשלום — שער בקליינט, לא בקוראים.

רקע (11/08/2026): הבעלים דיווח שכל לקוח וגם חשבון המשרד קיבלו חיוב של
מאות שקלים. המדידה ב-`sync_runs` הראתה ~21 ריצות SUMIT ליום לכל תיק עד
17/07. הגורם: `/accounting/documents/getdetails/` היא פעולה בתשלום
**לכל מסמך**, ו-SUMIT מחייבת את אמצעי התשלום של חברת הלקוח — ולכן החיוב
נחת על כל תיק בנפרד.

התיקון הראשון הסיר שני cron והציב `SUMIT_ENRICHMENT_DAILY_ACTION_LIMIT=0`.
אבל אותו שער נבדק **רק** ב-`/cron/enrich-expenses`. ארבע כניסות ידניות
עקפו אותו לגמרי:

    POST /expenses/resolve-suppliers      → getdetails (מנתי, limit=None)
    GET  /accounting/documents/{id}       → getdetails
    POST /expenses/{id}/ocr               → getpdf
    GET  /accounting/documents/{id}/pdf   → getpdf

הבעלים ביקש "שלא יהיו חיובים של api **מאף אחד**". שער פר-קורא אינו זה:
הוא סוגר את מי שמכירים ומשאיר פתוח את הקורא הבא שמישהו יוסיף. לכן השער
יושב במתודות הקליינט עצמן — המקום היחיד שאי-אפשר לעקוף.

`sumit_enrichment_daily_action_limit == 0` פירושו "פעולות מסמך בתשלום
כבויות". תקצוב הכמות היומי (>0) נשאר היכן שהוא — הוא דורש DB, והקליינט
חסר-מצב במכוון.
"""
import inspect

import pytest

from cfo.integrations.sumit_integration import (
    PaidSumitActionDisabled,
    SumitIntegration,
)


PAID_ENDPOINTS = (
    "/accounting/documents/getdetails/",
    "/accounting/documents/getpdf/",
)

PAID_METHODS = (
    "get_document_details",
    "get_document_pdf",
    "get_document_supplier_details",
)


@pytest.fixture
def client():
    return SumitIntegration(api_key="k", company_id="1")


@pytest.fixture
def budget_off(monkeypatch):
    from cfo.config import settings

    monkeypatch.setattr(settings, "sumit_enrichment_daily_action_limit", 0)


@pytest.fixture
def budget_on(monkeypatch):
    from cfo.config import settings

    monkeypatch.setattr(settings, "sumit_enrichment_daily_action_limit", 25)


@pytest.mark.parametrize("method_name", PAID_METHODS)
@pytest.mark.asyncio
async def test_paid_document_action_refuses_when_budget_is_zero(
    client, budget_off, monkeypatch, method_name
):
    """אף אחת מהשלוש לא יוצאת לרשת כשהתקציב אפס."""
    called = []

    async def _explode(*args, **kwargs):
        called.append(args)
        raise AssertionError("יצאה קריאה בתשלום למרות שהתקציב אפס")

    monkeypatch.setattr(client, "_post", _explode)
    monkeypatch.setattr(client, "_post_binary", _explode)

    with pytest.raises(PaidSumitActionDisabled):
        await getattr(client, method_name)("123")

    assert not called


@pytest.mark.asyncio
async def test_supplier_name_shortcut_is_gated_too(client, budget_off, monkeypatch):
    """`get_document_supplier` הוא עטיפה — אסור שיהיה דלת אחורית."""
    async def _explode(*args, **kwargs):
        raise AssertionError("יצאה קריאה בתשלום")

    monkeypatch.setattr(client, "_post", _explode)

    with pytest.raises(PaidSumitActionDisabled):
        await client.get_document_supplier("123")


@pytest.mark.asyncio
async def test_error_names_the_setting_that_reopens_it(client, budget_off, monkeypatch):
    """מי שנתקל בשער חייב לדעת מה להזיז — אחרת יעקוף אותו בקוד."""
    async def _explode(*args, **kwargs):
        raise AssertionError("יצאה קריאה בתשלום")

    monkeypatch.setattr(client, "_post", _explode)

    with pytest.raises(PaidSumitActionDisabled) as err:
        await client.get_document_details("123")

    assert "SUMIT_ENRICHMENT_DAILY_ACTION_LIMIT" in str(err.value)


@pytest.mark.asyncio
async def test_budget_above_zero_still_allows_the_call(client, budget_on, monkeypatch):
    """השער הוא מתג כיבוי, לא חסימה קבועה — עם תקציב הקריאה עוברת.

    מ-17/08/2026 קיים שער שני ובלתי-תלוי: מכסת הספק בפועל
    (`ActionsBilling/Operations`, נקראת מ-listquotas). הטסט הזה בודק את
    **מתג הכיבוי**, ולכן הוא מזריק מדידת מכסה תקפה — ולא מבטל את השער
    השני. שני השערים חייבים להיפתח כדי שפעולה בתשלום תצא.
    """
    from datetime import datetime, timezone
    from cfo.services.sumit_quota import QuotaSnapshot

    client.quota_snapshot = QuotaSnapshot(
        organization_id=1, used=0, limit=50,
        measured_at=datetime.now(timezone.utc),
    )
    sent = []

    async def _post(path, payload=None, **kwargs):
        sent.append(path)
        return {"Document": {}, "Items": []}

    monkeypatch.setattr(client, "_post", _post)

    await client.get_document_supplier_details("123")

    assert sent == ["/accounting/documents/getdetails/"]


@pytest.mark.asyncio
async def test_free_endpoints_are_not_gated(client, budget_off, monkeypatch):
    """השער חוסם פעולות מסמך בתשלום בלבד. `list` אינה כזו — אם היא
    תיחסם, הסנכרון היומי ייעצר ונאבד נתונים בלי סיבה."""
    from cfo.integrations.sumit_models import DocumentListRequest

    sent = []

    async def _post(path, payload=None, **kwargs):
        sent.append(path)
        return {"Items": []}

    monkeypatch.setattr(client, "_post", _post)

    await client.list_documents(DocumentListRequest())

    assert sent, "קריאת רשימה נחסמה בטעות — היא אינה פעולה בתשלום"


def test_every_paid_endpoint_call_site_lives_in_a_gated_method():
    """זהו השער שמחזיק את ההבטחה לאורך זמן.

    לא מספיק לגדר את שלוש המתודות הידועות: מי שיוסיף מחר מתודה רביעית
    שקוראת ל-getdetails יחזיר את החיוב. הטסט סורק את המקור, מוצא כל
    קריאה ל-endpoint בתשלום, ודורש שהמתודה העוטפת קוראת לשער.
    """
    import cfo.integrations.sumit_integration as mod

    source = inspect.getsource(mod).splitlines()

    # מיפוי כל שורה למתודה שהיא נמצאת בתוכה
    owner_of_line: dict[int, str] = {}
    current = None
    for idx, line in enumerate(source):
        stripped = line.strip()
        if stripped.startswith(("def ", "async def ")):
            current = stripped.split("(")[0].replace("async def ", "").replace("def ", "")
        owner_of_line[idx] = current

    # שורות בתוך הגדרת הקבוע PAID_ACTION_ENDPOINTS הן רשימת השערים עצמה,
    # לא נקודות קריאה — מדלגים עליהן בלבד (כל שימוש מודולרי אחר עדיין נתפס).
    in_const_block = False
    const_lines: set[int] = set()
    for idx, line in enumerate(source):
        stripped = line.strip()
        if stripped.startswith("PAID_ACTION_ENDPOINTS"):
            in_const_block = True
        if in_const_block:
            const_lines.add(idx)
            if stripped == "})":
                in_const_block = False

    offenders = []
    for idx, line in enumerate(source):
        if not any(f'"{ep}"' in line for ep in PAID_ENDPOINTS):
            continue
        if idx in const_lines:
            continue
        method = owner_of_line[idx]
        if method is None:
            offenders.append(f"שורה {idx + 1}: קריאה בתשלום מחוץ למתודה")
            continue
        body = inspect.getsource(getattr(mod.SumitIntegration, method))
        if "_assert_paid_actions_enabled" not in body:
            offenders.append(f"{method} (שורה {idx + 1}) קוראת ל-endpoint בתשלום בלי שער")

    assert not offenders, "נתיבי חיוב בלתי-מגודרים:\n  " + "\n  ".join(offenders)


def test_the_gate_covers_every_method_we_know_is_paid():
    """שער הפוך: אם מישהו ימחק את הבדיקה מאחת המתודות, זה ייתפס."""
    import cfo.integrations.sumit_integration as mod

    for name in PAID_METHODS + ("get_document_supplier",):
        body = inspect.getsource(getattr(mod.SumitIntegration, name))
        gated_directly = "_assert_paid_actions_enabled" in body
        # `get_document_supplier` מגודר דרך המתודה שהוא עוטף
        delegates = "get_document_supplier_details" in body
        assert gated_directly or delegates, f"{name} אינה מגודרת"
