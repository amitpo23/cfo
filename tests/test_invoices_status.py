"""בדיקת דוח סטטוס חשבוניות אמיתי (שולם/חלקי/לא שולם)."""
from datetime import date
import pytest


@pytest.fixture(scope="module")
def seeded(client):
    from cfo.database import SessionLocal
    from cfo.models import Contact, ContactType, Invoice, InvoiceStatus
    reg = client.post("/api/admin/auth/register", json={
        "email": "invstatus@example.com", "password": "secret123", "full_name": "Inv",
    })
    h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    org_id = reg.json()["user"]["organization_id"]
    db = SessionLocal()
    try:
        cust = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="לקוח")
        db.add(cust); db.flush()
        db.add_all([
            # שולם: balance 0
            Invoice(organization_id=org_id, contact_id=cust.id, invoice_number="P1",
                    issue_date=date.today(), total=1000, paid_amount=1000, balance=0, status=InvoiceStatus.PAID),
            # חלקי
            Invoice(organization_id=org_id, contact_id=cust.id, invoice_number="PP1",
                    issue_date=date.today(), total=2000, paid_amount=500, balance=1500, status=InvoiceStatus.PARTIALLY_PAID),
            # לא שולם
            Invoice(organization_id=org_id, contact_id=cust.id, invoice_number="U1",
                    issue_date=date.today(), total=3000, paid_amount=0, balance=3000, status=InvoiceStatus.SENT),
        ])
        db.commit()
        return {"headers": h}
    finally:
        db.close()


def test_invoices_status_report(client, seeded):
    r = client.get("/api/financial/ar/invoices-status", headers=seeded["headers"])
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["invoice_count"] == 3
    assert d["by_status"]["paid"]["count"] == 1
    assert d["by_status"]["partial"]["count"] == 1
    assert d["by_status"]["unpaid"]["count"] == 1
    assert d["total_billed"] == 6000          # 1000+2000+3000
    assert d["total_outstanding"] == 4500     # 1500 + 3000
    assert d["total_collected"] == 1500       # 1000 + 500 + 0
