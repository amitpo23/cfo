"""Offline vertical slice: approved collection -> receipt -> bank -> residual AR."""
import asyncio
from datetime import date
from decimal import Decimal
import pytest
from cfo.database import SessionLocal
from cfo.models import Invoice, InvoiceStatus, Contact, Payment, BankTransaction, User

@pytest.fixture
def case(fresh_org):
    identity = fresh_org()
    db = SessionLocal()
    org = identity['org_id']
    customer = Contact(organization_id=org, source='sumit', external_id='customer-1', name='Synthetic customer', contact_type='customer')
    db.add(customer); db.flush()
    invoice = Invoice(organization_id=org, source='sumit', external_id='invoice-1', contact_id=customer.id,
        total=1000, balance=1000, paid_amount=0, currency='ILS', status=InvoiceStatus.SENT,
        issue_date=date(2026,9,1), raw_data={'document_type':'invoice'})
    db.add(invoice); db.commit()
    yield db, org, invoice, db.query(User).filter_by(organization_id=org).one(), identity
    db.close()

def service(case):
    from cfo.services.collection_settlement import CollectionSettlementService
    return CollectionSettlementService(case[0],case[1])

def propose(case, amount='1000', key='one', channel='open_finance'):
    return service(case).propose(invoice_id=case[2].id, amount=Decimal(amount), channel=channel,
        proposed_by=case[3], idempotency_key=key, creditor={'name':'Synthetic business','account_number':'12-345-67890','account_type':'bban'})

def approve(case, request):
    from cfo.services.irreversible_action_service import IrreversibleActionService
    return IrreversibleActionService(case[0],case[1]).approve(request.id,approved_by=case[3])

class Provider:
    def __init__(self,status='PENDING'): self.status=status; self.calls=0
    async def create_payment(self,payload):
        self.calls+=1
        return {'id':'request-1','payUrl':'https://synthetic.invalid/pay'}
    async def get_payment(self,ref): return {'id':ref,'paymentStatus':self.status}
    async def close(self): pass

def execute(case, monkeypatch, request, status='PENDING'):
    from cfo.api.routes import open_finance
    provider=Provider(status)
    monkeypatch.setattr(open_finance,'get_open_finance_client',lambda *args:provider)
    approve(case, request)
    result=asyncio.run(service(case).execute(request.id))
    return provider,result

def received(case, amount=1000, provisional=False):
    db,org,inv,_,_=case
    payment=Payment(organization_id=org,source='sumit',external_id='receipt:42',contact_id=inv.contact_id,
       amount=amount,currency='ILS',payment_date=date(2026,9,6),method='receipt',
       raw_data={'document_id':'42','document_type':'receipt','status':'open'})
    bank=BankTransaction(organization_id=org,source='open_finance',external_id='bank:1',amount=amount,
       currency='ILS',transaction_date=date(2026,9,6),is_provisional=provisional,raw_data={'status':'BOOKED','entryReference':'bank-ref-1'})
    db.add_all([payment,bank]);db.commit()
    return payment,bank

def link(case, request, payment, bank, reason='Reviewed the payer transfer reference and SUMIT receipt'):
    return service(case).allocate(request.id,payment_id=payment.id,bank_transaction_id=bank.id,
        decided_by=case[3],reason=reason)

def test_happy_path_reuses_receipt_and_replay_is_idempotent(case,monkeypatch):
    request=propose(case)
    provider,result=execute(case,monkeypatch,request)
    assert result['request_verified'] is True
    assert result['money_status']=='pending'
    assert case[2].balance==1000
    payment,bank=received(case)
    result=link(case,request,payment,bank)
    assert result['remaining_balance']==0
    assert result['money_status']=='received'
    assert result['document']['external_id']=='42'
    assert result['official_reconciliation_status']=='unsupported'
    assert link(case,request,payment,bank)['remaining_balance']==0
    assert case[0].query(Payment).filter_by(organization_id=case[1]).count()==1
    with pytest.raises(ValueError): asyncio.run(service(case).execute(request.id))
    assert provider.calls==1

@pytest.mark.parametrize('status,expected',[('PENDING','pending'),('RJCT','failed'),('CANC','cancelled'),('ACSC','debtor_settled'),('ACCC','provider_settled')])
def test_provider_status_never_closes_invoice(case,monkeypatch,status,expected):
    request=propose(case)
    _,result=execute(case,monkeypatch,request,status)
    assert result['money_status']==expected
    assert result['remaining_balance']==1000
    assert case[0].query(Payment).filter_by(organization_id=case[1]).count()==0


