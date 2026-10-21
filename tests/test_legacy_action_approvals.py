"""Legacy provider routes must obey the durable approval boundary."""
import pytest

from cfo.api import app
from cfo.api.dependencies import get_sumit_integration
from cfo.database import SessionLocal
from cfo.models import IrreversibleActionRequest, User, UserRole
from cfo.services import membership_service
from cfo.services.irreversible_action_service import IrreversibleActionService


@pytest.fixture
def fake_sumit():
    calls = []
    class Fake:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def cancel_recurring(self, recurring_id, customer_id=None):
            calls.append(recurring_id)
            return {'accepted': True}
    app.dependency_overrides[get_sumit_integration] = lambda: Fake()
    yield calls
    app.dependency_overrides.pop(get_sumit_integration, None)


def test_cancel_refuses_missing_approval_before_provider(client, owner, fake_sumit):
    response = client.post('/api/payments/recurring/17/cancel', headers=owner['headers'])
    assert response.status_code == 409
    assert fake_sumit == []


def test_cancel_requires_matching_intent_and_executes_once(client, owner, fake_sumit):
    with SessionLocal() as db:
        actor = db.get(User, owner['user']['id'])
        proposer = User(organization_id=actor.organization_id, email='cancel-proposer@example.com',
                        password_hash='unused', full_name='Proposer', role=UserRole.ADMIN)
        db.add(proposer)
        db.flush()
        membership_service.grant(db, organization_id=actor.organization_id, user_id=proposer.id,
                                 role=UserRole.ADMIN, granted_by_user_id=actor.id)
        db.commit()
        service = IrreversibleActionService(db, actor.organization_id)
        row = service.propose(proposed_by=proposer, action_type='recurring_cancel',
                              payload={'operation':'sumit.recurring.cancel','recurring_id':'17'},
                              idempotency_key='legacy-cancel-review')
        service.approve(row.id, approved_by=actor)
        request_id = row.id
    headers = {**owner['headers'], 'X-Rezef-Approval-Id': str(request_id)}
    assert client.post('/api/payments/recurring/18/cancel', headers=headers).status_code == 409
    assert fake_sumit == []
    response = client.post('/api/payments/recurring/17/cancel', headers=headers)
    assert response.status_code == 200
    assert response.headers['X-Rezef-Approval-Status'] == 'executed_unverified'
    assert fake_sumit == ['17']
    assert client.post('/api/payments/recurring/17/cancel', headers=headers).status_code == 409
    assert fake_sumit == ['17']
    with SessionLocal() as db:
        assert db.get(IrreversibleActionRequest, request_id).status == 'executed'


@pytest.mark.parametrize('method,path,body', [
    ('delete','/api/open-finance/payments/p1',None),
    ('post','/api/open-finance/payments/p1/refund',{'amount':10}),
    ('post','/api/open-finance/payments/init',{'amount':10}),
    ('post','/api/open-finance/mandates',{'amount':10}),
    ('delete','/api/open-finance/mandates/m1',None),
    ('post','/api/accounting/documents/17/cancel',None),
    ('post','/api/accounting/documents/17/move-to-books',None),
])
def test_legacy_mutations_fail_closed_before_provider(client, owner, fake_sumit, method, path, body):
    response = client.request(method, path, headers=owner['headers'], json=body)
    assert response.status_code == 409, response.text
    assert 'approval' in response.text.lower()
    assert fake_sumit == []


def test_approval_proposal_rejects_nested_raw_card_data(owner):
    from cfo.services.irreversible_action_service import ActionValidationError
    with SessionLocal() as db:
        actor = db.get(User, owner['user']['id'])
        service = IrreversibleActionService(db, actor.organization_id)
        with pytest.raises(ActionValidationError, match='stored payment method'):
            service.propose(proposed_by=actor, action_type='payment',
                            payload={'amount':10, 'arguments':{'request':{'card':{'card_number':'4111111111111111','cvv':'123'}}}},
                            idempotency_key='forbidden-raw-card')
        assert db.query(IrreversibleActionRequest).filter_by(idempotency_key='forbidden-raw-card').first() is None
