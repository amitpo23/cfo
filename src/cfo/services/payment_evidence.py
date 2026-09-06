"""Payment-request readback is not evidence of creditor receipt."""

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
