"""בדיקות ה-OCR pipeline לעיבוד טיוטות הוצאה (חילוץ ראייה -> אימות ח.פ -> תיוק)."""
from datetime import date

import pytest

from cfo.services.company_registry import CompanyRegistry, normalize_tax_id
from cfo.services.expense_ocr_pipeline import ExpenseOCRPipeline
from cfo.services.vision_extractor import _decode_json, _normalize


# ---------- company registry parsing ----------

def test_normalize_tax_id():
    assert normalize_tax_id(" 51-140 2547 ") == "511402547"
    assert normalize_tax_id(None) == ""


def test_registry_parse_exact_match():
    payload = {"result": {"records": [
        {"מספר חברה": "511402547", "שם חברה": "חברה לדוגמה בע\"מ", "סטטוס חברה": "פעילה"},
        {"מספר חברה": "999999999", "שם חברה": "אחרת בע\"מ"},
    ]}}
    res = CompanyRegistry._parse_records("511402547", payload)
    assert res["name"] == "חברה לדוגמה בע\"מ"
    assert res["tax_id"] == "511402547"
    assert res["status"] == "פעילה"


def test_registry_parse_no_match():
    payload = {"result": {"records": [{"מספר חברה": "111111111", "שם חברה": "X"}]}}
    assert CompanyRegistry._parse_records("511402547", payload) is None


# ---------- vision extractor pure logic ----------

def test_decode_json_with_fence():
    assert _decode_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_decode_json_plain_with_prose():
    assert _decode_json('הנה התוצאה: {"a": 2} סוף') == {"a": 2}


def test_normalize_cleans_types():
    raw = {
        "supplier_name": " שופרסל ",
        "supplier_tax_id": "52-0022732",
        "amount_total": "104.90",
        "vat_amount": None,
        "confidence": "0.9",
        "is_readable": True,
    }
    n = _normalize(raw)
    assert n["supplier_name"] == "שופרסל"
    assert n["supplier_tax_id"] == "520022732"
    assert n["amount_total"] == 104.90
    assert n["confidence"] == 0.9


# ---------- amount resolution ----------

def test_resolve_amounts_from_total_only():
    total, net, vat = ExpenseOCRPipeline._resolve_amounts(
        {"amount_total": 118.0, "vat_amount": None, "net_amount": None}
    )
    assert total == 118.0
    assert round(vat, 2) == 18.0   # 118 - 118/1.18
    assert round(net, 2) == 100.0


def test_resolve_amounts_with_explicit_vat():
    total, net, vat = ExpenseOCRPipeline._resolve_amounts(
        {"amount_total": 490.0, "vat_amount": 74.75, "net_amount": None}
    )
    assert total == 490.0
    assert vat == 74.75
    assert round(net, 2) == 415.25


def test_resolve_amounts_missing_returns_none():
    assert ExpenseOCRPipeline._resolve_amounts(
        {"amount_total": None, "vat_amount": None, "net_amount": None}
    ) == (None, None, None)


# ---------- review reasons (filing gate) ----------

def _pipeline():
    return ExpenseOCRPipeline(db=None, organization_id=1, min_confidence=0.6)


def test_review_flags_low_confidence_and_missing_taxid():
    p = _pipeline()
    reasons = p._review_reasons(
        {"is_readable": True, "confidence": 0.3}, tax_id=None,
        supplier_name="ספק", total=100.0,
    )
    assert any("ביטחון" in r for r in reasons)
    assert any("ח.פ" in r for r in reasons)


def test_review_passes_when_complete():
    p = _pipeline()
    reasons = p._review_reasons(
        {"is_readable": True, "confidence": 0.95}, tax_id="520022732",
        supplier_name="שופרסל", total=104.90,
    )
    assert reasons == []


def test_review_flags_unreadable():
    p = _pipeline()
    reasons = p._review_reasons(
        {"is_readable": False, "confidence": 0.9}, tax_id="520022732",
        supplier_name="ספק", total=100.0,
    )
    assert any("קריא" in r for r in reasons)


# ---------- end-to-end via the route (mocked connector + extractor + registry) ----------

