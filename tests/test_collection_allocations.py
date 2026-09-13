"""Reviewed receipt allocations without requiring a new collection request."""
from datetime import date
from decimal import Decimal

import pytest

from cfo.models import Invoice, InvoiceStatus, Payment, BankTransaction, CollectionPaymentAllocation
from test_collection_settlement import case, received, service


def test_original_collection_entry_point_creates_reversible_allocation(case, monkeypatch):
    from test_collection_settlement import propose, execute, link
    request = propose(case, amount='400')
    execute(case, monkeypatch, request)
    payment, bank = received(case, 400)
    link(case, request, payment, bank)
    row = case[0].query(CollectionPaymentAllocation).filter_by(organization_id=case[1]).one()
    assert 'policy' in row.evidence
    service(case).reverse_allocation(row.id, decided_by=case[3], reason='Reviewed mistaken allocation to invoice')
    assert case[2].balance == 1000
    assert payment.invoice_id is None


def test_collection_status_consumes_authenticated_provider_observation_without_closing_invoice(case, monkeypatch):
    from test_collection_settlement import propose, execute
    from cfo.models import IntegrationConnection
    from cfo.services.credentials_vault import encrypt_credentials
    from cfo.services.provider_event_service import record_open_finance_event
    request = propose(case)
    execute(case, monkeypatch, request)
    case[0].add(IntegrationConnection(organization_id=case[1], source='open_finance', status='active',
        credentials_encrypted=encrypt_credentials({'user_id': f'synthetic-{case[1]}'})))
    case[0].commit()
    record_open_finance_event(case[0], {'userId': f'synthetic-{case[1]}', 'paymentId': request.provider_reference,
        'paymentStatus': 'ACCC'})
    result = service(case).status(request.id)
    assert result['money_status'] == 'provider_settled'
    assert result['provider_observation']['scope'] == 'authenticated_callback'
    assert result['remaining_balance'] == 1000
    assert not result['official_books_verified']


def allocate(case, payment, bank, amount, key, invoice=None):
    return service(case).allocate_existing(invoice_id=(invoice or case[2]).id,
        payment_id=payment.id, bank_transaction_id=bank.id, amount=amount,
        idempotency_key=key, decided_by=case[3], reason='Reviewed source receipt and payer reference with the customer')


def test_one_receipt_covers_two_invoices_with_unallocated_excess(case):
    db, org, invoice, *_ = case
    other = Invoice(organization_id=org, source='sumit', external_id='invoice-2',
        contact_id=invoice.contact_id, total=200, balance=200, paid_amount=0, currency='ILS',
        status=InvoiceStatus.SENT, issue_date=date(2026, 9, 1), raw_data={'document_type': 'invoice'})
    db.add(other); db.commit()
    payment, bank = received(case, 1500)
    first = allocate(case, payment, bank, '1000', 'split-1')
    assert first['payment_unallocated_amount'] == '500.00'
    second = allocate(case, payment, bank, '200', 'split-2', other)
    assert second['payment_unallocated_amount'] == '300.00'
    assert second['bank_unallocated_amount'] == '300.00'
    assert invoice.balance == other.balance == 0
    assert payment.invoice_id is None, 'A split must not become a false single invoice source link'
    assert not bank.is_reconciled, 'An unexplained remainder is still open'
    assert allocate(case, payment, bank, '1000', 'split-1')['allocation_id'] == first['allocation_id']
    assert db.query(CollectionPaymentAllocation).filter_by(organization_id=org).count() == 2


def test_multiple_payments_and_banks_complete_one_invoice(case):
    db, org, invoice, *_ = case
    payment, bank = received(case, 400)
    allocate(case, payment, bank, '400', 'first')
    second = Payment(organization_id=org, source='sumit', external_id='receipt:43', contact_id=invoice.contact_id,
        amount=600, currency='ILS', payment_date=date(2026, 9, 6), method='receipt',
        raw_data={'document_id': '43', 'document_type': 'receipt', 'status': 'open'})
    second_bank = BankTransaction(organization_id=org, source='open_finance', external_id='bank:2',
        amount=600, currency='ILS', transaction_date=date(2026, 9, 6), raw_data={'status': 'BOOKED'})
    db.add_all([second, second_bank]); db.commit()
    assert allocate(case, second, second_bank, '600', 'second')['remaining_balance'] == '0.00'
    assert bank.is_reconciled and second_bank.is_reconciled


