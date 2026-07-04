"""בדיקות: תיוק הוצאות DB-backed, רב-ארגוני, מול SUMIT (mock)."""
from datetime import date
import pytest


@pytest.fixture(scope="module")
def acc(client):
    reg = client.post("/api/admin/auth/register", json={
        "email": "expowner@example.com", "password": "secret123", "full_name": "Exp Owner",
    })
    assert reg.status_code == 201, reg.text
    return {"headers": {"Authorization": f"Bearer {reg.json()['access_token']}"},
            "org_id": reg.json()["user"]["organization_id"]}


def test_expenses_require_auth(client):
    assert client.get("/api/expenses").status_code == 403


def test_create_and_list_expense(client, acc):
    r = client.post("/api/expenses", json={
        "supplier_name": "ספק בדיקה",
        "amount": 1000,
        "vat_amount": 180,
        "expense_date": date.today().isoformat(),
        "category": "materials",
        "invoice_number": "EXP-1",
    }, headers=acc["headers"])
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["status"] == "pending"
    assert data["total"] == 1180  # 1000 + 180

    lst = client.get("/api/expenses", headers=acc["headers"]).json()["data"]
    assert any(e["invoice_number"] == "EXP-1" for e in lst)


def test_expense_is_org_scoped(client, acc):
    reg2 = client.post("/api/admin/auth/register", json={
        "email": "expother@example.com", "password": "secret123", "full_name": "Other",
    })
    other = {"Authorization": f"Bearer {reg2.json()['access_token']}"}
    lst = client.get("/api/expenses", headers=other).json()["data"]
    assert lst == []  # לא רואה את ההוצאות של acc


def test_file_to_sumit_without_connection(client, acc):
    # יצירת הוצאה
    r = client.post("/api/expenses", json={
        "supplier_name": "ספק", "amount": 500, "expense_date": date.today().isoformat(),
    }, headers=acc["headers"])
    eid = r.json()["data"]["id"]
    # ללא חיבור SUMIT -> 400 ברור, לא 500
    f = client.post(f"/api/expenses/{eid}/file", headers=acc["headers"])
    assert f.status_code == 400, f.text


def test_file_to_sumit_with_stubbed_connector(client, acc, monkeypatch):
    """תיוק מוצלח עם connector מזויף — מאמת שהמצב נשמר ל-DB."""
    import cfo.services.expense_filing_service as efs

    class FakeConnector:
        async def add_expense(self, request):
            return {"expense_id": "SUMIT-999"}

    def fake_get_connector(db, org_id, preferred_source=None):
        return FakeConnector(), None, "sumit"

    # מזריקים connector מזויף במקום get_connector_for_org
    import cfo.services.sync_engine as se
    monkeypatch.setattr(se, "get_connector_for_org", fake_get_connector)

    r = client.post("/api/expenses", json={
        "supplier_name": "ספק לתיוק", "amount": 700, "vat_amount": 126,
        "expense_date": date.today().isoformat(),
    }, headers=acc["headers"])
    eid = r.json()["data"]["id"]

    f = client.post(f"/api/expenses/{eid}/file", headers=acc["headers"])
    assert f.status_code == 200, f.text
    data = f.json()["data"]
    assert data["status"] == "filed"
    assert data["sumit_expense_id"] == "SUMIT-999"

    # נשמר ל-DB: רשימת filed כוללת אותה
    filed = client.get("/api/expenses?status=filed", headers=acc["headers"]).json()["data"]
    assert any(e["id"] == eid for e in filed)


def test_file_sumit_draft_replaces_with_category(client, acc, monkeypatch):
    """טיוטת SUMIT: נוצרת הוצאה חדשה עם הקטגוריה שלנו, והטיוטה המקורית מבוטלת (ללא כפילות)."""
    from cfo.database import SessionLocal
    from cfo.models import Expense
    from datetime import date
    import cfo.services.sync_engine as se

    # יצירת הוצאה ואז הפיכתה לטיוטת SUMIT עם קטגוריה
    r = client.post("/api/expenses", json={
        "supplier_name": "רואה חשבון לוי", "amount": 900, "vat_amount": 162,
        "expense_date": date.today().isoformat(),
    }, headers=acc["headers"])
    eid = r.json()["data"]["id"]

    db = SessionLocal()
    try:
        exp = db.query(Expense).filter(Expense.id == eid).first()
        exp.source = "sumit"
        exp.external_id = "DOC-555"
        exp.category = "professional"
        db.commit()
    finally:
        db.close()

    calls = {"created_category": None, "canceled": None}

    class FakeConnector:
        async def add_expense(self, request):
            calls["created_category"] = request.category
            return {"expense_id": "NEW-777"}
        async def cancel_document(self, document_id):
            calls["canceled"] = document_id
            return {"ok": True}

    monkeypatch.setattr(se, "get_connector_for_org",
                        lambda db, org_id, preferred_source=None: (FakeConnector(), None, "sumit"))

    f = client.post(f"/api/expenses/{eid}/file", headers=acc["headers"])
    assert f.status_code == 200, f.text
    data = f.json()["data"]
    assert data["status"] == "filed"
    assert data["sumit_expense_id"] == "NEW-777"       # מסמך חדש עם הקטגוריה
    assert calls["created_category"] == "professional"  # הסיווג נכנס ל-SUMIT
    assert calls["canceled"] == "DOC-555"              # הטיוטה המקורית בוטלה