@pytest.fixture(scope="module")
def acc(client):
    reg = client.post("/api/admin/auth/register", json={
        "email": "ocrowner@example.com", "password": "secret123", "full_name": "OCR Owner",
    })
    assert reg.status_code == 201, reg.text
    return {"headers": {"Authorization": f"Bearer {reg.json()['access_token']}"},
            "org_id": reg.json()["user"]["organization_id"]}


def test_ocr_flags_unreadable_expense(client, acc, monkeypatch):
    """מסמך לא קריא -> מסומן לבדיקה (flagged), לא מתויק."""
    from cfo.database import SessionLocal
    from cfo.models import Expense
    import cfo.services.sync_engine as se
    import cfo.services.vision_extractor as ve

    r = client.post("/api/expenses", json={
        "supplier_name": "DOC", "amount": 0, "expense_date": date.today().isoformat(),
    }, headers=acc["headers"])
    eid = r.json()["data"]["id"]
    db = SessionLocal()
    try:
        e = db.query(Expense).filter(Expense.id == eid).first()
        e.source = "sumit"; e.external_id = "DOC-UNREAD"; db.commit()
    finally:
        db.close()

    class FakeConnector:
        async def get_document_pdf(self, doc_id):
            return b"%PDF-1.6 fake"

    monkeypatch.setattr(se, "get_connector_for_org",
                        lambda db, org_id, preferred_source=None: (FakeConnector(), None, "sumit"))

    async def fake_extract(content):
        return {"supplier_name": None, "supplier_tax_id": None, "amount_total": None,
                "vat_amount": None, "net_amount": None, "invoice_number": None,
                "expense_date": None, "currency": "ILS", "document_type": "unknown",
                "confidence": 0.1, "is_readable": False, "notes": "דהוי"}
    monkeypatch.setattr(ve, "extract_receipt", fake_extract)

    f = client.post(f"/api/expenses/{eid}/ocr", headers=acc["headers"])
    assert f.status_code == 200, f.text
    data = f.json()["data"]
    assert data["status"] == "flagged"
    assert data["review_reasons"]


def test_ocr_extracts_verifies_and_files(client, acc, monkeypatch):
    """מסמך קריא + ח.פ מאומת ברשם -> תיוק אוטומטי ל-SUMIT, שם רשמי מתקן OCR."""
    from cfo.database import SessionLocal
    from cfo.models import Expense
    import cfo.services.sync_engine as se
    import cfo.services.vision_extractor as ve
    import cfo.services.company_registry as cr

    r = client.post("/api/expenses", json={
        "supplier_name": "DOC2", "amount": 0, "expense_date": date.today().isoformat(),
    }, headers=acc["headers"])
    eid = r.json()["data"]["id"]
    db = SessionLocal()
    try:
        e = db.query(Expense).filter(Expense.id == eid).first()
        e.source = "sumit"; e.external_id = "DOC-OK"; db.commit()
    finally:
        db.close()

    calls = {"filed": None, "canceled": None}

    class FakeConnector:
        async def get_document_pdf(self, doc_id):
            return b"%PDF-1.6 fake"
        async def add_expense(self, request):
            calls["filed"] = {"supplier": request.supplier_name, "category": request.category,
                              "amount": float(request.amount), "vat": float(request.vat_amount or 0)}
            return {"expense_id": "SUMIT-OCR-1"}
        async def cancel_document(self, doc_id):
            calls["canceled"] = doc_id
            return {"ok": True}

    monkeypatch.setattr(se, "get_connector_for_org",
                        lambda db, org_id, preferred_source=None: (FakeConnector(), None, "sumit"))

    async def fake_extract(content):
        return {"supplier_name": "שופרסל סניף", "supplier_tax_id": "520022732",
                "amount_total": 104.90, "vat_amount": None, "net_amount": None,
                "invoice_number": "8353406", "expense_date": "2026-05-20",
                "currency": "ILS", "document_type": "receipt", "confidence": 0.95,
                "is_readable": True, "notes": None}
    monkeypatch.setattr(ve, "extract_receipt", fake_extract)

    async def fake_lookup(self, tax_id):
        return {"tax_id": "520022732", "name": "שופרסל בע\"מ", "status": "פעילה", "raw": {}}
    monkeypatch.setattr(cr.CompanyRegistry, "lookup", fake_lookup)

    f = client.post(f"/api/expenses/{eid}/ocr?auto_file=true", headers=acc["headers"])
    assert f.status_code == 200, f.text
    data = f.json()["data"]
    assert data["status"] == "filed"
    assert data["registry_confirmed"] is True
    assert data["supplier_name"] == "שופרסל בע\"מ"     # שם רשמי החליף את ה-OCR
    assert data["sumit_expense_id"] == "SUMIT-OCR-1"
    # הסכומים נגזרו נכון מהסה"כ (104.90 כולל מע"מ 18%)
    assert calls["filed"]["supplier"] == "שופרסל בע\"מ"
    assert calls["canceled"] == "DOC-OK"               # הטיוטה המקורית בוטלה
    assert round(calls["filed"]["vat"], 2) == round(104.90 - 104.90 / 1.18, 2)


