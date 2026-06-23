"""User-facing financial recommendations generated from live org data."""
from datetime import date, datetime, timedelta


def _seed_recommendation_data(org_id: int):
    from cfo.database import SessionLocal
    from cfo.models import (
        Account,
        AccountType,
        BankTransaction,
        Bill,
        BillStatus,
        Budget,
        Contact,
        ContactType,
        Invoice,
        InvoiceStatus,
        Transaction,
        TransactionType,
    )

    today = date.today()
    db = SessionLocal()
    try:
        account = Account(
            organization_id=org_id,
            name="Operating bank",
            account_type=AccountType.BANK,
            balance=5000,
        )
        customer = Contact(
            organization_id=org_id,
            contact_type=ContactType.CUSTOMER,
            name="Recommendation Customer",
        )
        db.add_all([account, customer])
        db.flush()

        db.add_all([
            Transaction(
                organization_id=org_id,
                account_id=account.id,
                transaction_type=TransactionType.INCOME,
                amount=20000,
                description="Monthly revenue",
                category="sales",
                transaction_date=datetime.combine(today.replace(day=1), datetime.min.time()),
            ),
            Transaction(
                organization_id=org_id,
                account_id=account.id,
                transaction_type=TransactionType.EXPENSE,
                amount=32000,
                description="Materials",
                category="materials",
                transaction_date=datetime.combine(today.replace(day=1), datetime.min.time()),
            ),
            Invoice(
                organization_id=org_id,
                contact_id=customer.id,
                invoice_number="REC-INV-1",
                issue_date=today - timedelta(days=60),
                due_date=today - timedelta(days=35),
                total=15000,
                paid_amount=0,
                balance=15000,
                status=InvoiceStatus.OVERDUE,
            ),
            Bill(
                organization_id=org_id,
                bill_number="REC-BILL-1",
                issue_date=today - timedelta(days=3),
                due_date=today + timedelta(days=5),
                total=9000,
                paid_amount=0,
                balance=9000,
                status=BillStatus.APPROVED,
            ),
            BankTransaction(
                organization_id=org_id,
                transaction_date=today,
                description="Large unreconciled supplier payment",
                amount=-12000,
                currency="ILS",
                is_reconciled=False,
            ),
            Budget(
                organization_id=org_id,
                category_name="materials",
                year=today.year,
                month=today.month,
                budgeted_amount=10000,
            ),
        ])
        db.commit()
    finally:
        db.close()


def test_recommendations_require_auth(client):
    assert client.get("/api/brain/recommendations").status_code == 403


def test_recommendations_refresh_from_live_data(client, fresh_org):
    org = fresh_org()
    _seed_recommendation_data(org["org_id"])

    response = client.get(
        "/api/brain/recommendations?refresh=true",
        headers=org["headers"],
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] >= 4
    assert "אינה ייעוץ השקעות" in body["disclaimer"]

    recommendations = body["recommendations"]
    types = {item["insight_type"] for item in recommendations}
    assert {"collections", "reconciliation", "payables", "profitability", "budget"} & types
    assert recommendations == sorted(
        recommendations,
        key=lambda item: item["priority_score"],
        reverse=True,
    )
    for item in recommendations:
        assert item["recommended_action"]
        assert item["next_steps"]
        assert item["source_systems"]
        assert item["disclaimer"] == body["disclaimer"]


def test_recommendations_are_org_scoped(client, fresh_org):
    seeded = fresh_org()
    empty = fresh_org()
    _seed_recommendation_data(seeded["org_id"])

    seeded_resp = client.get(
        "/api/brain/recommendations?refresh=true",
        headers=seeded["headers"],
    )
    empty_resp = client.get(
        "/api/brain/recommendations?refresh=true",
        headers=empty["headers"],
    )

    assert seeded_resp.status_code == 200, seeded_resp.text
    assert empty_resp.status_code == 200, empty_resp.text
    seeded_text = str(seeded_resp.json())
    empty_text = str(empty_resp.json())
    assert "15000" in seeded_text
    assert "15000" not in empty_text