def test_partial_payment_and_duplicate_proposal(case,monkeypatch):
    request=propose(case,amount='400')
    assert propose(case,amount='400').id==request.id
    execute(case,monkeypatch,request)
    payment,bank=received(case,400)
    result=link(case,request,payment,bank)
    assert result['remaining_balance']==600
    assert case[2].paid_amount==400
    assert link(case,request,payment,bank)['remaining_balance']==600

@pytest.mark.parametrize('provisional,reason',[(True,'reviewed evidence'),(False,'')])
def test_amount_and_date_are_not_identity(case,monkeypatch,provisional,reason):
    request=propose(case);execute(case,monkeypatch,request)
    payment,bank=received(case,provisional=provisional)
    with pytest.raises(ValueError): link(case,request,payment,bank,reason)
    assert case[2].balance==1000
    assert not bank.is_reconciled


def test_already_recorded_receipt_is_not_subtracted_twice(case,monkeypatch):
    request=propose(case);execute(case,monkeypatch,request)
    payment,bank=received(case)
    payment.invoice_id=case[2].id
    case[2].paid_amount=1000;case[2].balance=0
    case[0].commit()
    assert link(case,request,payment,bank)['remaining_balance']==0
    assert case[2].paid_amount==1000


def test_foreign_organization_cannot_read_execute_or_allocate(case,fresh_org,monkeypatch):
    from cfo.services.collection_settlement import CollectionSettlementService
    request=propose(case); execute(case,monkeypatch,request)
    payment,bank=received(case)
    other=fresh_org()
    foreign=CollectionSettlementService(case[0],other['org_id'])
    with pytest.raises(ValueError): foreign.status(request.id)
    with pytest.raises(ValueError): asyncio.run(foreign.execute(request.id))
    with pytest.raises(ValueError): foreign.allocate(request.id,payment_id=payment.id,bank_transaction_id=bank.id,decided_by=case[3],reason='checked')


def test_missing_receipt_stays_pending_document(case,monkeypatch):
    request=propose(case);execute(case,monkeypatch,request,'ACCC')
    result=service(case).status(request.id)
    assert result['document']['status']=='awaiting_existing_receipt_or_approved_issue'
    assert result['document']['required_type']=='receipt'
    assert result['remaining_balance']==1000


def test_sumit_channel_requests_receipt_and_keeps_request_unverified(case,monkeypatch):
    from cfo.services.document_issuance_service import DocumentIssuanceService
    calls=[]
    async def fake(self,invoice_id,**kwargs):
        calls.append((invoice_id,kwargs))
        return {'payment_url':'https://synthetic.invalid/sumit','invoice_id':invoice_id,'amount':400}
    monkeypatch.setattr(DocumentIssuanceService,'create_payment_link',fake)
    request=propose(case,amount='400',channel='sumit');approve(case,request)
    result=asyncio.run(service(case).execute(request.id))
    assert calls[0][1]['document_type']=='receipt'
    assert calls[0][1]['external_identifier']==f'rezef-collection-{request.id}'
    assert not result['request_verified']
    assert result['money_status']=='pending'


def test_bank_candidates_never_become_confirmed_without_identity(case):
    from cfo.services.bank_reconciliation import reconcile_organization
    payment,bank=received(case,provisional=True)
    result=reconcile_organization(case[0],case[1],persist=True)
    assert result['matched_count']==0
    assert result['candidates']
    assert not bank.is_reconciled
    assert any(m['entity_type']=='payment' for m in result['candidates'])


def test_request_verification_api_exposes_money_status(client,owner,monkeypatch):
    from cfo.api.routes import open_finance
    from test_approved_open_finance_payment import _approved_payment
    p=Provider()
    monkeypatch.setattr(open_finance,'get_open_finance_client',lambda *a:p)
    payload={'amount':10,'currency':'ILS'}
    request=_approved_payment(client,owner,key='status-scope-test',payload=payload)
    response=client.post('/api/open-finance/payments',json=payload,
        headers={**owner['headers'],'X-Rezef-Approval-Id':str(request)})
    assert response.status_code==200,response.text
    assert response.json()['verification_scope']=='payment_request'
    assert response.json()['money_status']=='pending'
    assert response.json()['creditor_receipt_verified'] is False


