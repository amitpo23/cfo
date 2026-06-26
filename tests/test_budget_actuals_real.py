"""פאזה 2 — תקציב מול ביצוע חייב לשקף תנועות אמיתיות, לא נתוני random.

באג שנמצא: _get_actual_by_category השתמש ב-Transaction.date (שדה לא קיים) →
זרק AttributeError → נפל ל-_get_sample_actuals (random) עבור כל ארגון. כלומר
"תקציב מול ביצוע" היה 100% מזויף. התיקון: שדה נכון + הסרת ה-fallback האקראי השקט.
"""
from datetime import date

import pytest

from cfo.services.budget_service import BudgetService


@pytest.fixture
def org_factory(fresh_org):
    return fresh_org


def test_actuals_reflect_real_transactions(org_factory):
    from cfo.database import SessionLocal
    from cfo.models import Transaction, TransactionType, Account, AccountType

    org = org_factory()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        acc = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(acc); db.flush()
        db.add(Transaction(organization_id=org_id, account_id=acc.id,
                           transaction_type=TransactionType.INCOME, amount=5000,
                           description="מכירה ללקוח", category="sales",
                           transaction_date=date(2026, 4, 10)))
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        svc = BudgetService(db, organization_id=org_id)
        actuals = svc._get_actual_by_category(date(2026, 4, 1), date(2026, 5, 1))
        assert actuals.get("sales") == 5000.0
    finally:
        db.close()


def test_actuals_empty_when_no_transactions_not_random(org_factory):
    """ללא תנועות — מחזיר {} (לא נתוני random מ-_get_sample_actuals)."""
    from cfo.database import SessionLocal

    org = org_factory()
    db = SessionLocal()
    try:
        svc = BudgetService(db, organization_id=org["org_id"])
        actuals = svc._get_actual_by_category(date(2026, 4, 1), date(2026, 5, 1))
        assert actuals == {}
    finally:
        db.close()
