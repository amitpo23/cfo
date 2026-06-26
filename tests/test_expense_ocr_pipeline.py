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