# ---------- israeli_tax_rules integration: doc_kind + vat_claimable ---------- #

def _setup_ocr_expense(client, acc, external_id):
    r = client.post("/api/expenses", json={
        "supplier_name": "DOC-VAT", "amount": 0, "expense_date": date.today().isoformat(),
    }, headers=acc["headers"])
    eid = r.json()["data"]["id"]
    from cfo.database import SessionLocal
    from cfo.models import Expense

    db = SessionLocal()
    try:
        e = db.query(Expense).filter(Expense.id == eid).first()
        e.source = "sumit"; e.external_id = external_id; db.commit()
    finally:
        db.close()
    return eid


def _patch_connector_and_extract(monkeypatch, extract_payload):
    import cfo.services.sync_engine as se
    import cfo.services.vision_extractor as ve
    import cfo.services.company_registry as cr

    class FakeConnector:
        async def get_document_pdf(self, doc_id):
            return b"%PDF-1.6 fake"
        async def add_expense(self, request):
            return {"expense_id": "SUMIT-FAKE-1"}
        async def cancel_document(self, doc_id):
            return {"ok": True}

    monkeypatch.setattr(se, "get_connector_for_org",
                        lambda db, org_id, preferred_source=None: (FakeConnector(), None, "sumit"))

    async def fake_extract(content):
        return extract_payload
    monkeypatch.setattr(ve, "extract_receipt", fake_extract)

    # אין התאמה ברשם החברות — כדי שסיווג הקטגוריה יעבוד על שם הספק שחולץ מה-OCR
    # (extract_payload["supplier_name"]) ולא יוחלף בשם אמיתי ממשק חי.
    async def fake_lookup(self, tax_id):
        return None
    monkeypatch.setattr(cr.CompanyRegistry, "lookup", fake_lookup)


def test_ocr_plain_tax_invoice_full_vat_path_unchanged(client, acc, monkeypatch):
    """מסמך tax_invoice בקטגוריה עם שבר 1 (services) -> vat_claimable = כל המע\"מ, מתויק כרגיל."""
    eid = _setup_ocr_expense(client, acc, "DOC-PLAIN")
    _patch_connector_and_extract(monkeypatch, {
        "supplier_name": "מנוי SaaS בע\"מ", "supplier_tax_id": "520022732",
        "amount_total": 236.0, "vat_amount": 36.0, "net_amount": 200.0,
        "invoice_number": "INV-1", "expense_date": date.today().isoformat(),
        "currency": "ILS", "document_type": "invoice", "confidence": 0.95,
        "is_readable": True, "notes": None,
    })
    f = client.post(f"/api/expenses/{eid}/ocr?auto_file=true", headers=acc["headers"])
    assert f.status_code == 200, f.text
    data = f.json()["data"]
    assert data["status"] == "filed"
    assert data["doc_kind"] == "tax_invoice"
    assert data["vat_claimable"] == 36.0


