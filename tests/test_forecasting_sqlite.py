"""פאזה 4 — אגרגציה חודשית בתחזית חייבת לעבוד על SQLite (date_trunc אינו קיים שם).
"""
from datetime import datetime, timedelta

import pytest

from cfo.services.forecasting_service import ForecastingService


def test_monthly_revenue_works_on_sqlite(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Transaction, TransactionType, Account, AccountType

    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        acc = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(acc); db.flush()
        now = datetime.now()
        db.add_all([
            Transaction(organization_id=org_id, account_id=acc.id,
                        transaction_type=TransactionType.INCOME, amount=1000,
                        description="הכנסה", category="sales",
                        transaction_date=now - timedelta(days=10)),
            Transaction(organization_id=org_id, account_id=acc.id,
                        transaction_type=TransactionType.INCOME, amount=500,
                        description="הכנסה", category="sales",
                        transaction_date=now - timedelta(days=12)),
        ])
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        svc = ForecastingService(db)
        rows = svc._get_monthly_revenue(org_id, months=6)  # לא קורס על SQLite
        assert sum(r["amount"] for r in rows) == 1500.0
        # 'date' הוא datetime (חוזה ל-route שעושה r.date.strftime)
        assert all(hasattr(r["date"], "strftime") for r in rows)
    finally:
        db.close()
