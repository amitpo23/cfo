"""Synthetic event evidence: authentication, attribution and monotonic claims."""
import asyncio
from datetime import date

import pytest

from cfo.database import SessionLocal
from cfo.models import BankConnection, IntegrationConnection, OpenFinancePayment, Payment
from cfo.services.credentials_vault import encrypt_credentials


@pytest.fixture
def event_org(fresh_org, monkeypatch):
    from cfo.api.routes import open_finance
    org = fresh_org()['org_id']
    db = SessionLocal()
    db.add(IntegrationConnection(organization_id=org, source='open_finance', status='active',
        credentials_encrypted=encrypt_credentials({'user_id': f'event-user-{org}'})))
    db.commit()
    monkeypatch.setattr(open_finance.settings, 'open_finance_webhook_secret', 'synthetic-secret')
    yield db, org, f'event-user-{org}'
    db.close()


def deliver(client, user, status='PENDING', **extra):
    return client.post('/api/open-finance/webhooks', headers={'X-Webhook-Secret': 'synthetic-secret'},
        json={'userId': user, 'paymentId': 'payment-1', 'paymentStatus': status, **extra})


@pytest.mark.parametrize('route,setting', [('open-finance', 'open_finance_webhook_secret'),
                                         ('sumit', 'sumit_webhook_secret')])
def test_receiver_without_authentication_configuration_is_disabled(client, monkeypatch, route, setting):
    from cfo.config import settings
    monkeypatch.setattr(settings, setting, None)
    assert client.post(f'/api/{route}/webhooks', json={'paymentId': 'untrusted'}).status_code == 503


def test_invalid_shape_is_rejected(client, event_org):
    assert client.post('/api/open-finance/webhooks', json=[],
        headers={'X-Webhook-Secret': 'synthetic-secret'}).status_code == 400


def test_settled_event_cannot_be_downgraded_and_history_survives_replay(client, event_org):
    from cfo.models import ProviderEventReceipt
    db, org, user = event_org
    assert deliver(client, user, 'ACCC').status_code == 200
    assert deliver(client, user, 'PENDING').status_code == 200
    assert deliver(client, user, 'PENDING').json()['delta_sync']['reason'] == 'duplicate_event'
    row = db.query(OpenFinancePayment).filter_by(organization_id=org).one()
    assert row.status == 'ACCC'
    receipts = db.query(ProviderEventReceipt).filter_by(organization_id=org).all()
    assert len(receipts) == 2
    assert {r.disposition for r in receipts} == {'applied', 'review_required'}


@pytest.mark.parametrize('status', ['RJCT', 'CANC', 'NEW_PROVIDER_STATUS'])
def test_conflicting_or_unknown_status_preserves_previous_evidence(client, event_org, status):
    db, org, user = event_org
    deliver(client, user, 'ACSC')
    result = deliver(client, user, status)
    assert result.json()['delta_sync']['reason'] == 'review_required'
    assert db.query(OpenFinancePayment).filter_by(organization_id=org).one().status == 'ACSC'


def test_shared_provider_user_is_not_an_organization_identity(client, event_org, fresh_org):
    db, org, user = event_org
    db.add(IntegrationConnection(organization_id=fresh_org()['org_id'], source='open_finance',
        status='active', credentials_encrypted=encrypt_credentials({'user_id': user})))
    db.commit()
    result = deliver(client, user)
    assert result.json()['delta_sync']['reason'] == 'unresolvable_org'
    assert db.query(OpenFinancePayment).filter_by(organization_id=org).count() == 0


def test_revoked_integration_cannot_receive_payment_updates(client, event_org):
    db, org, user = event_org
    db.query(IntegrationConnection).filter_by(organization_id=org).one().status = 'inactive'
    db.commit()
    assert deliver(client, user).json()['delta_sync']['reason'] == 'unresolvable_org'
    assert db.query(OpenFinancePayment).filter_by(organization_id=org).count() == 0


def test_foreign_connection_cannot_be_updated_by_another_user(client, event_org, fresh_org):
    db, org, user = event_org
    bank = BankConnection(organization_id=fresh_org()['org_id'], source='open_finance',
        connection_id='foreign-connection', status='ACTIVE')
    db.add(bank); db.commit()
    deliver(client, user, connectionId=bank.connection_id, connectionStatus='EXPIRED')
    db.refresh(bank)
    assert bank.status == 'ACTIVE'


def test_payment_id_collision_never_links_an_accounting_payment(client, event_org):
    db, org, user = event_org
    payment = Payment(organization_id=org, source='sumit', external_id='payment-1',
        amount=50, currency='ILS', payment_date=date(2026, 9, 6), raw_data={'document_id': 'receipt-1'})
    db.add(payment); db.commit()
    deliver(client, user, 'ACCC')
    db.refresh(payment)
    assert payment.raw_data == {'document_id': 'receipt-1'}


def test_status_event_cannot_replace_verified_amount(client, event_org):
    db, org, user = event_org
    db.add(OpenFinancePayment(organization_id=org, external_payment_id='payment-1',
        amount=50, currency='ILS', status='PENDING'))
    db.commit()
    deliver(client, user, 'ACSC', amount=500, currency='USD')
    row = db.query(OpenFinancePayment).filter_by(organization_id=org).one()
    assert row.amount == 50 and row.currency == 'ILS'