def test_ocr_hospitality_expense_vat_claimable_zero(client, acc, monkeypatch):
    """אירוח (מסעדה) עם חשבונית מס — מוכר 0 תשומות תמיד, אך עדיין מתויק (הוכרע, לא הכרעה חסרה)."""
    eid = _setup_ocr_expense(client, acc, "DOC-HOSP")
    _patch_connector_and_extract(monkeypatch, {
        "supplier_name": "מסעדה של השף", "supplier_tax_id": "520022732",
        "amount_total": 236.0, "vat_amount": 36.0, "net_amount": 200.0,
        "invoice_number": "INV-2", "expense_date": date.today().isoformat(),
        "currency": "ILS", "document_type": "invoice", "confidence": 0.95,
        "is_readable": True, "notes": None,
    })
    f = client.post(f"/api/expenses/{eid}/ocr?auto_file=true", headers=acc["headers"])
    assert f.status_code == 200, f.text
    data = f.json()["data"]
    assert data["category"] == "hospitality"
    assert data["status"] == "filed"
    assert data["vat_claimable"] == 0.0


def test_ocr_unknown_doc_kind_goes_to_review_not_auto_filed(client, acc, monkeypatch):
    """document_type='unknown' וללא invoice_number -> doc_kind='unknown' ->
    vat_claimable=None -> תור הכרעה, לא תיוק אוטומטי (גם כשכל שאר השדות תקינים)."""
    eid = _setup_ocr_expense(client, acc, "DOC-UNKVAT")
    _patch_connector_and_extract(monkeypatch, {
        "supplier_name": "ספק כללי בע\"מ", "supplier_tax_id": "520022732",
        "amount_total": 236.0, "vat_amount": 36.0, "net_amount": 200.0,
        "invoice_number": None, "expense_date": date.today().isoformat(),
        "currency": "ILS", "document_type": "unknown", "confidence": 0.95,
        "is_readable": True, "notes": None,
    })
    f = client.post(f"/api/expenses/{eid}/ocr?auto_file=true", headers=acc["headers"])
    assert f.status_code == 200, f.text
    data = f.json()["data"]
    assert data["status"] == "flagged"
    assert data["doc_kind"] == "unknown"
    assert data["vat_claimable"] is None
    assert any("ניכוי תשומות" in r for r in data["review_reasons"])


def test_ocr_vehicle_expense_uses_single_vehicle_profile(client, fresh_org, monkeypatch):
    """רכב עם פרופיל-רכב יחיד (primarily_business=True) -> 2/3 מהמע\"מ נתבע."""
    from cfo.database import SessionLocal
    from cfo.models import VehicleProfile

    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        db.add(VehicleProfile(organization_id=org_id, label="טנדר עבודה",
                              vehicle_kind="commercial", primarily_business=True))
        db.commit()
    finally:
        db.close()

    eid = _setup_ocr_expense(client, org, "DOC-VEHICLE")
    _patch_connector_and_extract(monkeypatch, {
        "supplier_name": "סונול", "supplier_tax_id": "520022732",
        "amount_total": 118.0, "vat_amount": 18.0, "net_amount": 100.0,
        "invoice_number": "INV-3", "expense_date": date.today().isoformat(),
        "currency": "ILS", "document_type": "invoice", "confidence": 0.95,
        "is_readable": True, "notes": None,
    })
    f = client.post(f"/api/expenses/{eid}/ocr?auto_file=true", headers=org["headers"])
    assert f.status_code == 200, f.text
    data = f.json()["data"]
    assert data["category"] == "vehicle"
    assert data["status"] == "filed"
    assert round(data["vat_claimable"], 2) == round(18.0 * 2 / 3, 2)


def test_llm_ocr_disabled_by_default_api_reserved_for_chat(monkeypatch):
    """החלטת משתמש: מפתח ה-API משרת את עוזר ה-AI בלבד — OCR-LLM כבוי כברירת מחדל."""
    import asyncio
    import pytest as _pytest
    from cfo.config import settings
    from cfo.services.vision_extractor import extract_receipt, VisionExtractionError

    assert settings.ocr_llm_enabled is False, "ברירת המחדל חייבת להיות כבוי"
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    with _pytest.raises(VisionExtractionError, match="כבוי"):
        asyncio.run(extract_receipt(b"%PDF-1.4 fake"))


# ---------- source coverage: the pipeline must see every SUMIT-derived draft ----------