def test_update_expense_amount_and_category(client, acc):
    from datetime import date
    r = client.post("/api/expenses", json={
        "supplier_name": "ספק לעדכון", "amount": 100,
        "expense_date": date.today().isoformat(),
    }, headers=acc["headers"])
    eid = r.json()["data"]["id"]
    u = client.patch(f"/api/expenses/{eid}", json={"amount": 250, "category": "rent"}, headers=acc["headers"])
    assert u.status_code == 200, u.text
    data = u.json()["data"]
    assert data["amount"] == 250
    assert data["category"] == "rent"
    assert data["total"] == 250  # total עודכן (אין מע"מ)


def test_update_expense_sets_deduction_percent(client, acc):
    """Expense.deduction_percent existed already (annual_report_service
    honors it for 1301) but was never reachable via any API/UI path --
    ExpenseUpdateRequest didn't even include the field. Root-cause fix."""
    r = client.post("/api/expenses", json={
        "supplier_name": "ספק ניכוי", "amount": 1000,
        "expense_date": date.today().isoformat(),
    }, headers=acc["headers"])
    eid = r.json()["data"]["id"]

    u = client.patch(f"/api/expenses/{eid}", json={"deduction_percent": 45}, headers=acc["headers"])
    assert u.status_code == 200, u.text
    assert u.json()["data"]["deduction_percent"] == 45


def test_update_expense_rejects_out_of_range_deduction_percent(client, acc):
    r = client.post("/api/expenses", json={
        "supplier_name": "ספק ניכוי 2", "amount": 1000,
        "expense_date": date.today().isoformat(),
    }, headers=acc["headers"])
    eid = r.json()["data"]["id"]

    # Pydantic Field(ge=0, le=100) validation -> FastAPI's standard 422.
    u = client.patch(f"/api/expenses/{eid}", json={"deduction_percent": 150}, headers=acc["headers"])
    assert u.status_code == 422, u.text

    u2 = client.patch(f"/api/expenses/{eid}", json={"deduction_percent": -5}, headers=acc["headers"])
    assert u2.status_code == 422, u2.text


def test_update_expense_deduction_percent_omitted_stays_null(client, acc):
    """Regression: not passing deduction_percent must not reset it."""
    r = client.post("/api/expenses", json={
        "supplier_name": "ספק ללא ניכוי", "amount": 500,
        "expense_date": date.today().isoformat(),
    }, headers=acc["headers"])
    eid = r.json()["data"]["id"]

    u = client.patch(f"/api/expenses/{eid}", json={"amount": 600}, headers=acc["headers"])
    assert u.status_code == 200, u.text
    assert u.json()["data"]["deduction_percent"] is None


def test_pcn874_readiness(client, acc):
    """דוח מוכנות PCN874 — מסמן הוצאות מתויקות ללא ח.פ/מע"מ."""
    from datetime import date
    from cfo.database import SessionLocal
    from cfo.models import Expense
    # ניצור 3 הוצאות מתויקות: אחת מלאה, אחת בלי ח.פ, אחת בלי מע"מ
    org_id = None
    # הוצאה דרך ה-API כדי לקבל org, ואז נעדכן ל-filed ב-DB
    r = client.post("/api/expenses", json={"supplier_name":"A","amount":1000,"vat_amount":180,"expense_date":date.today().isoformat()}, headers=acc["headers"])
    base_id = r.json()["data"]["id"]
    db = SessionLocal()
    try:
        e = db.query(Expense).filter(Expense.id==base_id).first()
        org_id = e.organization_id
        e.status="filed"; e.supplier_tax_id="511402547"; e.vat_amount=180
        ready = Expense(organization_id=org_id, supplier_name="B", amount=500, vat_amount=90, total=590,
                        expense_date=date.today(), status="filed", supplier_tax_id="123456782")
        no_tax = Expense(organization_id=org_id, supplier_name="C", amount=300, vat_amount=54, total=354,
                         expense_date=date.today(), status="filed")  # אין ח.פ
        db.add_all([ready, no_tax]); db.commit()
    finally:
        db.close()

    res = client.get("/api/expenses/pcn874-readiness", headers=acc["headers"]).json()["data"]
    assert res["pcn_ready"] >= 2          # A + B מוכנים (ח.פ + מע"מ)
    assert res["missing_tax_id_count"] >= 1  # C חסר ח.פ
    assert res["totals"]["vat"] >= 324    # 180+90+54
