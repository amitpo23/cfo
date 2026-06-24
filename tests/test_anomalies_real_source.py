"""פאזה 2 — זיהוי חריגות רץ על תנועות אמיתיות, לא על stream מזויף של 50 תנועות random."""
from datetime import date

import pytest

from cfo.services.ai_analytics_service import AdvancedAIService


def test_anomaly_source_uses_real_transactions(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Transaction, TransactionType, Account, AccountType

    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        acc = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(acc); db.flush()
        db.add(Transaction(organization_id=org_id, account_id=acc.id,
                           transaction_type=TransactionType.EXPENSE, amount=1234.0,
                           description="הוצאה ייחודית", category="office",
                           transaction_date=date(2026, 4, 10)))
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        svc = AdvancedAIService(db, organization_id=org_id)
        txns = svc._get_transactions(date(2026, 4, 1), date(2026, 4, 30))
        assert len(txns) == 1
        assert abs(txns[0]["amount"]) == 1234.0
    finally:
        db.close()


def test_anomaly_source_empty_when_no_data(fresh_org):
    """ללא תנועות — אין stream מזויף."""
    from cfo.database import SessionLocal

    org = fresh_org()
    db = SessionLocal()
    try:
        svc = AdvancedAIService(db, organization_id=org["org_id"])
        assert svc._get_transactions(date(2026, 4, 1), date(2026, 4, 30)) == []
    finally:
        db.close()
