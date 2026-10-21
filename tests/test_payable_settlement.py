"""Offline bill-linked payment requests and reviewed bank settlement."""
import asyncio
from datetime import date
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import Bill, BillStatus, Contact, BankTransaction, User, Payment


@pytest.fixture
def payable(fresh_org):
    identity = fresh_org()
    with SessionLocal() as db:
        org = identity['org_id']
        vendor = Contact(organization_id=org, source='sumit', external_id='supplier-1',
            name='Synthetic supplier', contact_type='vendor', bank_code='12', bank_branch='345', bank_account_number='67890')
        db.add(vendor); db.flush()
        bill = Bill(organization_id=org, source='sumit', external_id='supplier-invoice-1', vendor_id=vendor.id,
            total=1000, paid_amount=0, balance=1000, currency='ILS', status=BillStatus.RECEIVED,
            issue_date=date(2026, 9, 1), raw_data={'document_type': 'invoice'})
        db.add(bill); db.commit()
        yield db, org, bill, vendor, db.query(User).filter_by(organization_id=org).one(), identity


def service(case):
    from cfo.services.payable_settlement import PayableSettlementService
    return PayableSettlementService(case[0], case[1])


def propose(case, amount='600', key='first'):
    return service(case).propose(bill_id=case[2].id, amount=amount, proposed_by=case[4],
        idempotency_key=key, creditor={'name': case[3].name, 'account_number': '12-345-67890', 'account_type': 'bban'},
        beneficiary_evidence='Reviewed supplier bank confirmation and exact bank, branch and account',
        withholding_decision='not_required', withholding_evidence='Owner reviewed payer obligation for this supplier payment')


class Provider:
    def __init__(self, status='PENDING'): self.calls = 0; self.status = status
    async def create_payment(self, body):
        self.calls += 1
        return {'id': 'supplier-payment-1', 'payUrl': 'https://synthetic.invalid/pay'}
    async def get_payment(self, reference): return {'id': reference, 'paymentStatus': self.status}
    async def close(self): pass


def execute(case, request, monkeypatch, status='PENDING'):
    from cfo.services.irreversible_action_service import IrreversibleActionService
    from cfo.api.routes import open_finance
    IrreversibleActionService(case[0], case[1]).approve(request.id, approved_by=case[4])
    provider = Provider(status)
    monkeypatch.setattr(open_finance, 'get_open_finance_client', lambda *args: provider)
    result = asyncio.run(service(case).execute(request.id))
    return provider, result


def bank(case, amount, key='one'):
    row = BankTransaction(organization_id=case[1], source='open_finance', external_id=f'bank:{key}',
        amount=-Decimal(str(amount)), currency='ILS', transaction_date=date(2026, 9, 6),
        is_provisional=False, raw_data={'status': 'BOOKED'})
    case[0].add(row); case[0].commit()
    return row


def settle(case, request, movement):
    return service(case).settle(request.id, bank_transaction_id=movement.id, decided_by=case[4],
        reason='Reviewed supplier identity and bank payment reference against the approved request')


def test_partial_bank_settlement_completes_request_without_double_counting_bill(payable, monkeypatch):
    request = propose(payable)
    provider, result = execute(payable, request, monkeypatch)
    assert result['money_status'] == 'pending' and payable[2].balance == 1000
    first = bank(payable, 400)
    result = settle(payable, request, first)
    assert result['remaining_balance'] == '600.00'
    assert result['remaining_request_amount'] == '200.00'
    assert settle(payable, request, first)['remaining_balance'] == '600.00'
    result = settle(payable, request, bank(payable, 200, 'two'))
    assert result['money_status'] == 'bank_settled'
    assert result['remaining_balance'] == '400.00'
    assert result['official_books_verified'] is False
    assert payable[0].query(Payment).filter_by(organization_id=payable[1]).one().amount == 600
    with pytest.raises(ValueError): asyncio.run(service(payable).execute(request.id))
    assert provider.calls == 1


@pytest.mark.parametrize('status', ['PENDING', 'RJCT', 'CANC', 'UNKNOWN', 'ACCC'])
def test_provider_result_alone_never_pays_bill(payable, monkeypatch, status):
    request = propose(payable)
    execute(payable, request, monkeypatch, status)
    assert payable[2].balance == 1000
    assert payable[0].query(Payment).filter_by(organization_id=payable[1]).count() == 0


def test_duplicate_request_and_changed_beneficiary_are_blocked(payable, monkeypatch):
    request = propose(payable)
    assert propose(payable).id == request.id
    with pytest.raises(ValueError): propose(payable, key='second')
    payable[3].bank_account_number = 'changed'; payable[0].commit()
    with pytest.raises(ValueError): execute(payable, request, monkeypatch)