def test_one_receipt_can_be_supported_by_multiple_booked_movements(case):
    db, org, invoice, *_ = case
    payment, bank = received(case, 1000)
    bank.amount = 400
    other = BankTransaction(organization_id=org, source='open_finance', external_id='bank:2',
        amount=600, currency='ILS', transaction_date=date(2026, 9, 6), raw_data={'status': 'BOOKED'})
    db.add(other); db.commit()
    allocate(case, payment, bank, '400', 'bank-1')
    assert allocate(case, payment, other, '600', 'bank-2')['remaining_balance'] == '0.00'


def test_already_linked_receipt_does_not_reduce_balance_twice(case):
    payment, bank = received(case, 400)
    payment.invoice_id = case[2].id
    case[2].paid_amount = 400; case[2].balance = 600
    case[0].commit()
    result = allocate(case, payment, bank, '400', 'already-paid')
    assert result['remaining_balance'] == '600.00'
    assert result['payment_unallocated_amount'] == '0.00'


def test_review_reversal_preserves_history_and_restores_only_local_balance_effect(case):
    from cfo.models import CollectionAllocationReversal
    payment, bank = received(case, 400)
    result = allocate(case, payment, bank, '400', 'first')
    svc = service(case)
    reversal = svc.reverse_allocation(result['allocation_id'], decided_by=case[3],
        reason='Wrong invoice selected; source documents themselves were not cancelled')
    assert reversal['remaining_balance'] == '1000.00'
    assert not bank.is_reconciled
    assert case[0].query(CollectionPaymentAllocation).filter_by(organization_id=case[1]).count() == 1
    assert case[0].query(CollectionAllocationReversal).filter_by(organization_id=case[1]).count() == 1
    assert svc.reverse_allocation(result['allocation_id'], decided_by=case[3],
        reason='Repeated reversal request')['reversal_id'] == reversal['reversal_id']


@pytest.mark.parametrize('violation', ['overpayment', 'provisional', 'currency', 'missing_receipt', 'short_reason', 'changed_key'])
def test_invalid_or_ambiguous_evidence_cannot_change_balances(case, violation):
    payment, bank = received(case, 400)
    kwargs = dict(invoice_id=case[2].id, payment_id=payment.id, bank_transaction_id=bank.id,
        amount='400', idempotency_key='evidence', decided_by=case[3], reason='Reviewed payer identity and receipt')
    if violation == 'overpayment': kwargs['amount'] = '500'
    if violation == 'provisional': bank.is_provisional = True
    if violation == 'currency': bank.currency = 'USD'
    if violation == 'missing_receipt': payment.raw_data = {}
    if violation == 'short_reason': kwargs['reason'] = 'same sum'
    if violation == 'changed_key':
        service(case).allocate_existing(**kwargs)
        kwargs['amount'] = '300'
    case[0].commit()
    before = case[2].balance
    with pytest.raises(ValueError): service(case).allocate_existing(**kwargs)
    assert case[2].balance == before


def test_foreign_tenant_cannot_allocate_or_reverse(case, fresh_org):
    from cfo.services.collection_settlement import CollectionSettlementService
    payment, bank = received(case, 400)
    result = allocate(case, payment, bank, '400', 'first')
    foreign = CollectionSettlementService(case[0], fresh_org()['org_id'])
    with pytest.raises(ValueError): foreign.reverse_allocation(result['allocation_id'], decided_by=case[3], reason='Foreign request')
    with pytest.raises(ValueError): foreign.allocate_existing(invoice_id=case[2].id, payment_id=payment.id,
        bank_transaction_id=bank.id, amount='400', idempotency_key='foreign', decided_by=case[3], reason='Foreign request')


