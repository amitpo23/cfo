"""Legacy in-memory payment routes cannot claim durable financial outcomes."""
import pytest


@pytest.mark.parametrize('path,body', [
    ('requests', {'customer_id': '1', 'customer_name': 'Synthetic', 'customer_email': 'fake@example.invalid', 'amount': 10, 'description': 'Synthetic'}),
    ('requests/missing/send', {}),
    ('demands', {'customer_id': '1', 'customer_name': 'Synthetic', 'amount': 10, 'due_date': '2026-09-06', 'description': 'Synthetic'}),
    ('demands/missing/send', {}),
    ('demands/missing/mark-paid?payment_method=bank_transfer', {}),
])
def test_legacy_payment_writes_require_the_durable_collection_flow(client, fresh_org, path, body, monkeypatch):
    from cfo.api.routes import financial_operations
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('Legacy prototype must not be constructed')
    monkeypatch.setattr(financial_operations, 'PaymentRequestService', forbidden)
    response = client.post('/api/financial/payments/' + path, headers=fresh_org()['headers'], json=body)
    assert response.status_code == 409
    assert calls == []


def test_sumit_configuration_requires_an_active_admin(client, fresh_org, monkeypatch):
    from cfo.database import SessionLocal
    from cfo.models import User, UserRole, OrganizationMembership
    from cfo.api.routes import cfo_sync
    identity = fresh_org()
    with SessionLocal() as db:
        user = db.query(User).filter_by(organization_id=identity['org_id']).one()
        user.role = UserRole.USER
        db.query(OrganizationMembership).filter_by(organization_id=identity['org_id'], user_id=user.id).one().role = UserRole.USER
        db.commit()
    calls = []
    monkeypatch.setattr(cfo_sync, '_kickoff_onboarding', lambda *args: calls.append(True))
    response = client.post('/api/integration/sumit/configure', headers=identity['headers'],
        json={'api_key': 'synthetic', 'company_id': 'synthetic'})
    assert response.status_code == 403
    assert calls == []