def test_foreign_or_provisional_movement_cannot_settle(payable, monkeypatch, fresh_org):
    request = propose(payable); execute(payable, request, monkeypatch)
    movement = bank(payable, 600); movement.is_provisional = True; payable[0].commit()
    with pytest.raises(ValueError): settle(payable, request, movement)
    movement.is_provisional = False; movement.organization_id = fresh_org()['org_id']; payable[0].commit()
    with pytest.raises(ValueError): settle(payable, request, movement)
    assert payable[2].balance == 1000


def test_bank_review_reversal_preserves_history_and_restores_bill(payable, monkeypatch):
    request = propose(payable); execute(payable, request, monkeypatch)
    movement = bank(payable, 400); settle(payable, request, movement)
    result = service(payable).reverse(request.id, bank_transaction_id=movement.id, decided_by=payable[4],
        reason='Reviewed incorrect bank linkage; no supplier refund was initiated')
    assert result['remaining_balance'] == '1000.00'
    assert result['settlement_history'][0]['status'] == 'reversed'
    assert not movement.is_reconciled


def test_sync_cannot_replace_reviewed_bill_balance_or_bank_identity(payable, monkeypatch):
    from cfo.services.connector_base import NormalizedBill, NormalizedBankTransaction
    from cfo.services.sync_engine import SyncEngine
    request = propose(payable); execute(payable, request, monkeypatch)
    movement = bank(payable, 400); settle(payable, request, movement)
    with pytest.raises(ValueError, match='review'):
        SyncEngine(payable[0], None, payable[1], 'sumit')._upsert_bill(NormalizedBill(
            external_id=payable[2].external_id, vendor_external_id=payable[3].external_id,
            total=Decimal('1000'), paid_amount=Decimal('0'), balance=Decimal('1000'),
            raw_data={'late_source': True}))
    with pytest.raises(ValueError, match='review'):
        SyncEngine(payable[0], None, payable[1], 'open_finance')._upsert_bank_transaction(NormalizedBankTransaction(
            external_id=movement.external_id, amount=Decimal('-400'), currency='ILS',
            transaction_date=date(2026, 9, 7), raw_data={'status': 'BOOKED'}))
    assert payable[2].balance == 600 and movement.transaction_date == date(2026, 9, 6)


def test_supplier_ledger_uses_each_bank_settlement_date(payable, monkeypatch):
    from cfo.services.ledger_service import build_journal
    request = propose(payable); execute(payable, request, monkeypatch)
    settle(payable, request, bank(payable, 400))
    second = bank(payable, 200, 'later'); second.transaction_date = date(2026, 10, 1); payable[0].commit()
    settle(payable, request, second)
    entries = build_journal(payable[0], payable[1], start=date(2026, 10, 1), end=date(2026, 10, 31))
    assert sum(line.credit for entry in entries for line in entry.lines if line.account == '1200') == 200


def test_workbench_and_moshko_share_scoped_saved_evidence(payable, client, fresh_org):
    from cfo.services.ai_chat_tools import TOOLS
    request = propose(payable)
    response = client.get('/api/financial/payables/workbench', headers=payable[5]['headers'])
    assert response.status_code == 200
    data = response.json()
    assert data['sync_triggered'] is False and data['requests'][0]['request_id'] == request.id
    assert asyncio.run(TOOLS['get_payable_workbench'].fn(payable[0], payable[1])) == data
    assert client.get('/api/financial/payables/workbench', headers=fresh_org()['headers']).json()['requests'] == []


def test_missing_evidence_and_existing_unreflected_payment_block_proposal(payable):
    payable[3].bank_account_number = None; payable[0].commit()
    with pytest.raises(ValueError): propose(payable)
    payable[3].bank_account_number = '67890'
    payable[0].add(Payment(organization_id=payable[1], source='sumit', external_id='already-paid',
        bill_id=payable[2].id, amount=200, currency='ILS', payment_date=date(2026, 9, 5)))
    payable[0].commit()
    with pytest.raises(ValueError, match='parity'): propose(payable)


def test_permission_revoked_after_approval_prevents_provider_execution(payable, monkeypatch):
    from cfo.services.irreversible_action_service import IrreversibleActionService
    request = propose(payable)
    IrreversibleActionService(payable[0], payable[1]).approve(request.id, approved_by=payable[4])
    payable[4].is_active = False; payable[0].commit()
    with pytest.raises(ValueError): asyncio.run(service(payable).execute(request.id))


