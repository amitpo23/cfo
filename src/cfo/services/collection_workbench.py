"""One DB-only collection view shared by HTTP and Moshko."""
from ..models import (BankTransaction, CollectionPaymentAllocation, Invoice, IrreversibleActionRequest,
                      Payment, ProviderEventReceipt)
from .collection_allocation_service import CollectionAllocationService, amount_allocated
from .collection_settlement import CollectionSettlementService, OPERATION


def collection_workbench(db, organization_id, *, limit=100, offset=0):
    if not 1 <= limit <= 200 or offset < 0:
        raise ValueError('Use limit 1–200 and a nonnegative offset')
    service = CollectionSettlementService(db, organization_id)
    allocation_service = CollectionAllocationService(service)
    queries = {
        'invoices': db.query(Invoice).filter_by(organization_id=organization_id, source='sumit'),
        'receipts': db.query(Payment).filter_by(organization_id=organization_id, source='sumit', method='receipt'),
        'bank_movements': db.query(BankTransaction).filter(BankTransaction.organization_id == organization_id,
            BankTransaction.source == 'open_finance', BankTransaction.amount > 0),
        'allocations': db.query(CollectionPaymentAllocation).filter_by(organization_id=organization_id),
        'requests': db.query(IrreversibleActionRequest).filter(IrreversibleActionRequest.organization_id == organization_id,
            IrreversibleActionRequest.payload['operation'].as_string() == OPERATION),
        'event_reviews': db.query(ProviderEventReceipt).filter_by(organization_id=organization_id, disposition='review_required'),
    }
    counts = {key: query.count() for key, query in queries.items()}
    rows = {key: query.order_by(query.column_descriptions[0]['entity'].id.desc()).offset(offset).limit(limit).all()
            for key, query in queries.items()}
    return {
        'organization_id': organization_id, 'sync_triggered': False, 'official_books_verified': False,
        'pagination': {'limit': limit, 'offset': offset, 'counts': counts, 'has_more': any(n > offset + limit for n in counts.values())},
        'invoices': [{'id': r.id, 'external_id': r.external_id, 'number': r.invoice_number,
            'contact_id': r.contact_id, 'currency': r.currency, 'total': str(r.total), 'paid_amount': str(r.paid_amount),
            'balance': str(r.balance), 'status': r.status.value, 'document_type': (r.raw_data or {}).get('document_type'),
            'observed_at': r.updated_at.isoformat() if r.updated_at else None} for r in rows['invoices']],
        'receipts': [{'id': r.id, 'external_id': r.external_id, 'contact_id': r.contact_id, 'currency': r.currency,
            'amount': str(r.amount), 'date': r.payment_date.isoformat(), 'document_external_id': (r.raw_data or {}).get('document_id'),
            'source_status': (r.raw_data or {}).get('status'),
            'unallocated_amount': f'{r.amount - amount_allocated(db, organization_id, payment_id=r.id):.2f}'} for r in rows['receipts']],
        'bank_movements': [{'id': r.id, 'external_id': r.external_id, 'account_id': r.account_id,
            'currency': r.currency, 'amount': str(r.amount), 'date': r.transaction_date.isoformat(),
            'provisional': bool(r.is_provisional), 'source_status': (r.raw_data or {}).get('status'),
            'unallocated_amount': f'{r.amount - amount_allocated(db, organization_id, bank_transaction_id=r.id):.2f}'} for r in rows['bank_movements']],
        'allocations': [allocation_service.status(r.id) for r in rows['allocations']],
        'requests': [service.status(r.id) for r in rows['requests']],
        'event_reviews': [{'id': r.id, 'source': r.source, 'entity_type': r.entity_type, 'external_id': r.external_id,
            'status': r.disposition, 'observed_at': r.observed_at.isoformat(), 'evidence': r.evidence} for r in rows['event_reviews']],
        'limitations': ['Allocation changes local relationships only; official SUMIT reconciliation is unsupported.',
            'This receipt workflow starts with an existing final tax invoice and an existing receipt.',
            'Fees, FX conversions and unidentified excess require separate evidence and review.',
            'A reversed allocation does not cancel a document or return money.'],
    }