def test_http_workflow_and_foreign_access(case,client,monkeypatch,fresh_org):
    from cfo.api.routes import open_finance
    p=Provider();monkeypatch.setattr(open_finance,'get_open_finance_client',lambda *a:p)
    headers=case[4]['headers']
    response=client.post('/api/financial/collection/requests',headers=headers,json={
        'invoice_id':case[2].id,'amount':'1000','channel':'open_finance','idempotency_key':'http',
        'creditor':{'name':'Business','account_number':'12-345-67890','account_type':'bban'}})
    assert response.status_code==201,response.text
    request_id=response.json()['request_id']
    denied=client.post(f'/api/financial/collection/requests/{request_id}/execute',headers=headers)
    assert denied.status_code==409 and p.calls==0
    approved=client.post(f'/api/approvals/{request_id}/approve',headers=headers)
    assert approved.status_code==200,approved.text
    executed=client.post(f'/api/financial/collection/requests/{request_id}/execute',headers=headers)
    assert executed.status_code==200,executed.text
    assert executed.json()['money_status']=='pending'
    foreign=client.get(f'/api/financial/collection/requests/{request_id}',headers=fresh_org()['headers'])
    assert foreign.status_code==404
    payment,bank=received(case)
    settled=client.post(f'/api/financial/collection/requests/{request_id}/allocate',headers=headers,json={
        'payment_id':payment.id,'bank_transaction_id':bank.id,'reason':'Reviewed transfer confirmation and receipt identities'})
    assert settled.status_code==200,settled.text
    assert settled.json()['remaining_balance']==0


def test_invoice_sync_preserves_reviewed_partial_settlement(case,monkeypatch):
    from cfo.services.sync_engine import SyncEngine
    from cfo.services.connector_base import NormalizedInvoice
    request=propose(case,amount='400');execute(case,monkeypatch,request)
    payment,bank=received(case,400);link(case,request,payment,bank)
    item=NormalizedInvoice(external_id='invoice-1',total=Decimal('1000'),balance=Decimal('1000'),
        paid_amount=Decimal(0),status='sent',raw_data={'document_type':'invoice','new_snapshot':True})
    SyncEngine(case[0],None,case[1],'sumit')._upsert_invoice(item);case[0].commit()
    assert case[2].balance==600
    assert case[2].paid_amount==400


def test_unlinked_chat_bank_request_is_refused_before_provider(case,monkeypatch):
    from cfo.services.ai_chat_tools import _create_bank_payment_request
    from cfo.api.routes import open_finance
    def forbidden(*args):raise AssertionError('Provider must not be constructed')
    monkeypatch.setattr(open_finance,'get_open_finance_client',forbidden)
    with pytest.raises(ValueError):
        asyncio.run(_create_bank_payment_request(case[0],case[1],amount=10,description='Unlinked',creditor_name='Business',creditor_account_number='12-345-67890'))


def test_allocated_bank_cannot_be_silently_rematched_or_unmatched(case,monkeypatch):
    from cfo.services.manual_reconciliation import ManualReconciliationService
    request=propose(case);execute(case,monkeypatch,request)
    payment,bank=received(case);link(case,request,payment,bank)
    manual=ManualReconciliationService(case[0],case[1])
    with pytest.raises(ValueError):manual.unmatch_transaction(bank.id)
    with pytest.raises(ValueError):manual.match_transaction(bank.id,'invoice',case[2].id)


def test_manual_decision_cannot_finalize_provisional_bank(case):
    from cfo.services.manual_reconciliation import ManualReconciliationService
    _,bank=received(case,provisional=True)
    with pytest.raises(ValueError):ManualReconciliationService(case[0],case[1]).match_transaction(bank.id,'invoice',case[2].id)


@pytest.mark.parametrize('entity',['payment','bank'])
def test_sync_cannot_silently_change_allocated_money(case,monkeypatch,entity):
    from cfo.services.sync_engine import SyncEngine
    from cfo.services.connector_base import NormalizedPayment,NormalizedBankTransaction
    request=propose(case);execute(case,monkeypatch,request)
    payment,bank=received(case);link(case,request,payment,bank)
    engine=SyncEngine(case[0],None,case[1], 'sumit' if entity=='payment' else 'open_finance')
    with pytest.raises(ValueError):
        if entity=='payment':
            engine._upsert_payment(NormalizedPayment(external_id=payment.external_id,amount=Decimal('999'),raw_data={'changed':True}))
        else:
            engine._upsert_bank_transaction(NormalizedBankTransaction(external_id=bank.external_id,amount=Decimal('999'),raw_data={'status':'BOOKED'}))
    case[0].rollback()
    assert service(case).status(request.id)['remaining_balance']==0


