"""Guarded synthetic PostgreSQL proof for source-bound filing claims and evidence."""
import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from offline_guard import isolate_offline_audit
isolate_offline_audit()
from environment import test_engine, evidence_path
from sqlalchemy.orm import Session
from cfo.models import Expense, IrreversibleActionRequest, Organization, OrganizationMembership, OrganizationSigningAuthority, User, UserRole
from cfo.services.document_intake import DocumentIntakeService
from cfo.services.expense_filing_workflow import ExpenseFilingWorkflow
from cfo.services.irreversible_action_service import IrreversibleActionService, ActionConflictError, ActionStateError

engine = test_engine()
with Session(engine) as db:
    org = Organization(name='SYNTHETIC FILING CONCURRENCY', settings={'synthetic': True},
        api_credentials={'company_id': '123', 'api_key': 'synthetic-only'})
    db.add(org); db.flush()
    actors = [User(organization_id=org.id, email=f'{uuid4()}@example.invalid', full_name='Synthetic',
        password_hash='not-a-login-hash', role=UserRole.ADMIN, is_active=True) for _ in range(2)]
    db.add_all(actors); db.flush()
    for actor in actors:
        db.add(OrganizationMembership(organization_id=org.id, user_id=actor.id, role=UserRole.ADMIN, status='active'))
    db.add(OrganizationSigningAuthority(organization_id=org.id, user_id=actors[1].id,
        authority_type='authorized_signer', action_types=['sumit_writeback'], is_active=True, granted_by_user_id=actors[0].id))
    db.commit(); org_id, actor_id, signer_id = org.id, actors[0].id, actors[1].id
    source = DocumentIntakeService(db, org_id).receive(b'%PDF synthetic concurrent expense', media_type='application/pdf', source='upload')
    reviewed = DocumentIntakeService(db, org_id).review(source['document_id'], expected_version=1, actor_id=actor_id,
        reason='Synthetic reviewed source fields before provider draft filing', fields={
            'supplier_name': 'Synthetic office supplier', 'supplier_tax_id': '520022732', 'invoice_number': 'PG-FILING-1',
            'expense_date': '2026-09-07', 'currency': 'ILS', 'net_amount': 100, 'vat_amount': 18,
            'amount_total': 118, 'document_type': 'tax_invoice'})
    expense_id = reviewed['expense_id']
barrier = Barrier(2)
def propose():
    barrier.wait(timeout=10)
    with Session(engine) as db:
        return ExpenseFilingWorkflow(db, org_id).propose(expense_id, actor_id=actor_id,
            reason='Synthetic reviewed draft request; official books remain unverified')['approval_request_id']
with ThreadPoolExecutor(max_workers=2) as pool:
    first, second = [f.result(timeout=20) for f in [pool.submit(propose), pool.submit(propose)]]
assert first == second
with Session(engine) as db:
    IrreversibleActionService(db, org_id).approve(first, approved_by=db.get(User, signer_id))

entered, release = Event(), Event(); calls = []
class FakeProvider:
    company_id = '123'
    async def add_expense(self, request):
        calls.append({'invoice_number': request.invoice_number, 'is_draft': request.is_draft})
        entered.set(); assert release.wait(timeout=15)
        return {'DocumentID': 9001, 'expense_id': '9001'}
def connector(db, organization_id, **kwargs):
    assert organization_id == org_id
    return FakeProvider(), None, 'sumit'
def execute():
    with Session(engine) as db:
        return asyncio.run(ExpenseFilingWorkflow(db, org_id).execute(expense_id, approval_id=first, actor_id=actor_id))
with patch('cfo.services.sync_engine.get_connector_for_org', connector):
    with ThreadPoolExecutor(max_workers=2) as pool:
        started = pool.submit(execute); assert entered.wait(timeout=10)
        repeated = pool.submit(execute)
        try:
            repeated.result(timeout=10)
            raise AssertionError('Concurrent execution reached the provider twice')
        except ActionConflictError:
            pass
        finally:
            release.set()
        assert started.result(timeout=15)['status'] == 'submitted'
assert calls == [{'invoice_number': 'PG-FILING-1', 'is_draft': True}]
engine.dispose()
with Session(engine) as db:
    row = db.get(Expense, expense_id); action = db.get(IrreversibleActionRequest, first)
    assert row.status == 'submitted' and row.sumit_expense_id == '9001'
    assert action.status == 'executed' and action.execution_result['source_matches_approved'] is True
    assert action.execution_result['official_books_verified'] is False
    assert action.payload['provider_target']['company_id'] == '123'
    assert db.query(IrreversibleActionRequest).filter_by(organization_id=org_id).count() == 1
# A signer withdrawal races the execution claim; precisely one may win.
for attempt in range(6):
    with Session(engine) as db:
        service = IrreversibleActionService(db, org_id)
        action = service.propose(proposed_by=db.get(User, actor_id), action_type='sumit_writeback',
            payload={'operation': 'synthetic_local_claim_race', 'amount': '1', 'currency': 'ILS'},
            idempotency_key=f'synthetic-withdrawal-{attempt}')
        service.approve(action.id, approved_by=db.get(User, signer_id)); request_id = action.id
    start = Barrier(2)
    def decide(withdraw):
        with Session(engine) as db:
            start.wait(timeout=10)
            service = IrreversibleActionService(db, org_id)
            try:
                if withdraw:
                    return service.reject(request_id, rejected_by=db.get(User, signer_id),
                        reason='Synthetic signer withdrawal before any provider execution').status
                return service.claim_for_execution(request_id).status
            except ActionStateError:
                return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [f.result(timeout=20) for f in [pool.submit(decide, True), pool.submit(decide, False)]]
    assert outcomes.count('conflict') == 1, outcomes
    with Session(engine) as db:
        action = db.get(IrreversibleActionRequest, request_id)
        assert action.status in ('executing', 'rejected')
        if action.status == 'rejected':
            assert action.execution_started_at is None
            assert action.policy_approved_decision['withdrawal']['actor_id'] == signer_id
result = {'status': 'passed', 'synthetic_only': True, 'provider_is_fake': True, 'real_provider_requests': 0,
    'fake_provider_requests': len(calls), 'checks': ['concurrent proposals share one durable approval',
        'distinct signing approval', 'overlapping execution submits exactly once', 'six signer-withdrawal versus execution races admit one winner',
        'source and destination identity survive connection-pool restart', 'provider acknowledgement remains unverified'],
    'official_books_verified': False}
evidence_path('2026-09-07-expense-filing-concurrency.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result)); engine.dispose()