def test_split_source_readback_compares_whole_payment_and_bank_not_one_edge(case):
    from cfo.services.sync_engine import SyncEngine
    from cfo.services.connector_base import NormalizedBankTransaction, NormalizedPayment
    payment, bank = received(case, 1500)
    allocate(case, payment, bank, '400', 'partial')
    engine = SyncEngine(case[0], None, case[1], 'sumit')
    assert engine._upsert_payment(NormalizedPayment(external_id=payment.external_id,
        amount=Decimal('1500'), currency='ILS', method='receipt', payment_date=payment.payment_date,
        raw_data=payment.raw_data)) in {'updated', 'skipped'}
    engine.source = 'open_finance'
    assert engine._upsert_bank_transaction(NormalizedBankTransaction(external_id=bank.external_id,
        amount=Decimal('1500'), currency='ILS', transaction_date=bank.transaction_date,
        raw_data=bank.raw_data)) in {'updated', 'skipped'}


def test_split_allocations_are_posted_once_to_derived_ledger(case):
    from cfo.services.ledger_service import build_journal
    payment, bank = received(case, 1000)
    allocate(case, payment, bank, '400', 'first')
    allocate(case, payment, bank, '600', 'second')
    entries = [entry for entry in build_journal(case[0], case[1]) if entry.source_ref == f'payment:{payment.id}']
    assert len(entries) == 1
    assert entries[0].total_debit == entries[0].total_credit == 1000


def test_reversal_cannot_be_silently_replaced_by_stale_provider_paid_total(case):
    from cfo.services.sync_engine import SyncEngine
    from cfo.services.connector_base import NormalizedInvoice
    payment, bank = received(case, 400)
    result = allocate(case, payment, bank, '400', 'first')
    service(case).reverse_allocation(result['allocation_id'], decided_by=case[3], reason='Incorrect invoice identity was selected')
    item = NormalizedInvoice(external_id=case[2].external_id, total=Decimal('1000'),
        paid_amount=Decimal('400'), balance=Decimal('600'), currency='ILS', status='partially_paid',
        issue_date=case[2].issue_date, raw_data={'document_type': 'invoice'})
    with pytest.raises(ValueError, match='reversal'):
        SyncEngine(case[0], None, case[1], 'sumit')._upsert_invoice(item)
    assert case[2].balance == 1000


def test_unallocated_customer_receipt_blocks_a_new_collection_request(case):
    from test_collection_settlement import propose
    received(case, 400)
    with pytest.raises(ValueError, match='receipt'):
        propose(case)


def test_request_remains_open_until_all_approved_money_is_allocated(case, monkeypatch):
    from test_collection_settlement import propose, execute
    request = propose(case)
    execute(case, monkeypatch, request)
    payment, bank = received(case, 1000)
    service(case).allocate_existing(invoice_id=case[2].id, payment_id=payment.id,
        bank_transaction_id=bank.id, amount='400', idempotency_key='partial-request', request_id=request.id,
        decided_by=case[3], reason='Reviewed receipt reference against this request')
    status = service(case).status(request.id)
    assert status['money_status'] == 'partially_received'
    assert status['allocated_amount'] == '400.00'
    assert status['remaining_collection_amount'] == '600.00'
    with pytest.raises(ValueError): propose(case, amount='600', key='new-channel')


def test_reconciliation_policy_deny_is_enforced_inside_service(case):
    from cfo.services.policy_service import PolicyService
    from cfo.models import UserRole
    payment, bank = received(case, 400)
    PolicyService(case[0], case[1]).create_grant(created_by=case[3], action='reconciliation.approve',
        effect='deny', role=UserRole.ADMIN)
    case[0].commit()
    with pytest.raises(ValueError, match='policy'):
        allocate(case, payment, bank, '400', 'denied')
    assert case[2].balance == 1000


def test_workbench_http_and_moshko_show_same_scoped_evidence(case, client, fresh_org):
    import asyncio
    from cfo.services.ai_chat_tools import TOOLS
    payment, bank = received(case, 400)
    result = allocate(case, payment, bank, '400', 'first')
    response = client.get('/api/financial/collection/workbench', headers=case[4]['headers'])
    assert response.status_code == 200
    body = response.json()
    assert body['allocations'][0]['allocation_id'] == result['allocation_id']
    assert body['invoices'][0]['balance'] == '600.00'
    assert body['sync_triggered'] is False
    tool_result = asyncio.run(TOOLS['get_collection_workbench'].fn(case[0], case[1]))
    assert tool_result == body
    foreign = client.get('/api/financial/collection/workbench', headers=fresh_org()['headers']).json()
    assert foreign['allocations'] == []
