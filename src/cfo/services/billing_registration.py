"""Verify checkout entitlements before the registration transaction consumes them."""
from datetime import datetime, timedelta
import os
import re
import httpx
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from ..config import settings
from ..models import BillingCheckout


def configured_prices():
    return {key: value for key, value in {
        'company_up_to_2_5m': settings.stripe_price_company_up_to_2_5m,
        'company_above_2_5m': settings.stripe_price_company_above_2_5m,
        'office': settings.stripe_price_office,
    }.items() if value}


async def verify_checkout(db, session_id: str, email: str):
    email = email.strip().casefold()
    row = db.get(BillingCheckout, session_id)
    if session_id.startswith('mock_'):
        if os.getenv('VERCEL_ENV') == 'production' or row is None:
            raise HTTPException(403, 'Checkout session could not be verified')
        if row.created_at < datetime.utcnow() - timedelta(hours=24):
            raise HTTPException(403, 'Checkout session expired')
        if row.email and row.email != email:
            raise HTTPException(403, 'Checkout email does not match registration')
    else:
        if not settings.stripe_secret_key or not re.fullmatch(r'cs_[A-Za-z0-9_]+', session_id):
            raise HTTPException(403, 'Checkout session could not be verified')
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f'https://api.stripe.com/v1/checkout/sessions/{session_id}',
                    headers={'Authorization': f'Bearer {settings.stripe_secret_key}'},
                    params=[('expand[]', 'line_items'), ('expand[]', 'subscription')])
            response.raise_for_status()
            session = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, 'Checkout verification is temporarily unavailable') from exc
        items = (session.get('line_items') or {}).get('data') or []
        plans = [plan for plan, price in configured_prices().items()
                 if len(items) == 1 and (items[0].get('price') or {}).get('id') == price
                 and items[0].get('quantity') == 1]
        provider_email = (session.get('customer_details') or {}).get('email') or session.get('customer_email') or ''
        subscription = session.get('subscription') or {}
        if (session.get('id') != session_id or session.get('mode') != 'subscription'
                or session.get('status') != 'complete'
                or session.get('payment_status') not in {'paid', 'no_payment_required'}
                or not isinstance(subscription, dict) or subscription.get('status') not in {'active', 'trialing'}
                or not subscription.get('id') or provider_email.strip().casefold() != email
                or len(plans) != 1 or (session.get('line_items') or {}).get('has_more')):
            raise HTTPException(403, 'Checkout entitlement does not match registration')
        if row is None:
            row = BillingCheckout(session_id=session_id, email=email, selected_plan=plans[0],
                                  payment_status='paid', subscription_id=subscription['id'])
            db.add(row)
            try:
                db.flush()  # Unique session ID arbitrates concurrent redemption.
            except IntegrityError as exc:
                db.rollback()
                raise HTTPException(409, 'Checkout session was already claimed') from exc
        elif row.email != email or row.selected_plan != plans[0]:
            raise HTTPException(403, 'Checkout entitlement does not match registration')
    if row.organization_id is not None:
        raise HTTPException(409, 'Checkout session was already claimed')
    return row


def consume_checkout(db, checkout, organization_id):
    updated = db.query(BillingCheckout).filter(
        BillingCheckout.session_id == checkout.session_id,
        BillingCheckout.organization_id.is_(None),
    ).update({'organization_id': organization_id}, synchronize_session=False)
    if updated != 1:
        db.rollback()
        raise HTTPException(409, 'Checkout session was already claimed')


def apply_subscription_event(db, raw: bytes, signature: str):
    """Authenticate raw Stripe snapshots, deduplicate and reject stale state."""
    import hashlib
    import hmac
    import json
    import time
    from ..models import BillingWebhookReceipt, Organization
    if not settings.stripe_webhook_secret:
        raise HTTPException(503, 'Stripe webhook is not configured')
    try:
        fields = [item.split('=', 1) for item in signature.split(',')]
        stamps = [value for key, value in fields if key == 't']
        if len(stamps) != 1 or abs(time.time() - int(stamps[0])) > 300:
            raise ValueError('invalid timestamp')
        expected = hmac.new(settings.stripe_webhook_secret.encode(), stamps[0].encode()+b'.'+raw, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, value) for key, value in fields if key == 'v1'):
            raise ValueError('invalid signature')
        event = json.loads(raw)
        event_id, created = event['id'], event['created']
        if not isinstance(event_id, str) or not isinstance(created, int):
            raise ValueError('invalid event')
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(400, 'Invalid Stripe webhook') from exc
    digest = hashlib.sha256(raw).hexdigest()
    receipt = db.get(BillingWebhookReceipt, event_id)
    if receipt:
        if receipt.payload_sha256 != digest:
            raise HTTPException(400, 'Webhook event ID conflicts with a previous payload')
        return {'received': True, 'duplicate': True}
    if event.get('type') not in {'customer.subscription.updated', 'customer.subscription.deleted', 'customer.subscription.created'}:
        return {'received': True, 'ignored': True}
    obj = (event.get('data') or {}).get('object') or {}
    state = 'canceled' if event['type'] == 'customer.subscription.deleted' else obj.get('status')
    if state not in {'active','trialing','past_due','unpaid','canceled','incomplete','incomplete_expired','paused'}:
        raise HTTPException(400, 'Unrecognized subscription state')
    checkout = db.query(BillingCheckout).filter_by(subscription_id=obj.get('id')).with_for_update().first()
    if not checkout or checkout.organization_id is None:
        raise HTTPException(503, 'Subscription registration is not yet available; retry delivery')
    if created > checkout.webhook_created:
        org = db.query(Organization).filter_by(id=checkout.organization_id).with_for_update().one()
        org.settings = {**(org.settings or {}), 'subscription_status': state}
        checkout.webhook_created = created
    elif created == checkout.webhook_created:
        # Distinct events can share a second; do not guess their ordering.
        org = db.query(Organization).filter_by(id=checkout.organization_id).with_for_update().one()
        if (org.settings or {}).get('subscription_status') != state:
            org.settings = {**(org.settings or {}), 'subscription_status':'pending', 'billing_review_required':True}
    db.add(BillingWebhookReceipt(event_id=event_id, payload_sha256=digest))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        receipt = db.get(BillingWebhookReceipt, event_id)
        if receipt and receipt.payload_sha256 == digest:
            return {'received': True, 'duplicate': True}
        raise HTTPException(409, 'Concurrent webhook delivery must be retried') from exc
    return {'received': True, 'duplicate': False}
