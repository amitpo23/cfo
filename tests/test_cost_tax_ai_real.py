"""בדיקות: cost analysis, מע"מ, ותובנות AI — על נתונים אמיתיים, ללא קריסות."""
from datetime import date, timedelta

import pytest


@pytest.fixture(scope="module")
def books(client):
    """ארגון ייעודי עם הכנסות, הוצאות מסווגות, וחשבונית באיחור."""
    from cfo.database import SessionLocal
    from cfo.models import (
        Transaction, TransactionType, Account, AccountType,
        Contact, ContactType, Invoice, InvoiceStatus,
    )

    reg = client.post("/api/admin/auth/register", json={
        "email": "taxowner@example.com", "password": "secret123", "full_name": "Tax Owner",
    })
    assert reg.status_code == 201, reg.text
    payload = reg.json()
    headers = {"Authorization": f"Bearer {payload['access_token']}"}
    org_id = payload["user"]["organization_id"]

    db = SessionLocal()
    try:
        acct = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=50000)
        db.add(acct); db.flush()
        today = date.today()
        m1 = today.replace(day=1)
        db.add_all([
            Transaction(organization_id=org_id, account_id=acct.id, transaction_type=TransactionType.INCOME,
                        amount=200000, description="מכירות", category="sales", transaction_date=m1),
            Transaction(organization_id=org_id, account_id=acct.id, transaction_type=TransactionType.EXPENSE,
                        amount=80000, description="חומרי גלם", category="materials", transaction_date=m1),
            Transaction(organization_id=org_id, account_id=acct.id, transaction_type=TransactionType.EXPENSE,
                        amount=20000, description="שכירות", category="rent", transaction_date=m1),
        ])
        cust = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="לקוח חייב")
        db.add(cust); db.flush()
        db.add(Invoice(organization_id=org_id, contact_id=cust.id, invoice_number="OD-1",
                       issue_date=today - timedelta(days=130), due_date=today - timedelta(days=100),
                       total=70000, paid_amount=0, balance=70000, status=InvoiceStatus.OVERDUE))
        db.commit()
        return {"org_id": org_id, "headers": headers}
    finally:
        db.close()


# ---------- Cost analysis ----------

def test_cost_breakdown_real(client, books):
    r = client.get("/api/financial/costs/breakdown", headers=books["headers"])
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["total_costs"] == 100000        # 80000 + 20000
    assert data["direct_costs"] == 80000        # materials
    assert data["indirect_costs"] == 20000      # rent


def test_cogs_real(client, books):
    r = client.get("/api/financial/costs/cogs", headers=books["headers"])
    assert r.status_code == 200, r.text


# ---------- VAT (מע"מ) ----------

def test_vat_report_real(client, books):
    """דוח המע"מ נגזר משדות מע"מ מפורשים במסמכי ה-ledger (לא אומדן 18% מ-Transaction).

    מקור אמת אחד עם compute_vat_position. זורעים חשבונית והוצאה עם מע"מ מפורש
    לחודש הנוכחי ומאמתים את הסכומים מהשדות האמיתיים.
    """
    from cfo.database import SessionLocal
    from cfo.models import Contact, ContactType, Invoice, InvoiceStatus, Expense

    today = date.today()
    org_id = books["org_id"]
    db = SessionLocal()
    try:
        cust = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="לקוח מעמ")
        db.add(cust); db.flush()
        # חשבונית: נטו 200000 + מע"מ 36000
        db.add(Invoice(organization_id=org_id, contact_id=cust.id, invoice_number="VAT-1",
                       issue_date=today, due_date=today,
                       subtotal=200000, tax=36000, total=236000,
                       paid_amount=0, balance=236000, status=InvoiceStatus.SENT))
        # הוצאה: נטו 100000 + מע"מ 18000
        db.add(Expense(organization_id=org_id, supplier_name="ספק מעמ",
                       amount=100000, vat_amount=18000, total=118000,
                       expense_date=today, status="filed"))
        db.commit()
    finally:
        db.close()

    r = client.post("/api/financial/tax/vat-report", json={
        "period_start": today.replace(day=1).isoformat(),
        "period_end": today.isoformat(),
    }, headers=books["headers"])
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert round(data["output_vat"]) == 36000      # מע"מ עסקאות אמיתי מהחשבונית
    assert round(data["total_input_vat"]) == 18000  # מע"מ תשומות אמיתי מההוצאה


def test_tax_routes_no_crash(client, books):
    today = date.today()
    period = today.strftime("%Y-%m")
    crashed = []
    checks = [
        ("get", f"/api/financial/tax/advance?period={period}"),
        ("get", f"/api/financial/tax/withholding?period={period}"),
        ("get", "/api/financial/tax/calendar"),
        ("get", "/api/financial/tax/planning"),
        ("get", "/api/financial/costs/break-even"),
        ("get", "/api/financial/costs/profitability?by=customer"),
    ]
    for _m, p in checks:
        try:
            resp = client.get(p, headers=books["headers"])
            if resp.status_code == 500:
                crashed.append((p, resp.text[:120]))
        except Exception as exc:
            crashed.append((p, f"{type(exc).__name__}: {exc}"))
    assert not crashed, crashed


# ---------- AI insights ----------

def test_ai_insights_real(client, books):
    r = client.get("/api/financial/ai/insights", headers=books["headers"])
    assert r.status_code == 200, r.text
    insights = r.json()["data"]
    # החשבונית באיחור 130 יום אמורה לייצר תובנת סיכון אשראי אמיתית
    assert any("INS-AR" in (i.get("insight_id") or "") for i in insights)


def test_all_financial_get_routes_no_crash(client, books):
    """smoke גורף: כל GET תחת /api/financial לא מחזיר 500 על ארגון עם נתונים."""
    from cfo.api import app
    h = books["headers"]
    placeholders = {"metric": "revenue", "product_id": "P1", "customer_id": "1"}
    crashed = []
    seen = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if "/financial/" not in path or "GET" not in methods:
            continue
        url = path
        for key, val in placeholders.items():
            url = url.replace("{" + key + "}", val)
        if "{" in url or url in seen:
            continue
        seen.add(url)
        try:
            r = client.get(url, headers=h)
            if r.status_code == 500:
                crashed.append((url, r.text[:120]))
        except Exception as exc:
            crashed.append((url, f"{type(exc).__name__}: {exc}"))
    assert not crashed, crashed
