"""Amount-bearing receipt allocation using the existing collection evidence model.

This changes a reviewed local relationship. It never creates/cancels a provider
document, transfers money, or asserts that SUMIT's official books were changed.
"""
import hashlib
import json
from decimal import Decimal

from sqlalchemy import func

from ..models import (BankTransaction, CollectionAllocationReversal, CollectionPaymentAllocation,
                      Invoice, InvoiceStatus, Organization, Payment)
from .payment_evidence import is_accounting_payment

ZERO = Decimal('0.00')


def active_allocations(db, organization_id, **filters):
    return db.query(CollectionPaymentAllocation).filter_by(organization_id=organization_id, status='active', **filters)


def amount_allocated(db, organization_id, **filters):
    return active_allocations(db, organization_id, **filters).with_entities(
        func.sum(CollectionPaymentAllocation.amount)).scalar() or ZERO


def _hash(raw):
    return hashlib.sha256(json.dumps(raw or {}, sort_keys=True, default=str).encode()).hexdigest()


class CollectionAllocationService:
    def __init__(self, collection):
        self.collection = collection
        self.db, self.org_id = collection.db, collection.org_id

    def _lock(self, actor):
        self.collection._admin(actor)
        # Common serialization point for capacity checks across payment/bank/document
        # edges. SQLite serializes writes; Postgres uses this organization row lock.
        self.db.query(Organization).filter_by(id=self.org_id).with_for_update().one()

    def _row(self, model, row_id):
        row = self.db.query(model).filter_by(id=row_id, organization_id=self.org_id).with_for_update().first()
        if row is None:
            raise ValueError('Evidence record not found in organization')
        return row

    def _policy(self, actor, amount, invoice, channel):
        from .policy_service import PolicyService
        decision = PolicyService(self.db, self.org_id).evaluate(user=actor,
            action='reconciliation.approve', amount=amount, currency=invoice.currency,
            counterparty_id=invoice.contact_id, document_type='receipt', channel=channel)
        if not decision.allowed or decision.requires_step_up or decision.required_approvals > 1 or decision.separation_of_duties:
            raise ValueError(f'Organization policy requires another approval path: {decision.reason}')
        return decision.to_audit()

    def allocate(self, *, invoice_id, payment_id, bank_transaction_id, amount, idempotency_key,
                 decided_by, reason, request_id=None, channel='web'):
        from .collection_settlement import money
        self._lock(decided_by)
        amount = money(amount)
        if not idempotency_key or len(idempotency_key) > 255:
            raise ValueError('A bounded idempotency key is required')
        if not reason or len(reason.strip()) < 10:
            raise ValueError('Record reviewed identity evidence; amount/date are insufficient')
        previous = self.db.query(CollectionPaymentAllocation).filter_by(
            organization_id=self.org_id, idempotency_key=idempotency_key).first()
        if previous:
            if (previous.invoice_id, previous.payment_id, previous.bank_transaction_id, previous.amount, previous.request_id) != (
                    invoice_id, payment_id, bank_transaction_id, amount, request_id):
                raise ValueError('Idempotency key already belongs to a different allocation')
            return self.status(previous.id)
        invoice = self._row(Invoice, invoice_id)
        policy = self._policy(decided_by, amount, invoice, channel)
        payment = self._row(Payment, payment_id)
        bank = self._row(BankTransaction, bank_transaction_id)
        raw = payment.raw_data or {}
        if invoice.source != 'sumit' or not invoice.external_id or (invoice.raw_data or {}).get('document_type') != 'invoice':
            raise ValueError('This receipt allocation requires an identified final SUMIT tax invoice')
        if invoice.status in {InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED, InvoiceStatus.VOID}:
            raise ValueError('Invoice source is no longer eligible; review the source change')
        if payment.source != 'sumit' or payment.method != 'receipt' or not payment.external_id or not raw.get('document_id') or raw.get('document_type') != 'receipt' or raw.get('status') not in {'open', 'closed', 'paid'}:
            raise ValueError('An existing final SUMIT receipt is required; document issuance remains pending')
        if bank.source != 'open_finance' or not bank.external_id or bank.is_provisional or (bank.raw_data or {}).get('status') != 'BOOKED' or bank.amount <= 0:
            raise ValueError('A final booked bank inflow is required')
        if not invoice.contact_id or payment.contact_id != invoice.contact_id or payment.bill_id or payment.invoice_id not in {None, invoice.id}:
            raise ValueError('Receipt customer/source document identity conflicts with this invoice')
        if not invoice.currency or invoice.currency != payment.currency or invoice.currency != bank.currency:
            raise ValueError('Currency disagreement requires a separately evidenced FX decision')
        if bank.is_reconciled and not active_allocations(self.db, self.org_id, bank_transaction_id=bank.id).first() and (
                bank.matched_entity_type, bank.matched_entity_id) not in {('payment', payment.id), ('invoice', invoice.id)}:
            raise ValueError('Bank movement belongs to a different reviewed reconciliation')
        if amount_allocated(self.db, self.org_id, payment_id=payment.id) + amount > payment.amount:
            raise ValueError('Receipt has insufficient unallocated amount')
        if amount_allocated(self.db, self.org_id, bank_transaction_id=bank.id) + amount > bank.amount:
            raise ValueError('Bank movement has insufficient unallocated amount')
        if request_id is not None:
            request = self.collection._request(request_id)
            self.collection._validate_invoice_identity(request, invoice)
            if request.payload['invoice_id'] != invoice.id or request.status not in {'executed', 'verified', 'verification_failed'}:
                raise ValueError('Collection request does not provide eligible execution evidence')
            if amount_allocated(self.db, self.org_id, request_id=request.id) + amount > money(request.payload['amount']):
                raise ValueError('Allocation exceeds the approved collection request amount')
        linked = [p for p in self.db.query(Payment).filter_by(organization_id=self.org_id, invoice_id=invoice.id).all()
                  if is_accounting_payment(p)]
        if any(p.currency != invoice.currency for p in linked):
            raise ValueError('Linked payment currency requires parity review')
        # Legacy invoice_id denotes the entire payment. Amount edges denote only
        # their allocation. Never count both representations of the same receipt.
        allocated_payment_ids = {r.payment_id for r in active_allocations(self.db, self.org_id, invoice_id=invoice.id).all()}
        explained = amount_allocated(self.db, self.org_id, invoice_id=invoice.id) + sum(
            (p.amount for p in linked if p.id not in allocated_payment_ids), ZERO)
        # A linked receipt can have additional not-yet-bank-reviewed parts already
        # counted in the source invoice's paid balance.
        for p in linked:
            if p.id in allocated_payment_ids:
                explained += p.amount - amount_allocated(self.db, self.org_id, invoice_id=invoice.id, payment_id=p.id)
        if invoice.paid_amount > explained:
            raise ValueError('Existing paid total needs source-payment parity before allocation')
        balance_effect = ZERO if payment.invoice_id == invoice.id else amount
        new_paid = max(invoice.paid_amount, explained) + balance_effect
        if new_paid > invoice.total:
            raise ValueError('Allocation exceeds invoice balance; keep the excess unallocated')
        before_paid = invoice.paid_amount
        invoice.paid_amount, invoice.balance = new_paid, invoice.total - new_paid
        invoice.status = InvoiceStatus.PAID if invoice.balance == 0 else InvoiceStatus.PARTIALLY_PAID
        row = CollectionPaymentAllocation(organization_id=self.org_id, request_id=request_id,
            invoice_id=invoice.id, payment_id=payment.id, bank_transaction_id=bank.id, amount=amount,
            currency=invoice.currency, document_external_id=str(raw['document_id']),
            idempotency_key=idempotency_key, status='active', decided_by_user_id=decided_by.id,
            evidence={'decision': 'human_review', 'reason': reason.strip(), 'policy': policy, 'balance_effect': str(new_paid - before_paid),
                'invoice_source': invoice.source, 'invoice_external_id': invoice.external_id,
                'invoice_total': str(invoice.total), 'invoice_paid_before': str(before_paid),
                'payment_source': payment.source, 'payment_external_id': payment.external_id,
                'payment_amount': str(payment.amount), 'payment_hash': _hash(payment.raw_data),
                'bank_source': bank.source, 'bank_external_id': bank.external_id, 'bank_amount': str(bank.amount),
                'bank_hash': _hash(bank.raw_data), 'document_external_id': str(raw['document_id']),
                'document_type': 'receipt', 'contact_id': invoice.contact_id,
                'payment_date': payment.payment_date.isoformat(), 'bank_date': bank.transaction_date.isoformat()})
        self.db.add(row); self.db.flush()
        self._refresh_bank(bank)
        self.db.commit()
        return self.status(row.id)

    def _refresh_bank(self, bank):
        rows = active_allocations(self.db, self.org_id, bank_transaction_id=bank.id).all()
        allocated = sum((r.amount for r in rows), ZERO)
        bank.is_reconciled = bool(rows) and allocated == bank.amount
        payment_ids = {r.payment_id for r in rows}
        bank.matched_entity_type = ('payment' if len(payment_ids) == 1 else 'settlement_allocation') if rows else None
        bank.matched_entity_id = (next(iter(payment_ids)) if len(payment_ids) == 1 else rows[0].id) if rows else None
        bank.reconciliation_dispatch_status = 'unsupported' if rows else None
        bank.reconciliation_error = 'Local allocation only; official SUMIT reconciliation requires operator evidence' if rows else None

    def reverse(self, allocation_id, *, decided_by, reason, channel='web'):
        self._lock(decided_by)
        row = self._row(CollectionPaymentAllocation, allocation_id)
        prior = self.db.query(CollectionAllocationReversal).filter_by(organization_id=self.org_id, allocation_id=row.id).first()
        if prior:
            return {**self.status(row.id), 'reversal_id': prior.id}
        if not reason or len(reason.strip()) < 10:
            raise ValueError('A reviewed reversal reason is required')
        if 'balance_effect' not in row.evidence:
            raise ValueError('Legacy allocation requires a balance reconstruction review before reversal')
        invoice = self._row(Invoice, row.invoice_id)
        policy = self._policy(decided_by, row.amount, invoice, channel)
        bank = self._row(BankTransaction, row.bank_transaction_id)
        if str(invoice.total) != row.evidence['invoice_total'] or invoice.currency != row.currency:
            raise ValueError('Invoice changed; reconstruct the balance before reversal')
        effect = Decimal(row.evidence['balance_effect'])
        if invoice.paid_amount < effect:
            raise ValueError('Invoice balance conflicts with reversal evidence')
        reversal = CollectionAllocationReversal(organization_id=self.org_id, allocation_id=row.id,
            decided_by_user_id=decided_by.id, evidence={'reason': reason.strip(), 'policy': policy, 'balance_effect': str(-effect),
                'paid_before': str(invoice.paid_amount), 'scope': 'local_relationship_only',
                'provider_documents_changed': False, 'money_returned': False})
        self.db.add(reversal)
        row.status = 'reversed'
        invoice.paid_amount -= effect
        invoice.balance = invoice.total - invoice.paid_amount
        invoice.status = InvoiceStatus.PAID if invoice.balance == 0 else (InvoiceStatus.PARTIALLY_PAID if invoice.paid_amount else InvoiceStatus.SENT)
        self.db.flush(); self._refresh_bank(bank); self.db.commit()
        return {**self.status(row.id), 'reversal_id': reversal.id}

    def status(self, allocation_id):
        row = self._row(CollectionPaymentAllocation, allocation_id)
        invoice = self._row(Invoice, row.invoice_id)
        payment = self._row(Payment, row.payment_id)
        bank = self._row(BankTransaction, row.bank_transaction_id)
        return {'organization_id': self.org_id, 'allocation_id': row.id, 'status': row.status,
            'invoice_id': invoice.id, 'payment_id': payment.id, 'bank_transaction_id': bank.id,
            'request_id': row.request_id, 'amount': str(row.amount), 'currency': row.currency,
            'remaining_balance': f'{invoice.balance:.2f}',
            'payment_unallocated_amount': f'{payment.amount - amount_allocated(self.db, self.org_id, payment_id=payment.id):.2f}',
            'bank_unallocated_amount': f'{bank.amount - amount_allocated(self.db, self.org_id, bank_transaction_id=bank.id):.2f}',
            'bank_fully_allocated': bank.is_reconciled, 'document_external_id': row.document_external_id,
            'official_reconciliation_status': 'unsupported', 'official_books_verified': False, 'evidence': row.evidence}
