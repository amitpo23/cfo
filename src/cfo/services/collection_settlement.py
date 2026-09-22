"""Invoice collection using the existing approval and normalized evidence planes.

No reads here trigger sync. A request's `verified` means request readback only.
The single-invoice slice settles from an existing SUMIT receipt and booked bank
movement, joined by an explicit reviewed decision; amount/date alone never join.
"""
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from sqlalchemy.exc import IntegrityError
from ..models import (Invoice, InvoiceStatus, Payment, BankTransaction, Contact,
                      CollectionPaymentAllocation, IrreversibleActionRequest, UserRole)
from .irreversible_action_service import IrreversibleActionService
from .payment_evidence import is_accounting_payment, payment_outcome
from .membership_service import role_in

OPERATION = 'collection.payment_request'


def money(value):
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("A valid monetary amount is required") from exc
    if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal('.01')):
        raise ValueError('A positive amount with at most two decimal places is required')
    return amount


class CollectionSettlementService:
    def __init__(self, db, organization_id):
        self.db, self.org_id = db, organization_id
        self.actions = IrreversibleActionService(db, organization_id)

    def _invoice(self, invoice_id):
        row = self.db.query(Invoice).filter_by(id=invoice_id, organization_id=self.org_id).with_for_update().first()
        if row is None:
            raise ValueError('Invoice not found in organization')
        return row

    def allocate_existing(self, **kwargs):
        from .collection_allocation_service import CollectionAllocationService
        return CollectionAllocationService(self).allocate(**kwargs)

    def reverse_allocation(self, allocation_id, **kwargs):
        from .collection_allocation_service import CollectionAllocationService
        return CollectionAllocationService(self).reverse(allocation_id, **kwargs)

    def _request(self, request_id):
        row = self.actions.get(request_id)
        if row is None or (row.payload or {}).get('operation') != OPERATION:
            raise ValueError('Collection request not found in organization')
        required = {'invoice_id','invoice_external_id','invoice_source','contact_id','customer_external_id',
                    'amount','currency','payment_channel','creditor','document_type'}
        if not required.issubset(row.payload) or row.payload['payment_channel'] not in {'sumit','open_finance'}:
            raise ValueError('Collection approval envelope is incomplete or unsupported')
        return row

    def _validate_invoice_identity(self, request, invoice):
        contact = self.db.query(Contact).filter_by(id=invoice.contact_id,organization_id=self.org_id).first()
        actual = {'invoice_external_id':invoice.external_id, 'invoice_source':invoice.source,
                  'contact_id':invoice.contact_id, 'customer_external_id':contact.external_id if contact else None,
                  'currency':invoice.currency}
        if any(request.payload.get(key) != value for key,value in actual.items()) or not contact or contact.source != 'sumit':
            raise ValueError('Invoice/customer identity or currency changed; review a new proposal')
        if invoice.currency != 'ILS' or invoice.source != 'sumit' or (invoice.raw_data or {}).get('document_type') != 'invoice':
            raise ValueError('Invoice no longer satisfies the reviewed document contract')
        if request.payload.get('document_type') != 'receipt':
            raise ValueError('This slice requires a receipt against an existing tax invoice')

    def _admin(self, actor):
        self.actions._require_actor_scope(actor)
        if actor.role != UserRole.SUPER_ADMIN and role_in(self.db, actor.id, self.org_id) != UserRole.ADMIN:
            raise ValueError('An active organization admin must record the evidence decision')

    def _request_fully_allocated(self, request):
        from .collection_allocation_service import amount_allocated
        return amount_allocated(self.db, self.org_id, request_id=request.id) >= money(request.payload['amount'])

    def propose(self, *, invoice_id, amount, channel, proposed_by, idempotency_key, creditor=None, origin_channel='web'):
        self._admin(proposed_by)
        amount = money(amount)
        if channel not in {'open_finance','sumit'}:
            raise ValueError('Choose open_finance or sumit')
        invoice = self._invoice(invoice_id)
        if invoice.source != 'sumit' or not invoice.external_id or not invoice.contact_id:
            raise ValueError('A source-identified SUMIT invoice and customer are required')
        contact = self.db.query(Contact).filter_by(id=invoice.contact_id, organization_id=self.org_id, source='sumit').first()
        if not contact or not contact.external_id:
            raise ValueError('SUMIT customer identity is missing')
        # This vertical slice deliberately starts from a final tax invoice.
        # A proforma/exempt-business document needs a separate professional decision.
        if (invoice.raw_data or {}).get('document_type') != 'invoice':
            raise ValueError('Document type needs review; this slice supports an existing tax invoice only')
        if invoice.currency != 'ILS':
            raise ValueError('This collection slice supports ILS only')
        creditor = dict(creditor or {}) if channel == 'open_finance' else {}
        if channel == 'open_finance' and (set(creditor) != {'name','account_number','account_type'} or
                not creditor['name'] or not creditor['account_number'] or creditor['account_type'] not in {'iban','bban'}):
            raise ValueError('Explicit creditor name, account number and account type are required for signing review')
        payload = {'operation':OPERATION,'invoice_id':invoice.id,'invoice_external_id':invoice.external_id,
                   'invoice_source':invoice.source,'contact_id':contact.id,'customer_external_id':contact.external_id,
                   'amount':str(amount),'currency':invoice.currency,'payment_channel':channel,
                   'creditor':creditor,'bank_account':creditor.get('account_number'), 'document_type':'receipt'}
        existing = self.db.query(IrreversibleActionRequest).filter_by(organization_id=self.org_id,idempotency_key=idempotency_key).first()
        if existing is None:
            if invoice.status in {InvoiceStatus.DRAFT,InvoiceStatus.CANCELLED,InvoiceStatus.VOID,InvoiceStatus.PAID} or invoice.balance is None or amount > invoice.balance:
                raise ValueError('Invoice has no sufficient verified open balance')
            from .collection_allocation_service import amount_allocated
            for receipt in self.db.query(Payment).filter_by(organization_id=self.org_id,
                    contact_id=contact.id, source='sumit', method='receipt').all():
                if receipt.bill_id or (receipt.raw_data or {}).get('status') not in {'open', 'closed', 'paid'}:
                    continue
                if receipt.invoice_id is None and receipt.amount > amount_allocated(self.db, self.org_id, payment_id=receipt.id):
                    raise ValueError('An unallocated customer receipt requires review before another collection request')
                if receipt.invoice_id == invoice.id and receipt.amount > invoice.paid_amount:
                    raise ValueError('An already-linked receipt requires balance review before collection')
            # Serialize proposals on the invoice. No second channel/request while
            # another claim is pending or has an unknown external outcome.
            for request in self.db.query(IrreversibleActionRequest).filter_by(organization_id=self.org_id,action_type='payment').all():
                if (request.payload or {}).get('operation') == OPERATION and request.payload.get('invoice_id') == invoice_id:
                    allocated = self._request_fully_allocated(request)
                    if not allocated and request.status not in {'rejected','cancelled'}:
                        raise ValueError('An unresolved collection request already exists for this invoice')
        return self.actions.propose(proposed_by=proposed_by, action_type='payment',payload=payload,
            idempotency_key=idempotency_key, channel=origin_channel,
            description='Collect the reviewed invoice balance; verify creditor account before approval')

    async def execute(self, request_id):
        request = self._request(request_id)
        invoice = self._invoice(request.payload['invoice_id'])
        self._validate_invoice_identity(request, invoice)
        amount = money(request.payload['amount'])
        if invoice.balance is None or amount > invoice.balance or invoice.status in {InvoiceStatus.DRAFT,InvoiceStatus.CANCELLED,InvoiceStatus.VOID}:
            raise ValueError('Balance changed; review a new proposal before executing')
        for other in self.db.query(IrreversibleActionRequest).filter_by(organization_id=self.org_id,action_type='payment').all():
            if other.id == request.id or (other.payload or {}).get('operation') != OPERATION or other.payload.get('invoice_id') != invoice.id:
                continue
            if other.status in {'executing','executed','verified','verification_failed','failed'} and not self._request_fully_allocated(other):
                raise ValueError('Another collection attempt has an unresolved provider outcome')
        self.actions.claim_approved_for_execution(request.id,action_type='payment',submitted_payload=request.payload)
        client = None
        try:
            if request.payload['payment_channel'] == 'open_finance':
                from ..api.routes.open_finance import get_open_finance_client
                client = get_open_finance_client(self.db,self.org_id)
                creditor = request.payload['creditor']
                body = {'paymentInformation':{'amount':float(amount),'currency':request.payload['currency'],
                        'description':f"Invoice {request.payload['invoice_external_id']}",
                        'creditorName':creditor['name'],'creditorAccountNumber':creditor['account_number'],
                        'creditorAccountType':creditor['account_type']}}
                created = await client.create_payment(body)
                reference = created.get('id') or created.get('paymentId')
                if not reference or not created.get('payUrl'):
                    raise ValueError('Provider omitted request identity or payment URL')
                self.actions.mark_executed(request.id,provider_reference=str(reference),execution_result=created)
                readback = await client.get_payment(str(reference))
                if not isinstance(readback,dict) or str(readback.get('id') or readback.get('paymentId') or '') != str(reference):
                    raise ValueError('Payment request readback identity mismatch')
                self.actions.mark_verified(request.id,verification_evidence={**readback,**payment_outcome(readback)})
            else:
                from .document_issuance_service import DocumentIssuanceService
                created = await DocumentIssuanceService(self.db,self.org_id).create_payment_link(
                    invoice.id, amount=amount, external_identifier=f'rezef-collection-{request.id}', document_type='receipt')
                # SUMIT beginredirect returns only a URL. It is a request reference,
                # never a payment ID or independently verified transfer.
                self.actions.mark_executed(request.id,provider_reference=created['payment_url'],
                    execution_result={**created,'verification_scope':'payment_request','money_status':'pending'})
            return self.status(request.id)
        except Exception as exc:
            self.db.rollback()
            row=self.actions.get(request.id)
            if row.status in {'executing','executed'}:
                self.actions.mark_failed(request.id,error=f'Provider outcome unknown: {type(exc).__name__}; no automatic retry')
            raise ValueError('Provider request outcome unverified; review before any retry') from exc
        finally:
            if client is not None:
                await client.close()

    def allocate(self, request_id, *, payment_id, bank_transaction_id, decided_by, reason):
        """Compatibility entry point using the shared, reversible allocation path."""
        self._admin(decided_by)
        request = self._request(request_id)
        self.allocate_existing(invoice_id=request.payload['invoice_id'],
            payment_id=payment_id, bank_transaction_id=bank_transaction_id,
            amount=request.payload['amount'], request_id=request.id,
            idempotency_key=f'collection-request:{request.id}',
            decided_by=decided_by, reason=reason)
        return self.status(request_id)

    def status(self, request_id):
        request=self._request(request_id)
        invoice=self.db.query(Invoice).filter_by(id=request.payload['invoice_id'],organization_id=self.org_id).one()
        from .collection_allocation_service import active_allocations, amount_allocated
        allocation=active_allocations(self.db,self.org_id,request_id=request_id).first()
        allocated=amount_allocated(self.db,self.org_id,request_id=request_id)
        remaining=money(request.payload['amount'])-allocated
        evidence=request.verification_evidence or request.execution_result or {}
        observation = None
        if request.payload['payment_channel'] == 'open_finance' and request.provider_reference:
            from ..models import ProviderEventReceipt
            from .provider_event_service import FINAL_PAYMENT_STATUSES
            event = self.db.query(ProviderEventReceipt).filter_by(organization_id=self.org_id,
                source='open_finance', entity_type='payment', external_id=request.provider_reference,
                disposition='applied').order_by(ProviderEventReceipt.id.desc()).first()
            if event:
                observed = payment_outcome(event.evidence)
                previous_code = evidence.get('provider_status')
                new_code = observed['provider_status']
                conflict = previous_code in FINAL_PAYMENT_STATUSES and previous_code != new_code and (previous_code, new_code) != ('ACSC', 'ACCC')
                observation = {'scope': 'authenticated_callback', 'event_receipt_id': event.id,
                    'observed_at': event.observed_at.isoformat(), 'provider_status': new_code,
                    'review_required': conflict}
                if not conflict:
                    evidence = {**evidence, **observed}
        return {'request_id':request.id,'organization_id':self.org_id,'invoice_id':invoice.id,
                'invoice_external_id':invoice.external_id,'amount':request.payload['amount'],'currency':request.payload['currency'],
                'channel':request.payload['payment_channel'],'approval_status':request.status,
                'approval_payload':request.payload,
                'request_verified':request.status=='verified','verification_scope':'payment_request',
                'provider_reference':request.provider_reference,'provider_status':evidence.get('provider_status'),
                'provider_observation':observation,
                'money_status':('received' if remaining == 0 else 'partially_received') if allocation else evidence.get('money_status','unknown'),
                'allocated_amount':f'{allocated:.2f}', 'remaining_collection_amount':f'{remaining:.2f}',
                'invoice_observed_at':invoice.updated_at.isoformat() if invoice.updated_at else None,
                'request_created_at':request.proposed_at.isoformat() if request.proposed_at else None,
                'derived_balance':True,
                'remaining_balance':float(invoice.balance) if invoice.balance is not None else None,
                'payment_url':(request.execution_result or {}).get('payUrl') or (request.execution_result or {}).get('payment_url'),
                'payment_id':allocation.payment_id if allocation else None,
                'bank_transaction_id':allocation.bank_transaction_id if allocation else None,
                'document':{'status':'existing_receipt_linked' if allocation else 'awaiting_existing_receipt_or_approved_issue',
                            'required_type':'receipt','source':'sumit','external_id':allocation.document_external_id if allocation else None},
                'official_reconciliation_status':'unsupported','official_books_verified':False,
                'evidence':allocation.evidence if allocation else None,
                'pending':(['official_reconciliation_readback'] if allocation else
                           ['booked_bank_and_receipt_identity_review','official_reconciliation_readback'])}