def test_unknown_provider_failure_is_locked_against_retry(case,monkeypatch):
    from cfo.api.routes import open_finance
    class Broken(Provider):
        async def create_payment(self,payload):
            self.calls+=1
            raise TimeoutError('synthetic outcome unknown')
    provider=Broken();monkeypatch.setattr(open_finance,'get_open_finance_client',lambda *a:provider)
    request=propose(case);approve(case,request)
    with pytest.raises(ValueError):asyncio.run(service(case).execute(request.id))
    with pytest.raises(ValueError):asyncio.run(service(case).execute(request.id))
    assert provider.calls==1
    assert case[2].balance==1000
    with pytest.raises(ValueError):propose(case,key='retry-with-new-key')


def test_sumit_payload_uses_documented_receipt_and_correlation_fields(monkeypatch):
    from test_sumit_payment_link import _sumit
    from cfo.integrations.sumit_models import ChargeRequest
    provider=_sumit();calls=[]
    async def post(path,payload):
        calls.append((path,payload));return {'RedirectURL':'https://synthetic.invalid/pay'}
    monkeypatch.setattr(provider,'_post',post)
    async def run():
        try:
            return await provider.create_payment_link(ChargeRequest(customer_id='7',amount=Decimal('400')),
                 external_identifier='rezef-collection-1',document_type='receipt')
        finally:await provider.client.aclose()
    asyncio.run(run())
    assert calls[0][0]=='/billing/payments/beginredirect/'
    assert calls[0][1]['DocumentType']=='Receipt'
    assert calls[0][1]['ExternalIdentifier']=='rezef-collection-1'
    assert calls[0][1]['VATIncluded'] is True


def test_callable_writeback_still_requires_reviewed_approval_adapter(case,monkeypatch):
    from cfo.services import reconciliation_dispatch
    from cfo.services.manual_reconciliation import ManualReconciliationService
    _,bank=received(case)
    ManualReconciliationService(case[0],case[1]).match_transaction(bank.id,'invoice',case[2].id)
    class Unreviewed:
        async def post_bank_reconciliation(self,payload):raise AssertionError('No automatic posting allowed')
    monkeypatch.setattr(reconciliation_dispatch,'get_connector_for_org',lambda *a:(Unreviewed(),1,'sumit'))
    result=asyncio.run(reconciliation_dispatch.dispatch_reconciliation_to_sumit(case[0],case[1]))
    assert result['items'][0]['status']=='approval_required'
    assert result['confirmed']==0


def test_legacy_sumit_link_requires_same_durable_request(case,client,monkeypatch):
    from cfo.services.ai_chat_tools import _create_payment_link
    from cfo.services import document_issuance_service
    def forbidden(*a,**kw):raise AssertionError('Unapproved legacy entry point reached provider')
    monkeypatch.setattr(document_issuance_service,'get_connector_for_org',forbidden)
    with pytest.raises(ValueError):asyncio.run(_create_payment_link(case[0],case[1],invoice_id=case[2].id))
    result=client.post(f'/api/financial/invoices/{case[2].id}/payment-link',headers=case[4]['headers'])
    assert result.status_code==409,result.text


def test_automation_does_not_link_amount_only_payment(case):
    from cfo.services.financial_synthesis import link_payments_organization
    payment,_=received(case)
    result=link_payments_organization(case[0],case[1],persist=True)
    assert result['linked_count']==0
    assert result['candidates']
    assert payment.invoice_id is None


def test_candidate_does_not_recommend_issuing_another_document():
    from cfo.services.financial_synthesis import build_synthesis
    from cfo.services.bank_reconciliation import BankTxnLite,DocLite
    result=build_synthesis([BankTxnLite(1,1000,date(2026,9,6))],[DocLite(1,'invoice',1000,date(2026,9,6))],[],[])
    assert {a['type'] for a in result['required_actions']}=={'review_bank_evidence'}


def test_billing_observation_and_receipt_are_not_two_customer_credits(case,monkeypatch):
    from cfo.services.ledger_service import contact_card
    request=propose(case);execute(case,monkeypatch,request)
    payment,bank=received(case);link(case,request,payment,bank)
    case[0].add(Payment(organization_id=case[1],source='sumit',external_id='billing:42',contact_id=case[2].contact_id,
        payment_date=date(2026,9,6),amount=1000,currency='ILS',raw_data={'source_entity_type':'billing_payment'}))
    case[0].commit()
    card=contact_card(case[0],case[1],case[2].contact_id)
    assert card['closing_balance']==0


