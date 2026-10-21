"""Payment-request readback is not evidence of creditor receipt."""

def accounting_payment_parts(payment):
    """Read-only projections keep split bank settlements in their actual periods."""
    from datetime import date
    from decimal import Decimal
    from types import SimpleNamespace
    raw = payment.raw_data or {}
    if raw.get('source_entity_type') != 'reviewed_payable_settlement':
        return [payment]
    reversed_ids = {e['bank_transaction_id'] for e in raw.get('reversals', [])}
    parts = []
    for entry in raw.get('settlements', []):
        if entry['bank_transaction_id'] in reversed_ids:
            continue
        fields = {k: getattr(payment, k) for k in ('id', 'organization_id', 'source', 'external_id',
            'invoice_id', 'bill_id', 'contact_id', 'currency', 'method', 'reference', 'raw_data')}
        fields.update(amount=Decimal(entry['amount']), payment_date=date.fromisoformat(entry['bank_date']),
            settlement_bank_id=entry['bank_transaction_id'])
        parts.append(SimpleNamespace(**fields))
    return parts

def payment_outcome(readback: dict) -> dict:
    code = str(readback.get('paymentStatus') or readback.get('status') or '').upper()
    state = {'ACCC': 'provider_settled', 'ACSC': 'debtor_settled',
             'RJCT': 'failed', 'ERROR': 'failed', 'CANC': 'cancelled'}.get(code)
    if state is None:
        state = 'pending' if code in {'INIT','RCVD','PATC','PENDING','PART','ACTC','ACSP','ACWC','ACFC','ACCP'} else 'unknown'
    return {'verification_scope': 'payment_request', 'provider_status': code or None,
            'money_status': state, 'creditor_receipt_verified': False}


def is_accounting_payment(payment) -> bool:
    """A billing observation is not another accounting receipt.

    The current SUMIT schema cannot relate these observations to receipts.
    Keep them available as source evidence without counting a second credit.
    """
    raw = getattr(payment, 'raw_data', None) or {}
    legacy_billing = (raw.get('payment_id') and not raw.get('document_id')
                      and getattr(payment, 'method', None) != 'receipt')
    return not (getattr(payment, 'source', None) == 'sumit' and
                (raw.get('source_entity_type') == 'billing_payment' or legacy_billing))
