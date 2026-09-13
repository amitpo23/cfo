"""Saved supplier-payment evidence shared by the UI and Moshko. No provider calls."""
from ..models import Account, BankTransaction, Bill, Contact, IrreversibleActionRequest
from .payable_settlement import OPERATION, PayableSettlementService


def payable_workbench(db, organization_id, *, limit=100, offset=0):
    if not 1 <= limit <= 200 or offset < 0:
        raise ValueError('Use limit 1–200 and a nonnegative offset')
    queries = {
        'bills': db.query(Bill).filter_by(organization_id=organization_id, source='sumit'),
        'requests': db.query(IrreversibleActionRequest).filter(
            IrreversibleActionRequest.organization_id == organization_id,
            IrreversibleActionRequest.payload['operation'].as_string() == OPERATION),
        'bank_movements': db.query(BankTransaction).filter(BankTransaction.organization_id == organization_id,
            BankTransaction.source == 'open_finance', BankTransaction.amount < 0),
        'funding_accounts': db.query(Account).filter_by(organization_id=organization_id, source='open_finance'),
    }
    counts = {key: query.count() for key, query in queries.items()}
    rows = {key: query.order_by(query.column_descriptions[0]['entity'].id.desc()).offset(offset).limit(limit).all()
        for key, query in queries.items()}
    vendors = {v.id: v for v in db.query(Contact).filter_by(organization_id=organization_id)}
    service = PayableSettlementService(db, organization_id)
    return {'organization_id': organization_id, 'sync_triggered': False, 'official_books_verified': False,
        'pagination': {'limit': limit, 'offset': offset, 'counts': counts,
            'has_more': any(n > offset + limit for n in counts.values())},
        'bills': [{'id': b.id, 'external_id': b.external_id, 'number': b.bill_number,
            'vendor_id': b.vendor_id, 'vendor_name': vendors[b.vendor_id].name if b.vendor_id in vendors else None,
            'amount': str(b.total), 'balance': str(b.balance), 'currency': b.currency, 'status': b.status.value}
            for b in rows['bills']],
        'requests': [service.status(r.id) for r in rows['requests']],
        'bank_movements': [{'id': b.id, 'external_id': b.external_id, 'account_id': b.account_id,
            'date': b.transaction_date.isoformat(), 'amount': str(b.amount), 'currency': b.currency,
            'provisional': bool(b.is_provisional), 'source_status': (b.raw_data or {}).get('status'),
            'reconciled': bool(b.is_reconciled)} for b in rows['bank_movements']],
        'funding_accounts': [{'id': a.id, 'external_id': a.external_id, 'name': a.name,
            'connection_id': a.open_finance_connection_id,
            'has_provider_account_identity': bool(a.provider_account_number)} for a in rows['funding_accounts']],
        'limitations': ['Single supplier bill and ILS per request; several booked outflows may settle it.',
            'Beneficiary and withholding decisions require an owner review of supporting evidence.',
            'Withholding deductions, schedules, bulk payments, FX and fees require separate reviewed adapters.',
            'Official SUMIT posting, refunds and bank authorization are separate pending steps.']}
