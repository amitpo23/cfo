"""Documented product boundaries are checked before token/provider calls."""
import asyncio
import httpx
import pytest
from cfo.services.open_finance_client import OpenFinanceClient, OpenFinanceError


def client_for(product, plan=None, accounts=()):
    client = OpenFinanceClient('synthetic', 'synthetic', 'synthetic', provider_product=product,
        provider_plan=plan, connected_account_numbers=accounts)
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path == '/oauth/token': return httpx.Response(200, json={'accessToken': 'synthetic', 'expiresIn': 3600000})
        return httpx.Response(200, json={'id': 'payment-1', 'payUrl': 'https://synthetic.invalid/pay'})
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client, calls


@pytest.mark.parametrize('operation', ['connection', 'mandate', 'refund', 'loans'])
def test_financy_never_inherits_platform_only_operations(operation):
    client, calls = client_for('financy', 'pro')
    async def run():
        try:
            with pytest.raises(OpenFinanceError, match='product'):
                if operation == 'connection': await client.create_connection({})
                elif operation == 'mandate': await client.create_mandate({})
                elif operation == 'refund': await client.refund_payment('p', amount=10, description='refund')
                else: await client.list_customers()
        finally: await client.close()
    asyncio.run(run())
    assert calls == []


@pytest.mark.parametrize('plan', [None, 'free'])
def test_financy_plan_must_be_verified_before_using_api(plan):
    client, calls = client_for('financy', plan)
    async def run():
        try:
            with pytest.raises(OpenFinanceError, match='plan'): await client.list_accounts()
        finally: await client.close()
    asyncio.run(run()); assert calls == []


def test_financy_collection_requires_a_connected_party_account():
    client, calls = client_for('financy', 'starter', ['IL-SYNTHETIC-ACCOUNT'])
    async def run():
        try:
            with pytest.raises(OpenFinanceError, match='connected'):
                await client.create_payment({'paymentInformation': {'amount': 10, 'currency': 'ILS', 'creditorAccountNumber': 'unrelated'}})
            await client.create_payment({'paymentInformation': {'amount': 10, 'currency': 'ILS', 'creditorAccountNumber': 'IL-SYNTHETIC-ACCOUNT'}})
        finally: await client.close()
    asyncio.run(run()); assert len(calls) == 2


def test_unverified_product_cannot_create_connections_or_payments():
    client, calls = client_for('unverified')
    async def run():
        try:
            with pytest.raises(OpenFinanceError, match='product'): await client.create_payment({})
            with pytest.raises(OpenFinanceError, match='product'): await client.create_connection({})
        finally: await client.close()
    asyncio.run(run()); assert calls == []


def test_unauthorized_write_is_not_automatically_replayed():
    client, calls = client_for('open_finance')
    def handler(request):
        calls.append(request)
        if request.url.path == '/oauth/token': return httpx.Response(200, json={'accessToken': 'synthetic', 'expiresIn': 3600000})
        return httpx.Response(401, json={'message': 'unauthorized'})
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async def run():
        try:
            with pytest.raises(OpenFinanceError): await client.create_payment({})
        finally: await client.close()
    asyncio.run(run())
    assert len([r for r in calls if r.url.path == '/v2/payments']) == 1


def test_configuration_persists_product_without_exposing_credentials(client, fresh_org, monkeypatch):
    from cfo.api.routes import cfo_sync
    from cfo.database import SessionLocal
    from cfo.models import IntegrationConnection
    monkeypatch.setattr(cfo_sync, '_kickoff_onboarding', lambda *args: None)
    identity = fresh_org()
    response = client.post('/api/integration/open-finance/configure', headers=identity['headers'], json={
        'client_id': 'synthetic-id', 'client_secret': 'synthetic-secret', 'user_id': 'synthetic-user',
        'provider_product': 'financy', 'provider_plan': 'pro'})
    assert response.status_code == 200
    assert 'synthetic-secret' not in response.text
    with SessionLocal() as db:
        config = db.query(IntegrationConnection).filter_by(organization_id=identity['org_id'], source='open_finance').one().config
        assert config['provider_product'] == 'financy' and config['provider_plan'] == 'pro'
    status = client.get('/api/integration/status', headers=identity['headers']).json()
    assert status['open_finance_product']['product'] == 'financy'
    assert status['open_finance_product']['connection_creation'] == 'financy_portal'


def test_inactive_configuration_cannot_fall_back_to_environment(fresh_org):
    from cfo.api.routes.open_finance import get_open_finance_client
    from cfo.database import SessionLocal
    from cfo.models import IntegrationConnection
    from fastapi import HTTPException
    identity = fresh_org()
    with SessionLocal() as db:
        db.add(IntegrationConnection(organization_id=identity['org_id'], source='open_finance', status='inactive'))
        db.commit()
        with pytest.raises(HTTPException) as error: get_open_finance_client(db, identity['org_id'])
        assert error.value.status_code == 409


@pytest.mark.parametrize('product,status', [('financy', 'active'), ('open_finance', 'inactive'), ('unverified', 'active')])
def test_onboarding_does_not_change_identity_or_reactivate_unreviewed_connection(fresh_org, product, status):
    from cfo.services.open_finance_onboarding import start_bank_connection
    from cfo.database import SessionLocal
    from cfo.models import IntegrationConnection
    from cfo.services.credentials_vault import encrypt_credentials
    with SessionLocal() as db:
        org = fresh_org()['org_id']
        conn = IntegrationConnection(organization_id=org, source='open_finance', status=status,
            config={'provider_product': product, 'provider_plan': 'pro'},
            credentials_encrypted=encrypt_credentials({}))
        db.add(conn); db.commit()
        original = conn.credentials_encrypted
        with pytest.raises(OpenFinanceError, match='configuration|portal|inactive'):
            asyncio.run(start_bank_connection(db, org))
        db.refresh(conn)
        assert conn.credentials_encrypted == original and conn.status == status
