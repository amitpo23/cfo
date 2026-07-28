"""FinancialService must be tenant-bound for every read and write."""
from datetime import datetime
from decimal import Decimal

import pytest

from cfo.database import SessionLocal, init_db
from cfo.models import (
    Account,
    AccountCreate,
    AccountType,
    Organization,
    Transaction,
    TransactionCreate,
    TransactionType,
)
from cfo.services.financial_service import FinancialService


@pytest.fixture(autouse=True, scope="module")
def _schema():
    init_db()


def _seed_two_orgs(db):
    org_a = Organization(name="FinancialService A")
    org_b = Organization(name="FinancialService B")
    db.add_all([org_a, org_b])
    db.flush()
    account_a = Account(
        organization_id=org_a.id,
        name="A bank",
        account_type=AccountType.ASSET,
        balance=Decimal("100"),
    )
    account_b = Account(
        organization_id=org_b.id,
        name="B bank",
        account_type=AccountType.ASSET,
        balance=Decimal("900"),
    )
    db.add_all([account_a, account_b])
    db.flush()
    db.add_all([
        Transaction(
            organization_id=org_a.id,
            account_id=account_a.id,
            transaction_type=TransactionType.INCOME,
            amount=Decimal("20"),
            transaction_date=datetime(2026, 7, 1),
        ),
        Transaction(
            organization_id=org_b.id,
            account_id=account_b.id,
            transaction_type=TransactionType.INCOME,
            amount=Decimal("800"),
            transaction_date=datetime(2026, 7, 1),
        ),
    ])
    db.commit()
    return org_a.id, org_b.id, account_a.id, account_b.id


def test_financial_service_scopes_all_reads_and_summary_to_organization():
    db = SessionLocal()
    try:
        org_a, _org_b, account_a, account_b = _seed_two_orgs(db)
        service = FinancialService(db, org_a)

        assert [row.id for row in service.get_all_accounts()] == [account_a]
        assert service.get_account(account_b) is None
        assert {row.account_id for row in service.get_transactions()} == {account_a}

        summary = service.get_financial_summary(
            datetime(2026, 7, 1), datetime(2026, 7, 31),
        )
        assert summary.total_assets == Decimal("100")
        assert summary.total_income == Decimal("20")
    finally:
        db.close()


def test_financial_service_sets_org_on_create_and_rejects_cross_org_write():
    db = SessionLocal()
    try:
        org_a, _org_b, _account_a, account_b = _seed_two_orgs(db)
        service = FinancialService(db, org_a)

        created = service.create_account(AccountCreate(
            name="New A account",
            account_type=AccountType.ASSET,
            balance=Decimal("50"),
        ))
        assert created.organization_id == org_a

        with pytest.raises(ValueError, match="not found"):
            service.create_transaction(TransactionCreate(
                account_id=account_b,
                transaction_type=TransactionType.EXPENSE,
                amount=Decimal("10"),
                transaction_date=datetime(2026, 7, 2),
            ))

        db.expire_all()
        assert db.query(Account).filter(Account.id == account_b).one().balance == Decimal("900")
        assert db.query(Transaction).filter(
            Transaction.organization_id == org_a,
            Transaction.account_id == account_b,
        ).count() == 0
    finally:
        db.close()