def _seed_expense(client, headers, *, source, external_id, total):
    """יוצר הוצאה ממתינה עם מקור/מזהה חיצוני מפורשים."""
    from cfo.database import SessionLocal
    from cfo.models import Expense

    r = client.post("/api/expenses", json={
        "supplier_name": f"SRC-{source}", "amount": 0,
        "expense_date": date.today().isoformat(),
    }, headers=headers)
    assert r.status_code in (200, 201), r.text
    eid = r.json()["data"]["id"]

    db = SessionLocal()
    try:
        e = db.query(Expense).filter(Expense.id == eid).first()
        e.source = source
        e.external_id = external_id
        e.status = "pending"
        e.total = total
        db.commit()
    finally:
        db.close()
    return eid


def test_process_pending_covers_fileexpense_source(client, monkeypatch):
    """רגרסיה: הוצאות שנקלטו ממסך תיוק ההוצאות (source='sumit_fileexpense')
    חייבות להיסרק גם הן.

    בפרוד ל-org 5 יש 41 הוצאות כאלה בסך ₪211,107.98 — היחידות עם סכומים
    אמיתיים — בעוד 156 הוצאות `source='sumit'` הן מעטפות ריקות בסכום 0.
    סינון על 'sumit' בלבד עיבד בדיוק את הקבוצה הלא נכונה.
    """
    reg = client.post("/api/admin/auth/register", json={
        "email": "srccover@example.com", "password": "secret123",
        "full_name": "Source Coverage",
    })
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    org_id = reg.json()["user"]["organization_id"]

    _seed_expense(client, headers, source="sumit",
                  external_id="EXT-EMPTY-1", total=0)
    _seed_expense(client, headers, source="sumit_fileexpense",
                  external_id="EXT-REAL-1", total=1180)
    # מקור זר — חייב להישאר מחוץ לסריקה.
    _seed_expense(client, headers, source="manual",
                  external_id="EXT-MANUAL-1", total=500)

    _patch_connector_and_extract(monkeypatch, {
        "is_readable": True, "confidence": 0.95,
        "supplier_name": "ספק בדיקה", "supplier_tax_id": "511402547",
        "total": 1180, "vat_amount": 180,
        "expense_date": date.today().isoformat(),
        "doc_kind": "tax_invoice",
    })

    from cfo.database import SessionLocal
    import asyncio

    db = SessionLocal()
    try:
        pipeline = ExpenseOCRPipeline(db, organization_id=org_id)
        summary = asyncio.run(pipeline.process_pending(delay=0))
    finally:
        db.close()

    scanned_sources = {r.get("source") for r in summary["results"]}
    assert summary["scanned"] == 2, (
        f"expected both SUMIT-derived drafts, got {summary['scanned']}"
    )
    assert scanned_sources == {"sumit", "sumit_fileexpense"}, scanned_sources


def test_process_pending_prioritises_drafts_that_carry_amounts(client, monkeypatch):
    """משמעת עלויות API: כש--limit מגביל, קודם ההוצאות עם סכום אמיתי.

    בפרוד יש 415 מעטפות ריקות (total=0) שה-getpdf מחזיר עבורן דף ריק, מול
    41 הוצאות עם סכומים. ריצה עם --limit חייבת לבזבז את התקציב על השניות.
    """
    reg = client.post("/api/admin/auth/register", json={
        "email": "ocrprio@example.com", "password": "secret123",
        "full_name": "OCR Priority",
    })
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    org_id = reg.json()["user"]["organization_id"]

    # נזרעות לפי סדר ids כך שהריקות מקדימות — בדיוק כמו בפרוד.
    empty_id = _seed_expense(client, headers, source="sumit",
                             external_id="PRIO-EMPTY", total=0)
    real_id = _seed_expense(client, headers, source="sumit_fileexpense",
                            external_id="PRIO-REAL", total=1180)
    assert empty_id < real_id

    _patch_connector_and_extract(monkeypatch, {
        "is_readable": True, "confidence": 0.95,
        "supplier_name": "ספק בדיקה", "supplier_tax_id": "511402547",
        "total": 1180, "vat_amount": 180,
        "expense_date": date.today().isoformat(),
        "doc_kind": "tax_invoice",
    })

    from cfo.database import SessionLocal
    import asyncio

    db = SessionLocal()
    try:
        pipeline = ExpenseOCRPipeline(db, organization_id=org_id)
        summary = asyncio.run(pipeline.process_pending(limit=1, delay=0))
    finally:
        db.close()

    assert summary["scanned"] == 1
    assert summary["results"][0]["expense_id"] == real_id, (
        "limit must spend the budget on the draft that carries an amount"
    )


