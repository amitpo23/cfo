"""Source-explicit relationships may arrive later; numerical IDs are not joins."""
from datetime import date
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, BankTransaction, Bill, BillStatus, Payment
from cfo.services.connector_base import NormalizedBankTransaction, NormalizedPayment
from cfo.services.sync_engine import SyncEngine


def test_bank_account_resolution_is_source_scoped_and_retried_after_account_arrives(fresh_org):
    org = fresh_org()['org_id']
    with SessionLocal() as db:
        other = Account(organization_id=org, source='sumit', external_id='account-1', name='Different source', account_type=AccountType.BANK)
        db.add(other); db.commit()
        item = NormalizedBankTransaction(external_id='tx-1', account_external_id='account-1',
            transaction_date=date(2026, 9, 6), amount=Decimal('400'), raw_data={'accountId': 'account-1'})
        engine = SyncEngine(db, None, org, 'open_finance')
        engine._upsert_bank_transaction(item); db.commit()
        bank = db.query(BankTransaction).filter_by(organization_id=org).one()
        assert bank.account_id is None
        account = Account(organization_id=org, source='open_finance', external_id='account-1', name='Correct source', account_type=AccountType.BANK)
        db.add(account); db.commit()
        engine._upsert_bank_transaction(item); db.commit()
        assert bank.account_id == account.id


def test_explicit_bill_link_arriving_later_is_scoped_and_preserved(fresh_org):
    org = fresh_org()['org_id']
    foreign = fresh_org()['org_id']
    with SessionLocal() as db:
        db.add(Bill(organization_id=foreign, source='sumit', external_id='bill-1',
            total=400, balance=400, paid_amount=0, status=BillStatus.RECEIVED))
        db.commit()
        item = NormalizedPayment(external_id='payment-1', bill_external_id='bill-1',
            payment_date=date(2026, 9, 6), amount=Decimal('400'), raw_data={'source': 'explicit synthetic bill relationship'})
        engine = SyncEngine(db, None, org, 'sumit')
        engine._upsert_payment(item); db.commit()
        payment = db.query(Payment).filter_by(organization_id=org).one()
        assert payment.bill_id is None
        bill = Bill(organization_id=org, source='sumit', external_id='bill-1',
            total=400, balance=400, paid_amount=0, status=BillStatus.RECEIVED)
        db.add(bill); db.commit()
        engine._upsert_payment(item); db.commit()
        assert payment.bill_id == bill.id
        assert bill.balance == 400, 'A source link alone is not proof of bank settlement'


def test_reviewed_bank_account_cannot_silently_change(fresh_org):
    org = fresh_org()['org_id']
    with SessionLocal() as db:
        first = Account(organization_id=org, source='open_finance', external_id='a', name='A', account_type=AccountType.BANK)
        second = Account(organization_id=org, source='open_finance', external_id='b', name='B', account_type=AccountType.BANK)
        db.add_all([first, second]); db.flush()
        bank = BankTransaction(organization_id=org, source='open_finance', external_id='tx',
            account_id=first.id, amount=400, transaction_date=date(2026, 9, 6), is_reconciled=True)
        db.add(bank); db.commit()
        with pytest.raises(ValueError, match='account'):
            SyncEngine(db, None, org, 'open_finance')._upsert_bank_transaction(NormalizedBankTransaction(
                external_id='tx', account_external_id='b', amount=Decimal('400'), transaction_date=bank.transaction_date))
        assert bank.account_id == first.id


def test_sync_cannot_bypass_explicitly_inactive_connection_using_legacy_credentials(fresh_org):
    from cfo.models import IntegrationConnection, Organization
    from cfo.services.sync_engine import get_connector_for_org
    org = fresh_org()['org_id']
    with SessionLocal() as db:
        db.get(Organization, org).api_credentials = {'client_id': 'fake', 'client_secret': 'fake', 'user_id': 'fake'}
        db.add(IntegrationConnection(organization_id=org, source='open_finance', status='inactive'))
        db.commit()
        with pytest.raises(ValueError, match='inactive'):
            get_connector_for_org(db, org, 'open_finance')


def test_shared_provider_identity_requires_an_explicit_connection_scope(fresh_org):
    from cfo.models import IntegrationConnection
    from cfo.services.credentials_vault import encrypt_credentials
    from cfo.services.sync_engine import get_connector_for_org
    org, other = fresh_org()['org_id'], fresh_org()['org_id']
    with SessionLocal() as db:
        for org_id in [org, other]:
            db.add(IntegrationConnection(organization_id=org_id, source='open_finance', status='active',
                credentials_encrypted=encrypt_credentials({'client_id': 'fake', 'client_secret': 'fake', 'user_id': 'shared-sync-user'})))
        db.commit()
        with pytest.raises(ValueError, match='connection scope'):
            get_connector_for_org(db, org, 'open_finance')
