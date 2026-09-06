"""Checkout is a single-use, server-verified entitlement, never a client claim."""
import pytest
from cfo.database import SessionLocal
from cfo.models import Organization
from cfo.config import settings


@pytest.fixture(autouse=True)
def ensure_owner(owner):
    pass


def signup(client, email, **kwargs):
    return client.post('/api/admin/auth/register', json={
        'email': email, 'password': 'secret123', 'full_name': 'Checkout', **kwargs})


def test_client_cannot_activate_subscription(client):
    response = signup(client, 'fake-paid@example.com', payment_status='paid')
    assert response.status_code == 201
    with SessionLocal() as db:
        org = db.get(Organization, response.json()['user']['organization_id'])
        assert org.settings['subscription_status'] == 'pending'


def test_fabricated_mock_is_rejected(client):
    assert signup(client, 'fake-mock@example.com', checkout_session_id='mock_fabricated').status_code == 403


def test_mock_is_single_use_and_cannot_be_upgraded_by_client(client):
    checkout = client.post('/api/admin/billing/checkout', json={
        'selected_plan':'company_up_to_2_5m'}).json()
    session_id = checkout['checkout_session_id']
    response = signup(client, 'real-mock@example.com', checkout_session_id=session_id,
                      payment_status='paid', selected_plan='office')
    assert response.status_code == 201
    with SessionLocal() as db:
        org = db.get(Organization, response.json()['user']['organization_id'])
        assert org.settings['selected_plan'] == 'company_up_to_2_5m'
        assert org.settings['subscription_status'] == 'pending'
    assert signup(client, 'reuse-mock@example.com', checkout_session_id=session_id).status_code == 409


@pytest.fixture
def stripe(monkeypatch):
    import httpx
    monkeypatch.setattr(settings, 'stripe_secret_key', 'sk_test_fake')
    monkeypatch.setattr(settings, 'stripe_price_company_up_to_2_5m', 'price_small')
    session = {'id':'cs_test_boundary', 'status':'complete', 'payment_status':'paid',
               'mode':'subscription', 'customer_details':{'email':'buyer@example.com'},
               'subscription':{'id':'sub_boundary','status':'active'}, 'line_items':{'data':[{'price':{'id':'price_small'}, 'quantity':1}]}}
    async def get(self, url, **kwargs):
        return httpx.Response(200, json=session, request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    return session


def test_stripe_binds_email_price_and_rejects_replay(client, stripe):
    assert signup(client, 'thief@example.com', checkout_session_id=stripe['id']).status_code == 403
    response = signup(client, 'buyer@example.com', checkout_session_id=stripe['id'], selected_plan='office')
    assert response.status_code == 201
    with SessionLocal() as db:
        org = db.get(Organization, response.json()['user']['organization_id'])
        assert org.settings['selected_plan'] == 'company_up_to_2_5m'
        assert org.settings['subscription_status'] == 'active'
    assert signup(client, 'buyer@example.com', checkout_session_id=stripe['id']).status_code == 409


@pytest.mark.parametrize('field,value', [('mode','payment'), ('status','open'), ('payment_status','unpaid'),
                                        ('line_items', {'data':[{'price':{'id':'unknown'}}]})])
def test_stripe_invalid_entitlement_rejected(client, stripe, field, value):
    stripe[field] = value
    assert signup(client, 'buyer@example.com', checkout_session_id=stripe['id']).status_code == 403


def test_signed_subscription_events_are_idempotent_and_ignore_older_state(client, fresh_org, monkeypatch):
    import hashlib, hmac, json, time
    from cfo.models import BillingCheckout
    monkeypatch.setattr(settings, 'stripe_webhook_secret', 'whsec_synthetic')
    org_id = fresh_org()['org_id']
    with SessionLocal() as db:
        db.add(BillingCheckout(session_id='cs_events', email='events@example.com', selected_plan='office',
                              payment_status='paid', subscription_id='sub_events', organization_id=org_id))
        db.commit()
    def send(event_id, created, state, signature=True, age=0):
        raw = json.dumps({'id':event_id, 'created':created, 'type':'customer.subscription.updated',
                          'data':{'object':{'id':'sub_events','status':state}}}).encode()
        stamp = int(time.time()) - age
        digest = hmac.new(b'whsec_synthetic', str(stamp).encode()+b'.'+raw, hashlib.sha256).hexdigest()
        return client.post('/api/admin/billing/webhook', content=raw,
                           headers={'content-type':'application/json','Stripe-Signature':f't={stamp},v1={digest if signature else "bad"}'})
    assert send('evt_bad', 10, 'active', signature=False).status_code == 400
    assert send('evt_stale_sig', 10, 'active', age=600).status_code == 400
    assert send('evt_new', 30, 'canceled').status_code == 200
    assert send('evt_new', 30, 'canceled').json()['duplicate'] is True
    assert send('evt_old', 20, 'active').status_code == 200
    with SessionLocal() as db:
        assert db.get(Organization, org_id).settings['subscription_status'] == 'canceled'