# ---------- הגנה על נתונים שאומתו ידנית ----------

def test_unreadable_extract_never_overwrites_a_verified_amount(client, monkeypatch):
    """מסמך לא קריא לא רשאי למחוק סכום שכבר קיים.

    ל-org 5 בפרוד יש 41 הוצאות בסך ₪211,107.98 שנקלטו בקליטה ידנית מדוקדקת
    (commit e69d654). `_process_one` כותב `exp.total` בכל פעם ש-`_resolve_amounts`
    מחזיר משהו, ושער ה-`_review_reasons` חוסם *תיוק* ולא *כתיבה* — כך שחילוץ
    כושל מדף ריק היה דורס נתון מאומת.
    """
    reg = client.post("/api/admin/auth/register", json={
        "email": "ocrguard1@example.com", "password": "secret123",
        "full_name": "OCR Guard",
    })
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    org_id = reg.json()["user"]["organization_id"]

    eid = _seed_expense(client, headers, source="sumit",
                        external_id="2126074573", total=1180)

    _patch_connector_and_extract(monkeypatch, {
        "is_readable": False, "confidence": 0.1,
        "supplier_name": None, "supplier_tax_id": None,
        "amount_total": 0, "vat_amount": 0, "net_amount": 0,
    })

    from cfo.database import SessionLocal
    from cfo.models import Expense
    import asyncio

    db = SessionLocal()
    try:
        asyncio.run(ExpenseOCRPipeline(db, organization_id=org_id)
                    .process_pending(delay=0))
    finally:
        db.close()

    db = SessionLocal()
    try:
        exp = db.query(Expense).filter(Expense.id == eid).first()
        assert float(exp.total) == 1180.0, (
            f"סכום מאומת נדרס ל-{exp.total} ע\"י חילוץ לא קריא"
        )
    finally:
        db.close()


def test_low_confidence_extract_never_overwrites_a_verified_amount(client, monkeypatch):
    """גם חילוץ ש'קריא' אך בביטחון נמוך ומחזיר מספר אחר לא דורס."""
    reg = client.post("/api/admin/auth/register", json={
        "email": "ocrguard2@example.com", "password": "secret123",
        "full_name": "OCR Guard 2",
    })
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    org_id = reg.json()["user"]["organization_id"]

    eid = _seed_expense(client, headers, source="sumit",
                        external_id="2126074574", total=14697)

    _patch_connector_and_extract(monkeypatch, {
        "is_readable": True, "confidence": 0.2,
        "supplier_name": "רעש", "supplier_tax_id": None,
        "amount_total": 12, "vat_amount": 2, "net_amount": 10,
    })

    from cfo.database import SessionLocal
    from cfo.models import Expense
    import asyncio

    db = SessionLocal()
    try:
        asyncio.run(ExpenseOCRPipeline(db, organization_id=org_id)
                    .process_pending(delay=0))
    finally:
        db.close()

    db = SessionLocal()
    try:
        exp = db.query(Expense).filter(Expense.id == eid).first()
        assert float(exp.total) == 14697.0, (
            f"סכום מאומת נדרס ל-{exp.total} ע\"י חילוץ בביטחון נמוך"
        )
    finally:
        db.close()


