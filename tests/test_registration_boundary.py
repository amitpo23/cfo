"""Registration authorizes a new tenant, never membership in an existing one."""
import pytest
from pydantic import ValidationError

from cfo.config import Settings
from cfo.database import SessionLocal
from cfo.models import Organization, OrganizationMembership, User


@pytest.mark.parametrize("requested_id", [0, -1, 999999])
def test_registration_rejects_any_explicit_organization(client, owner, requested_id):
    response = client.post('/api/admin/auth/register', json={
        'email': f'forbidden-org-{requested_id}@example.com',
        'password': 'secret123', 'full_name': 'Uninvited',
        'organization_id': requested_id,
    })
    assert response.status_code == 403


def test_registration_cannot_join_or_modify_an_existing_tenant(client, fresh_org):
    target = fresh_org()['org_id']
    with SessionLocal() as db:
        before = dict(db.get(Organization, target).settings or {})
        members = db.query(OrganizationMembership).filter_by(organization_id=target).count()
    response = client.post('/api/admin/auth/register', json={
        'email': 'uninvited-review@example.com', 'password': 'secret123',
        'full_name': 'Uninvited', 'organization_id': target,
        'selected_plan': 'office', 'payment_status': 'paid',
    })
    assert response.status_code == 403
    with SessionLocal() as db:
        assert db.query(User).filter_by(email='uninvited-review@example.com').first() is None
        assert db.get(Organization, target).settings == before
        assert db.query(OrganizationMembership).filter_by(organization_id=target).count() == members


@pytest.mark.parametrize('deployment_env', ['production', 'preview'])
def test_public_deployment_refuses_authentication_bypass(monkeypatch, deployment_env):
    monkeypatch.setenv('VERCEL', '1')
    monkeypatch.setenv('VERCEL_ENV', deployment_env)
    with pytest.raises(ValidationError, match='AUTH_BYPASS_ENABLED'):
        Settings(_env_file=None,
                 database_url='postgresql+psycopg://fake:fake@localhost/fake',
                 jwt_secret_key='j' * 40, credentials_encryption_key='k' * 40,
                 cron_secret='fake', open_finance_webhook_secret='fake',
                 auth_bypass_enabled=True)
