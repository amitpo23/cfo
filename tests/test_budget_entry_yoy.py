"""בדיקות: הזנת תקציב גורפת, ייבוא Excel, ודוח השוואה לשנה קודמת."""
import io
from datetime import date

import pytest


@pytest.fixture(scope="module")
def acc(client):
    reg = client.post("/api/admin/auth/register", json={
        "email": "yoyowner@example.com", "password": "secret123", "full_name": "YoY Owner",
    })
    assert reg.status_code == 201, reg.text
    return {"headers": {"Authorization": f"Bearer {reg.json()['access_token']}"},
            "org_id": reg.json()["user"]["organization_id"]}


def test_budget_bulk_save(client, acc):
    today = date.today()
    r = client.post("/api/financial/budget/bulk", json={"items": [
        {"category": "materials", "year": today.year, "month": today.month, "amount": 30000},
        {"category": "rent", "year": today.year, "month": today.month, "amount": 12000},
    ]}, headers=acc["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["data"]["saved"] == 2

    va = client.get(f"/api/financial/budget/vs-actual?year={today.year}&month={today.month}",
                    headers=acc["headers"]).json()["data"]
    total = sum(c["budget_amount"] for c in va["categories"])
    assert total == 42000


def test_budget_template_download(client, acc):
    r = client.get("/api/financial/budget/template", headers=acc["headers"])
    assert r.status_code == 200
    assert r.content[:2] == b"PK"  # xlsx


def test_budget_excel_import_roundtrip(client, acc):
    import openpyxl
    today = date.today()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["קטגוריה", "שנה", "חודש", "סכום"])
    ws.append(["marketing", today.year, today.month, 8000])
    ws.append(["utilities", today.year, today.month, 3000])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    r = client.post(
        "/api/financial/budget/import",
        files={"file": ("budget.xlsx", buf.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=acc["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["saved"] == 2


def test_year_comparison_real(client, acc):
    from cfo.database import SessionLocal
    from cfo.models import Transaction, TransactionType, Account, AccountType

    org_id = acc["org_id"]
    this_year = date.today().year
    db = SessionLocal()
    try:
        a = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(a); db.flush()
        db.add_all([
            Transaction(organization_id=org_id, account_id=a.id, transaction_type=TransactionType.INCOME,
                        amount=100000, category="sales", transaction_date=date(this_year, 2, 1)),
            Transaction(organization_id=org_id, account_id=a.id, transaction_type=TransactionType.INCOME,
                        amount=60000, category="sales", transaction_date=date(this_year - 1, 2, 1)),
        ])
        db.commit()
    finally:
        db.close()

    r = client.get(f"/api/reports/year-comparison?year={this_year}", headers=acc["headers"])
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["current_year"] == this_year
    assert d["previous_year"] == this_year - 1
    rev = d["metrics"]["revenue"]
    assert rev["current"] == 100000
    assert rev["previous"] == 60000
    assert round(rev["change_pct"]) == round((100000 - 60000) / 60000 * 100)
    assert len(d["monthly"]) == 12


def test_budget_entry_requires_auth(client):
    assert client.post("/api/financial/budget/bulk", json={"items": []}).status_code == 403
    assert client.get("/api/reports/year-comparison").status_code == 403
