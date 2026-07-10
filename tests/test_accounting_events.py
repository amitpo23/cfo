from datetime import date

from cfo.database import SessionLocal
from cfo.models import BankTransaction, Bill, Invoice


def test_accounting_events_are_derived_and_org_scoped(client, fresh_org):
    target = fresh_org()
    other = fresh_org()
    db = SessionLocal()
    try:
        db.add(Invoice(
            organization_id=target["org_id"],
            source="test",
            invoice_number="INV-EVENT",
            issue_date=date.today(),
            subtotal=100,
            tax=18,
            total=118,
            balance=118,
        ))
        db.add(Bill(
            organization_id=target["org_id"],
            source="test",
            bill_number="BILL-EVENT",
            issue_date=date.today(),
            subtotal=50,
            tax=9,
            total=59,
            balance=59,
        ))
        db.add(BankTransaction(
            organization_id=target["org_id"],
            source="test",
            external_id="BANK-EVENT",
            transaction_date=date.today(),
            description="Bank event",
            amount=118,
            is_reconciled=False,
        ))
        db.add(Invoice(
            organization_id=other["org_id"],
            source="test",
            invoice_number="OTHER-EVENT",
            issue_date=date.today(),
            subtotal=999,
            tax=0,
            total=999,
            balance=999,
        ))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/accounting-events", headers=target["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["derived"] is True
    assert body["by_type"]["invoice"] >= 1
    assert body["by_type"]["bill"] >= 1
    assert body["by_type"]["bank_transaction"] >= 1
    event_ids = {event["event_id"] for event in body["events"]}
    assert any(event_id.startswith("invoice:") for event_id in event_ids)
    assert all(event["organization_id"] == target["org_id"] for event in body["events"])
    assert all(event["evidence"] for event in body["events"])

    other_resp = client.get("/api/accounting-events", headers=other["headers"])
    assert other_resp.status_code == 200, other_resp.text
    other_titles = {event["title"] for event in other_resp.json()["events"]}
    assert "חשבונית OTHER-EVENT" in other_titles
    assert "חשבונית INV-EVENT" not in other_titles


def test_accounting_events_filter_by_type(client, owner):
    resp = client.get("/api/accounting-events?event_type=bank_transaction", headers=owner["headers"])
    assert resp.status_code == 200, resp.text
    assert all(event["event_type"] == "bank_transaction" for event in resp.json()["events"])
