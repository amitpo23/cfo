"""בדיקות: דוח עמלות אמיתי + דשבורד מנהלים מאוחד (8 פאנלים, מבודד מכשלים)."""
from datetime import date
import pytest


@pytest.fixture(scope="module")
def feebooks(client):
    from cfo.database import SessionLocal
    from cfo.models import Transaction, TransactionType, Account, AccountType

    reg = client.post("/api/admin/auth/register", json={
        "email": "feeowner@example.com", "password": "secret123", "full_name": "Fee Owner",
    })
    assert reg.status_code == 201, reg.text
    payload = reg.json()
    headers = {"Authorization": f"Bearer {payload['access_token']}"}
    org_id = payload["user"]["organization_id"]

    db = SessionLocal()
    try:
        acct = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=10000)
        db.add(acct); db.flush()
        m1 = date.today().replace(day=1)
        db.add_all([
            Transaction(organization_id=org_id, account_id=acct.id, transaction_type=TransactionType.INCOME,
                        amount=100000, description="מכירות", category="sales", transaction_date=m1),
            Transaction(organization_id=org_id, account_id=acct.id, transaction_type=TransactionType.EXPENSE,
                        amount=1200, description="עמלת ניהול חשבון", category="bank_fees", transaction_date=m1),
            Transaction(organization_id=org_id, account_id=acct.id, transaction_type=TransactionType.EXPENSE,
                        amount=800, description="עמלת סליקת אשראי", category="clearing", transaction_date=m1),
            Transaction(organization_id=org_id, account_id=acct.id, transaction_type=TransactionType.EXPENSE,
                        amount=500, description="ריבית הלוואה", category="loan_interest", transaction_date=m1),
            Transaction(organization_id=org_id, account_id=acct.id, transaction_type=TransactionType.EXPENSE,
                        amount=20000, description="חומרי גלם", category="materials", transaction_date=m1),
        ])
        db.commit()
        return {"org_id": org_id, "headers": headers}
    finally:
        db.close()


def test_fees_report_classifies_real(client, feebooks):
    r = client.get("/api/dashboard/fees", headers=feebooks["headers"])
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    # 1200 + 800 + 500 = 2500 עמלות (לא כולל חומרי גלם)
    assert d["total_fees"] == 2500
    types = {t["type"]: t["amount"] for t in d["by_type"]}
    assert types.get("bank") == 1200
    assert types.get("credit_card") == 800
    assert types.get("loan") == 500


def test_executive_dashboard_has_all_panels(client, feebooks):
    r = client.get("/api/dashboard/executive", headers=feebooks["headers"])
    assert r.status_code == 200, r.text
    panels = r.json()["data"]["panels"]
    expected = {
        "profit_loss", "bank_reconciliation", "expense_overruns",
        "budget_vs_actual", "profitability", "profitability_improvement",
        "fees", "ai_opportunities",
    }
    assert expected.issubset(panels.keys())
    # כל פאנל מחזיר ok=True (מבודד מכשלים, לא 500)
    failed = [k for k, v in panels.items() if not v.get("ok")]
    assert not failed, failed
    # נתון אמיתי זולג דרך הפאנל
    assert panels["profit_loss"]["data"]["total_revenue"] == 100000
    assert panels["fees"]["data"]["total_fees"] == 2500


def test_dashboard_requires_auth(client):
    assert client.get("/api/dashboard/executive").status_code == 403
    assert client.get("/api/dashboard/fees").status_code == 403


def test_executive_dashboard_empty_org_no_crash(client):
    reg = client.post("/api/admin/auth/register", json={
        "email": "emptydash@example.com", "password": "secret123", "full_name": "Empty",
    })
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    r = client.get("/api/dashboard/executive", headers=headers)
    assert r.status_code == 200, r.text
    panels = r.json()["data"]["panels"]
    failed = [k for k, v in panels.items() if not v.get("ok")]
    assert not failed, failed