def test_timeout_is_not_retried_and_blocks_new_request(payable, monkeypatch):
    from cfo.services.irreversible_action_service import IrreversibleActionService
    from cfo.api.routes import open_finance
    request = propose(payable)
    IrreversibleActionService(payable[0], payable[1]).approve(request.id, approved_by=payable[4])
    class TimeoutProvider(Provider):
        async def create_payment(self, body):
            self.calls += 1
            raise TimeoutError('Unknown provider outcome')
    provider = TimeoutProvider()
    monkeypatch.setattr(open_finance, 'get_open_finance_client', lambda *args: provider)
    with pytest.raises(TimeoutError): asyncio.run(service(payable).execute(request.id))
    with pytest.raises(ValueError): asyncio.run(service(payable).execute(request.id))
    with pytest.raises(ValueError): propose(payable, key='retry')
    assert provider.calls == 1 and payable[2].balance == 1000


def test_authenticated_failure_event_blocks_bank_allocation(payable, monkeypatch):
    from cfo.models import ProviderEventReceipt
    request = propose(payable); execute(payable, request, monkeypatch)
    payable[0].add(ProviderEventReceipt(organization_id=payable[1], source='open_finance',
        entity_type='payment', external_id=request.provider_reference, fingerprint='f' * 64,
        disposition='applied', evidence={'paymentStatus': 'RJCT'}))
    payable[0].commit()
    assert service(payable).status(request.id)['money_status'] == 'failed'
    with pytest.raises(ValueError): settle(payable, request, bank(payable, 600))
    assert payable[2].balance == 1000


def test_accounting_events_preserve_bank_dates_and_unique_ids(payable, monkeypatch):
    from cfo.services.accounting_event_service import build_events
    request = propose(payable); execute(payable, request, monkeypatch)
    settle(payable, request, bank(payable, 400))
    later = bank(payable, 200, 'later'); later.transaction_date = date(2026, 10, 1); payable[0].commit()
    settle(payable, request, later)
    result = build_events(payable[0], payable[1], event_type='payment')
    assert len({event['event_id'] for event in result['events']}) == 2


def test_http_writes_require_scoped_admin_and_existing_signing_approval(payable, client, fresh_org, monkeypatch):
    from cfo.api.routes import open_finance
    request = propose(payable)
    provider = Provider()
    monkeypatch.setattr(open_finance, 'get_open_finance_client', lambda *args: provider)
    url = f'/api/financial/payables/requests/{request.id}'
    assert client.post(url + '/execute', headers=fresh_org()['headers']).status_code == 409
    assert client.post(url + '/execute', headers=payable[5]['headers']).status_code == 409
    assert provider.calls == 0
    assert client.post(f'/api/approvals/{request.id}/approve', headers=payable[5]['headers'], json={}).status_code == 200
    assert client.post(url + '/execute', headers=payable[5]['headers']).status_code == 200
    movement = bank(payable, 400)
    body = {'bank_transaction_id': movement.id, 'reason': 'Reviewed exact supplier payment and bank reference evidence'}
    response = client.post(url + '/settle', headers=payable[5]['headers'], json=body)
    assert response.status_code == 200 and response.json()['remaining_balance'] == '600.00'
    assert provider.calls == 1


def test_supplier_bank_decision_obeys_policy_inside_service(payable, monkeypatch):
    from cfo.models import UserRole
    from cfo.services.policy_service import PolicyService
    request = propose(payable); execute(payable, request, monkeypatch)
    PolicyService(payable[0], payable[1]).create_grant(created_by=payable[4],
        action='reconciliation.approve', effect='deny', role=UserRole.ADMIN)
    payable[0].commit()
    with pytest.raises(ValueError, match='policy'): settle(payable, request, bank(payable, 400))
    assert payable[2].balance == 1000


def test_later_official_payment_needs_explicit_parity_before_second_count(payable, monkeypatch):
    from cfo.services.connector_base import NormalizedPayment
    from cfo.services.sync_engine import SyncEngine
    request = propose(payable); execute(payable, request, monkeypatch)
    settle(payable, request, bank(payable, 400))
    with pytest.raises(ValueError, match='parity'):
        SyncEngine(payable[0], None, payable[1], 'sumit')._upsert_payment(NormalizedPayment(
            external_id='official-supplier-payment', bill_external_id=payable[2].external_id,
            payment_date=date(2026, 9, 6), amount=Decimal('400'), currency='ILS',
            raw_data={'explicitBill': payable[2].external_id}))
    assert payable[0].query(Payment).filter_by(organization_id=payable[1]).count() == 1