def test_synthetic_external_id_is_not_fetched_from_sumit(client, monkeypatch):
    """41 שורות ה-`sumit_fileexpense` נושאות מזהה סינתטי (`sumit_file_<uuid>`)
    ולא מזהה מסמך של SUMIT. אין טעם לשרוף עליהן קריאת getpdf — הן שייכות
    למסלול התיוק, לא למסלול החילוץ."""
    reg = client.post("/api/admin/auth/register", json={
        "email": "ocrguard3@example.com", "password": "secret123",
        "full_name": "OCR Guard 3",
    })
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    org_id = reg.json()["user"]["organization_id"]

    _seed_expense(client, headers, source="sumit_fileexpense",
                  external_id="sumit_file_1db657bf-9c28-4a3a-9354-de76f150db0c",
                  total=2676)

    calls = []

    import cfo.services.sync_engine as se
    import cfo.services.vision_extractor as ve

    class CountingConnector:
        async def get_document_pdf(self, doc_id):
            calls.append(doc_id)
            return b"%PDF-1.6 fake"

    monkeypatch.setattr(
        se, "get_connector_for_org",
        lambda db, org_id, preferred_source=None: (CountingConnector(), None, "sumit"))

    async def fail_extract(content):  # pragma: no cover - must never run
        raise AssertionError("vision must not be called for a synthetic id")
    monkeypatch.setattr(ve, "extract_receipt", fail_extract)

    from cfo.database import SessionLocal
    import asyncio

    db = SessionLocal()
    try:
        summary = asyncio.run(ExpenseOCRPipeline(db, organization_id=org_id)
                              .process_pending(delay=0))
    finally:
        db.close()

    assert calls == [], f"getpdf נקרא על מזהה סינתטי: {calls}"
    # נחסמת כבר בשאילתה: לא נכנסת לתור, לא שורפת קריאה, ועדיין נספרת.
    assert summary["scanned"] == 0
    assert summary["not_fetchable"] == 1


def test_weak_extract_never_overwrites_verified_supplier_identity(client, monkeypatch):
    """שם הספק וה-ח.פ הם נתון מאומת בדיוק כמו הסכום.

    41 השורות של org 5 נושאות שמות אמיתיים (קיבוץ מעלה גלבוע, ספק מספוא)
    ו-29 מהן ח.פ — כולם מאותה קליטה ידנית של ה-₪211K. חילוץ חלש שכותב ח.פ
    שגוי גרוע במיוחד: הוא מגיע ל-`_lookup_registry` (קריאה חיה ל-data.gov.il),
    ואם ה-ח.פ המומצא מזוהה כחברה אמיתית — השם המאומת מוחלף בשם שגוי אך
    משכנע, וה-ח.פ זורם משם ל-PCN874.
    """
    reg = client.post("/api/admin/auth/register", json={
        "email": "ocrguard4@example.com", "password": "secret123",
        "full_name": "OCR Guard 4",
    })
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    org_id = reg.json()["user"]["organization_id"]

    eid = _seed_expense(client, headers, source="sumit_fileexpense",
                        external_id="2126074575", total=1180)

    from cfo.database import SessionLocal
    from cfo.models import Expense

    db = SessionLocal()
    try:
        e = db.query(Expense).filter(Expense.id == eid).first()
        e.supplier_name = "קיבוץ מעלה גלבוע"
        e.supplier_tax_id = "511402547"
        db.commit()
    finally:
        db.close()

    _patch_connector_and_extract(monkeypatch, {
        "is_readable": True, "confidence": 0.2,
        "supplier_name": "רעש", "supplier_tax_id": "999999999",
        "amount_total": 12, "vat_amount": 2, "net_amount": 10,
    })

    import asyncio

    db = SessionLocal()
    try:
        asyncio.run(ExpenseOCRPipeline(db, organization_id=org_id)
                    .process_pending(delay=0))
    finally:
        db.close()

    db = SessionLocal()
    try:
        exp = db.query(Expense).filter(Expense.id == eid).first()
        assert exp.supplier_name == "קיבוץ מעלה גלבוע", exp.supplier_name
        assert exp.supplier_tax_id == "511402547", exp.supplier_tax_id
        assert float(exp.total) == 1180.0, exp.total
    finally:
        db.close()


