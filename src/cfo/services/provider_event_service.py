"""Authenticated provider observations; no network, inferred joins or money writes."""
import hashlib
import json

from sqlalchemy.exc import IntegrityError

from ..config import settings
from ..models import BankConnection, IntegrationConnection, OpenFinancePayment, Organization, ProviderEventReceipt
from .credentials_vault import decrypt_credentials
from .payment_evidence import payment_outcome

FINAL_PAYMENT_STATUSES = {'ACSC', 'ACCC', 'RJCT', 'CANC', 'ERROR'}
CONNECTION_STATUSES = {'ACTIVE', 'COMPLETED', 'INACTIVE', 'INIT', 'PENDING', 'EXPIRED',
                       'REJECTED', 'ERROR', 'REVOKED', 'CANCELLED'}
FINAL_CONNECTION_STATUSES = {'EXPIRED', 'REVOKED', 'CANCELLED', 'REJECTED'}


def resolve_provider_organization(db, source, external_user):
    """One active credential owner; provider tenants are never local tenant IDs."""
    if not external_user:
        return None
    key = 'user_id' if source == 'open_finance' else 'company_id'
    rows = db.query(IntegrationConnection).filter_by(source=source).all()
    matches = set()
    for row in rows:
        credentials = decrypt_credentials(row.credentials_encrypted) or {}
        identity = credentials.get(key)
        if not identity and row.organization_id == 1:
            identity = getattr(settings, f'{source}_{key}', None)
        if row.status == 'active' and identity and str(identity) == str(external_user):
            matches.add(row.organization_id)
    # Legacy env-only pilot is allowed only if no explicit configuration overrides it.
    if not any(row.organization_id == 1 for row in rows):
        identity = getattr(settings, f'{source}_{key}', None)
        if identity and str(identity) == str(external_user) and db.query(Organization).filter_by(id=1).first():
            matches.add(1)
    return next(iter(matches)) if len(matches) == 1 else None


def record_open_finance_event(db, event):
    """Persist evidence and conservatively update the provider observation plane.

    The documented callback has no ordering sequence or authoritative monetary
    fields. Conflicting final states and unknown codes therefore require review.
    A status event cannot link a SUMIT payment or bank movement by coincident ID.
    """
    org_id = resolve_provider_organization(db, 'open_finance', event.get('userId'))
    if org_id is None:
        return {'handled': False, 'reason': 'unresolvable_org'}
    # Serialize distinct deliveries for this integration, including first payment creation.
    db.query(IntegrationConnection).filter_by(organization_id=org_id, source='open_finance').with_for_update().first()
    connection_id = event.get('connectionId')
    connection = None
    if connection_id:
        connection = db.query(BankConnection).filter_by(organization_id=org_id,
            source='open_finance', connection_id=connection_id).with_for_update().first()
        if connection is None:
            return {'handled': False, 'reason': 'connection_identity_conflict'}
    payment_id = event.get('paymentId')
    if payment_id:
        entity_type, external_id = 'payment', str(payment_id)
    elif connection_id:
        entity_type, external_id = 'connection', str(connection_id)
    else:
        return {'handled': False, 'reason': 'unrecognized_event_type'}
    fingerprint = hashlib.sha256(json.dumps(event, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if db.query(ProviderEventReceipt).filter_by(organization_id=org_id, source='open_finance', fingerprint=fingerprint).first():
        return {'handled': False, 'reason': 'duplicate_event', 'org_id': org_id}
    # Whitelist documented evidence fields; unexpected data never becomes instructions,
    # credentials, an amount, or a new source relationship.
    evidence = {key: event[key] for key in ('paymentId', 'paymentStatus', 'requestStatus', 'userId',
        'orgId', 'bankName', 'paymentError', 'connectionId', 'connectionStatus', 'connectionError') if key in event}
    disposition = 'applied'
    if payment_id:
        row = db.query(OpenFinancePayment).filter_by(organization_id=org_id,
            external_payment_id=external_id).with_for_update().first()
        code = str(event.get('paymentStatus') or '').upper()
        if payment_outcome({'paymentStatus': code})['money_status'] == 'unknown':
            disposition = 'review_required'
        elif row and row.status in FINAL_PAYMENT_STATUSES and row.status != code:
            # ACSC -> ACCC strengthens settlement evidence; a reversal/failure is
            # a separate event needing bank/receipt review, not a silent overwrite.
            if (row.status, code) != ('ACSC', 'ACCC'):
                disposition = 'review_required'
        if row is None:
            row = OpenFinancePayment(organization_id=org_id, external_payment_id=external_id)
            db.add(row)
        if disposition == 'applied':
            row.status = code
            row.raw_data = {**(row.raw_data or {}), **evidence, 'verification_scope': 'provider_observation'}
    else:
        code = str(event.get('connectionStatus') or '').upper()
        if code not in CONNECTION_STATUSES or (connection.status in FINAL_CONNECTION_STATUSES and code != connection.status):
            disposition = 'review_required'
        else:
            connection.status = code
            connection.raw_data = {**(connection.raw_data or {}), 'status_event': evidence}
            # Consent state is not a successful fetch; never advance last_refresh_at.
    receipt = ProviderEventReceipt(organization_id=org_id, source='open_finance', entity_type=entity_type,
        external_id=external_id, fingerprint=fingerprint, disposition=disposition, evidence=evidence)
    db.add(receipt)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.query(ProviderEventReceipt).filter_by(organization_id=org_id, source='open_finance', fingerprint=fingerprint).first():
            return {'handled': False, 'reason': 'duplicate_event', 'org_id': org_id}
        raise
    return {'handled': disposition == 'applied', 'reason': disposition, 'event': f'{entity_type}_status',
            'org_id': org_id, 'event_receipt_id': receipt.id, 'sync_status': 'awaiting_budgeted_sync'}
