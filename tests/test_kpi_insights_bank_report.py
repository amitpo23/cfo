"""בדיקות: KPI אמיתי, הערכת סיכוני AI אמיתית, ודוח מצב לבנק — על נתונים אמיתיים."""
from datetime import date, timedelta

import pytest


@pytest.fixture(scope="module")
def seeded_books(client):
    """משתמש/ארגון ייעודי ומבודד עם הכנסות, הוצאות, חשבונית פתוחה וחוב ספק."""
    from cfo.database import SessionLocal
    from cfo.models import (
        Transaction, TransactionType, Account, AccountType,
        Contact, ContactType, Invoice, InvoiceStatus, Bill, BillStatus,
    )

    reg = client.post("/api/admin/auth/register", json={
        "email": "kpiowner@example.com", "password": "secret123", "full_name": "KPI Owner",
    })
    assert reg.status_code == 201, reg.text
    payload = reg.json()
    headers = {"Authorization": f"Bearer {payload['access_token']}"}
    org_id = payload["user"]["organization_id"]
    db = SessionLocal()
    try:
        acct = Account(organization_id=org_id, name="עו\"ש", account_type=AccountType.BANK, balance=80000)
        db.add(acct)
        db.flush()

        today = date.today()
        # הכנסה והוצאה בחודש הנוכחי
        db.add_all([
            Transaction(organization_id=org_id, account_id=acct.id,
                        transaction_type=TransactionType.INCOME, amount=100000,
                        description="מכירות", category="sales",
                        transaction_date=today.replace(day=1)),
            Transaction(organization_id=org_id, account_id=acct.id,
                        transaction_type=TransactionType.EXPENSE, amount=40000,
                        description="ספקים", category="materials",
                        transaction_date=today.replace(day=2)),
        ])
        cust = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="לקוח KPI")
        vend = Contact(organization_id=org_id, contact_type=ContactType.VENDOR, name="ספק KPI")
        db.add_all([cust, vend])
        db.flush()
        db.add_all([
            Invoice(organization_id=org_id, contact_id=cust.id, invoice_number="INVK-1",
                    issue_date=today - timedelta(days=20), due_date=today + timedelta(days=10),
                    total=30000, paid_amount=0, balance=30000, status=InvoiceStatus.SENT),
            Bill(organization_id=org_id, vendor_id=vend.id, bill_number="BILLK-1",
                 issue_date=today - timedelta(days=10), due_date=today + timedelta(days=5),
                 total=15000, paid_amount=0, balance=15000, status=BillStatus.APPROVED),
        ])
        db.commit()
        return {"org_id": org_id, "headers": headers}
    finally:
        db.close()


def test_kpis_use_real_data(client, seeded_books):
    r = client.get("/api/financial/kpis", headers=seeded_books["headers"])
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "kpis" in data and len(data["kpis"]) > 0


def test_executive_summary_real_snapshot(client, seeded_books):
    r = client.get("/api/financial/kpis/executive-summary", headers=seeded_books["headers"])
    assert r.status_code == 200, r.text
    snap = r.json()["data"]["financial_snapshot"]
    # הכנסות החודש = 100000 (מהתנועה האמיתית), לא ערך אקראי
    assert snap["revenue_mtd"] == 100000
    assert snap["receivables"] == 30000
    assert snap["payables"] == 15000


def test_executive_summary_has_no_fabricated_comparisons(client, seeded_books):
    """comparison_to_budget/comparison_to_previous used to hardcode
    budget=500000/400000 and revenue/expenses/profit_change=8.5/5.2/12.3
    on every single call, regardless of any real budget or prior-period
    data. Both are honest-null now, not a "plausible" number computed over
    the frozen Account/Transaction pipeline (the same data source behind
    the documented P0 finding) -- converting an obviously-fake number into
    a plausible-but-still-unreliable one would be worse, not better."""
    r = client.get("/api/financial/kpis/executive-summary", headers=seeded_books["headers"])
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    assert data["comparison_to_budget"]["available"] is False
    assert data["comparison_to_previous"]["available"] is False
    # The old fabricated constants must not appear anywhere in the response.
    assert "500000" not in str(data["comparison_to_budget"])
    assert data["comparison_to_previous"]["revenue_change"] != 8.5


def test_ai_risks_no_crash_real(client, seeded_books):
    r = client.get("/api/financial/ai/risks", headers=seeded_books["headers"])
    assert r.status_code == 200, r.text
    assert isinstance(r.json()["data"], list)


def test_bank_status_report_real(client, seeded_books):
    r = client.get("/api/reports/bank-status", headers=seeded_books["headers"])
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["profit_loss"]["total_revenue"] == 100000
    assert data["receivables"]["total"] == 30000
    assert data["payables"]["total"] == 15000
    assert "current_ratio" in data["balance_sheet"]


def test_bank_status_export_xlsx(client, seeded_books):
    r = client.get("/api/reports/bank-status/export", headers=seeded_books["headers"])
    assert r.status_code == 200, r.text
    assert "spreadsheet" in r.headers["content-type"]
    assert r.content[:2] == b"PK"  # חתימת קובץ xlsx (zip)


def test_kpis_require_auth(client):
    assert client.get("/api/financial/kpis").status_code == 403
    assert client.get("/api/reports/bank-status").status_code == 403


def test_existing_reports_routes_no_crash(client, seeded_books):
    """ראוטר הדוחות תוקן (org_id מ-User), כל ה-routes לא קורסים."""
    h = seeded_books["headers"]
    crashed = []
    for p in [
        "/api/reports/profit-loss", "/api/reports/profit-loss/export",
        "/api/reports/balance-sheet", "/api/reports/balance-sheet/export",
        "/api/reports/cash-flow-projection", "/api/reports/summary",
        "/api/reports/available",
    ]:
        try:
            r = client.get(p, headers=h)
            if r.status_code == 500:
                crashed.append((p, r.text[:120]))
        except Exception as exc:
            crashed.append((p, f"{type(exc).__name__}: {exc}"))
    assert not crashed, crashed