def test_registry_is_not_called_for_a_row_that_cannot_be_overwritten(monkeypatch,
                                                                     client):
    """אם ההחלטה היא לא לדרוס, אין סיבה לשרוף קריאה חיה לרשם החברות."""
    reg = client.post("/api/admin/auth/register", json={
        "email": "ocrguard5@example.com", "password": "secret123",
        "full_name": "OCR Guard 5",
    })
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    org_id = reg.json()["user"]["organization_id"]

    eid = _seed_expense(client, headers, source="sumit",
                        external_id="2126074576", total=5000)

    from cfo.database import SessionLocal
    from cfo.models import Expense

    db = SessionLocal()
    try:
        e = db.query(Expense).filter(Expense.id == eid).first()
        e.supplier_name = "ספק מאומת"
        e.supplier_tax_id = "511402547"
        db.commit()
    finally:
        db.close()

    lookups = []
    import cfo.services.company_registry as cr
    import cfo.services.sync_engine as se
    import cfo.services.vision_extractor as ve

    class FakeConnector:
        async def get_document_pdf(self, doc_id):
            return b"%PDF-1.6 fake"

    monkeypatch.setattr(
        se, "get_connector_for_org",
        lambda db, org_id, preferred_source=None: (FakeConnector(), None, "sumit"))

    async def fake_extract(content):
        return {"is_readable": False, "confidence": 0.05,
                "supplier_name": "רעש", "supplier_tax_id": "999999999",
                "amount_total": 7, "vat_amount": 1, "net_amount": 6}
    monkeypatch.setattr(ve, "extract_receipt", fake_extract)

    async def counting_lookup(self, tax_id):
        lookups.append(tax_id)
        return None
    monkeypatch.setattr(cr.CompanyRegistry, "lookup", counting_lookup)

    import asyncio

    db = SessionLocal()
    try:
        asyncio.run(ExpenseOCRPipeline(db, organization_id=org_id)
                    .process_pending(delay=0))
    finally:
        db.close()

    assert lookups == [], f"רשם החברות נקרא מיותר: {lookups}"


def test_summary_reports_not_fetchable_rows(client, monkeypatch):
    """honest-null: ריצה שקיצרה 40 שורות לא רשאית להיראות כריצה נקייה."""
    reg = client.post("/api/admin/auth/register", json={
        "email": "ocrguard6@example.com", "password": "secret123",
        "full_name": "OCR Guard 6",
    })
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    org_id = reg.json()["user"]["organization_id"]

    _seed_expense(client, headers, source="sumit_fileexpense",
                  external_id="sumit_file_aaaa", total=100)
    _seed_expense(client, headers, source="sumit_fileexpense",
                  external_id="sumit_file_bbbb", total=200)

    _patch_connector_and_extract(monkeypatch, {
        "is_readable": True, "confidence": 0.9,
        "supplier_name": "ספק", "supplier_tax_id": "511402547",
        "amount_total": 118, "vat_amount": 18, "net_amount": 100,
    })

    from cfo.database import SessionLocal
    import asyncio

    db = SessionLocal()
    try:
        summary = asyncio.run(ExpenseOCRPipeline(db, organization_id=org_id)
                              .process_pending(delay=0))
    finally:
        db.close()

    # מזהה סינתטי נחסם כבר בשאילתה, כדי ש--limit לא יתבזבז עליו — אבל
    # הספירה נשמרת בסיכום כדי שהשורות לא ייעלמו מהדיווח.
    assert summary["scanned"] == 0
    assert summary["not_fetchable"] == 2


def test_single_row_route_also_refuses_a_synthetic_id(client, monkeypatch):
    """`process_expense` (מאחורי POST /expenses/{id}/ocr) אינו עובר בשאילתה
    של `process_pending`, ולכן השער חייב לשבת גם בתוך `_process_one`."""
    reg = client.post("/api/admin/auth/register", json={
        "email": "ocrguard7@example.com", "password": "secret123",
        "full_name": "OCR Guard 7",
    })
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    org_id = reg.json()["user"]["organization_id"]

    eid = _seed_expense(client, headers, source="sumit_fileexpense",
                        external_id="sumit_file_cccc", total=900)

    calls = []
    import cfo.services.sync_engine as se

    class CountingConnector:
        async def get_document_pdf(self, doc_id):
            calls.append(doc_id)
            return b"%PDF-1.6 fake"

    monkeypatch.setattr(
        se, "get_connector_for_org",
        lambda db, org_id, preferred_source=None: (CountingConnector(), None, "sumit"))

    from cfo.database import SessionLocal
    import asyncio

    db = SessionLocal()
    try:
        res = asyncio.run(ExpenseOCRPipeline(db, organization_id=org_id)
                          .process_expense(eid))
    finally:
        db.close()

    assert calls == [], f"getpdf נקרא במסלול הבודד: {calls}"
    assert res["status"] == "not_fetchable"