@pytest.mark.parametrize('change',['currency','source_identity'])
def test_invoice_identity_change_after_approval_stops_provider(case,monkeypatch,change):
    from cfo.api.routes import open_finance
    provider=Provider();monkeypatch.setattr(open_finance,'get_open_finance_client',lambda *a:provider)
    request=propose(case);approve(case,request)
    if change=='currency':case[2].currency='USD'
    else:case[2].external_id='different-invoice'
    case[0].commit()
    with pytest.raises(ValueError):asyncio.run(service(case).execute(request.id))
    assert provider.calls==0


def test_generic_approval_cannot_repeat_a_collection_request(case,monkeypatch):
    from cfo.services.irreversible_action_service import IrreversibleActionService
    first=propose(case);execute(case,monkeypatch,first)
    second=IrreversibleActionService(case[0],case[1]).propose(proposed_by=case[3],action_type='payment',
        payload=first.payload,idempotency_key='generic-second')
    approve(case,second)
    with pytest.raises(ValueError):asyncio.run(service(case).execute(second.id))


@pytest.mark.parametrize('raw',[
    {'source_entity_type':'billing_payment'}, {'payment_id':'42'},
])
def test_linked_billing_observation_does_not_inflate_partial_settlement(case,monkeypatch,raw):
    request=propose(case,amount='400');execute(case,monkeypatch,request)
    payment,bank=received(case,400)
    case[0].add(Payment(organization_id=case[1],source='sumit',external_id='billing:42',
        contact_id=case[2].contact_id,invoice_id=case[2].id,payment_date=date(2026,9,6),
        amount=400,currency='ILS',raw_data=raw))
    case[0].commit()
    assert link(case,request,payment,bank)['remaining_balance']==600
    assert case[2].paid_amount==400


def test_sync_keeps_receipt_linked_before_collection_allocation(case,monkeypatch):
    from cfo.services.sync_engine import SyncEngine
    from cfo.services.connector_base import NormalizedInvoice
    case[0].add(Payment(organization_id=case[1],source='sumit',external_id='receipt:earlier',
        contact_id=case[2].contact_id,invoice_id=case[2].id,payment_date=date(2026,9,1),
        amount=100,currency='ILS',method='receipt',raw_data={'document_id':'earlier','document_type':'receipt','status':'open'}))
    case[2].paid_amount=100;case[2].balance=900;case[0].commit()
    request=propose(case,amount='400');execute(case,monkeypatch,request)
    payment,bank=received(case,400)
    assert link(case,request,payment,bank)['remaining_balance']==500
    item=NormalizedInvoice(external_id=case[2].external_id,total=Decimal('1000'),
        paid_amount=Decimal('100'),balance=Decimal('900'),status='partially_paid',
        raw_data={'document_type':'invoice'})
    SyncEngine(case[0],None,case[1],'sumit')._upsert_invoice(item);case[0].commit()
    assert service(case).status(request.id)['remaining_balance']==500


@pytest.mark.parametrize('entity,change',[
    ('invoice','customer'),('invoice','document_type'),
    ('payment','customer'),('payment','document_type'),('payment','status'),
])
def test_sync_preserves_allocated_source_identity(case,monkeypatch,entity,change):
    from cfo.services.sync_engine import SyncEngine
    from cfo.services.connector_base import NormalizedInvoice,NormalizedPayment
    request=propose(case);execute(case,monkeypatch,request)
    payment,bank=received(case);link(case,request,payment,bank)
    other=Contact(organization_id=case[1],source='sumit',external_id='customer-2',name='Other customer',contact_type='customer')
    case[0].add(other);case[0].commit()
    engine=SyncEngine(case[0],None,case[1],'sumit')
    if entity=='invoice':
        item=NormalizedInvoice(external_id=case[2].external_id,total=Decimal('1000'),status='sent',
            contact_external_id='customer-2' if change=='customer' else 'customer-1',
            raw_data={'document_type':'proforma' if change=='document_type' else 'invoice'})
        update=engine._upsert_invoice
    else:
        item=NormalizedPayment(external_id=payment.external_id,amount=Decimal('1000'),method='receipt',
            contact_external_id='customer-2' if change=='customer' else 'customer-1',
            raw_data={'document_id':'42','document_type':'credit_receipt' if change=='document_type' else 'receipt',
                      'status':'cancelled' if change=='status' else 'open'})
        update=engine._upsert_payment
    with pytest.raises(ValueError,match='review'):
        update(item)
    case[0].rollback()
    assert case[2].contact_id==payment.contact_id
    assert service(case).status(request.id)['remaining_balance']==0
