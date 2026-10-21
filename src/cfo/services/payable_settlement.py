"""Bill-linked payment requests and reviewed local settlement, without live sync.

The approved beneficiary/withholding review is an owner attestation. Provider
request readback, booked bank evidence and official posting remain separate facts.
"""
from datetime import datetime, timezone
from decimal import Decimal

from ..models import (Account, BankTransaction, Bill, BillStatus, Contact,
                      IrreversibleActionRequest, Organization, Payment)
from .collection_settlement import CollectionSettlementService, money
from .irreversible_action_service import IrreversibleActionService
from .payment_evidence import is_accounting_payment, payment_outcome

OPERATION = 'payable.payment_request'


class PayableSettlementService:
    def __init__(self, db, organization_id):
        self.db, self.org_id = db, organization_id
        self.actions = IrreversibleActionService(db, organization_id)

    def _row(self, model, row_id):
        row = self.db.query(model).filter_by(id=row_id, organization_id=self.org_id).with_for_update().first()
        if row is None:
            raise ValueError('Record not found in organization')
        return row

    def _lock(self, actor):
        CollectionSettlementService(self.db, self.org_id)._admin(actor)
        self.db.query(Organization).filter_by(id=self.org_id).with_for_update().one()

    def _request(self, request_id):
        request = self.actions.get(request_id)
        if request is None or (request.payload or {}).get('operation') != OPERATION:
            raise ValueError('Payable request not found in organization')
        return request

    def _identity(self, bill):
        vendor = self._row(Contact, bill.vendor_id)
        if bill.source != 'sumit' or not bill.external_id or vendor.source != 'sumit' or not vendor.external_id or not vendor.is_active:
            raise ValueError('An identified SUMIT bill and active supplier are required')
        if not all([vendor.bank_code, vendor.bank_branch, vendor.bank_account_number]):
            raise ValueError('Supplier bank details are incomplete')
        return {'bill_id': bill.id, 'bill_external_id': bill.external_id, 'bill_source': bill.source,
            'bill_total': str(bill.total), 'currency': bill.currency, 'vendor_id': vendor.id,
            'vendor_external_id': vendor.external_id, 'vendor_name': vendor.name,
            'vendor_bank': {'bank': vendor.bank_code, 'branch': vendor.bank_branch,
                'account_number': vendor.bank_account_number, 'holder': vendor.bank_account_holder}}

    def _validate(self, request, bill):
        if any(request.payload.get(key) != value for key, value in self._identity(bill).items()):
            raise ValueError('Supplier, beneficiary or bill changed; a new review is required')
        if bill.currency != 'ILS' or bill.status in {BillStatus.DRAFT, BillStatus.VOID}:
            raise ValueError('Bill is not eligible for this ILS supplier payment flow')

    def _payment(self, request):
        if not request.provider_reference:
            return None
        row = self.db.query(Payment).filter_by(organization_id=self.org_id, source='open_finance',
            external_id=f'payment:{request.provider_reference}').with_for_update().first()
        if row and ((row.raw_data or {}).get('request_id') != request.id or row.bill_id != request.payload['bill_id']):
            raise ValueError('Provider payment is already recorded; review its existing allocation')
        return row

    def _funding(self, account_id):
        if account_id is None:
            return None
        from ..api.routes.open_finance import _active_connected_account_numbers
        account = self._row(Account, account_id)
        if account.source != 'open_finance' or not account.provider_account_number or account.provider_account_number not in _active_connected_account_numbers(self.db, self.org_id):
            raise ValueError('Funding account requires exact active provider account evidence')
        return {'account_id': account.id, 'external_id': account.external_id,
            'account_number': account.provider_account_number, 'connection_id': account.open_finance_connection_id}

    def propose(self, *, bill_id, amount, proposed_by, idempotency_key, creditor,
                beneficiary_evidence, withholding_decision, withholding_evidence,
                funding_account_id=None, funding_account_type=None, channel='web'):
        self._lock(proposed_by)
        amount = money(amount)
        bill = self._row(Bill, bill_id)
        identity = self._identity(bill)
        if withholding_decision not in {'not_required', 'valid_exemption'}:
            raise ValueError('Withholding payment/posting requires a separate reviewed adapter')
        if not all(isinstance(e, str) and len(e.strip()) >= 20 for e in [beneficiary_evidence, withholding_evidence]):
            raise ValueError('Explicit beneficiary and withholding evidence are required')
        if not isinstance(creditor, dict) or set(creditor) != {'name', 'account_number', 'account_type'} or not all(isinstance(v, str) and v.strip() for v in creditor.values()) or creditor['account_type'] not in {'iban', 'bban'}:
            raise ValueError('Explicit creditor name and full account identity are required')
        funding = self._funding(funding_account_id)
        if funding and funding_account_type not in {'iban', 'bban'}:
            raise ValueError('Choose the documented funding account type')
        payload = {**identity, 'operation': OPERATION, 'amount': str(amount), 'creditor': creditor,
            'bank_account': creditor['account_number'], 'funding': funding, 'funding_account_type': funding_account_type,
            'beneficiary_evidence': beneficiary_evidence, 'withholding_decision': withholding_decision,
            'withholding_evidence': withholding_evidence, 'review_scope': 'owner_attestation'}
        prior = self.db.query(IrreversibleActionRequest).filter_by(organization_id=self.org_id, idempotency_key=idempotency_key).first()
        if prior is None:
            if bill.currency != 'ILS' or bill.balance is None or amount > bill.balance or bill.balance <= 0 or bill.status in {BillStatus.DRAFT, BillStatus.VOID, BillStatus.PAID}:
                raise ValueError('Bill has no sufficient eligible ILS balance')
            linked = [p for p in self.db.query(Payment).filter_by(organization_id=self.org_id, bill_id=bill.id) if is_accounting_payment(p)]
            if any(p.currency != bill.currency for p in linked) or sum((p.amount for p in linked), Decimal(0)) > bill.paid_amount:
                raise ValueError('Already-recorded supplier payments require balance parity review')
            for other in self.db.query(IrreversibleActionRequest).filter_by(organization_id=self.org_id, action_type='payment'):
                if (other.payload or {}).get('operation') != OPERATION or other.payload.get('bill_id') != bill.id or other.status in {'rejected', 'cancelled'}:
                    continue
                payment = self._payment(other)
                if payment is None or payment.amount < money(other.payload['amount']):
                    raise ValueError('An unresolved supplier payment request already exists')
        return self.actions.propose(proposed_by=proposed_by, action_type='payment', payload=payload,
            idempotency_key=idempotency_key, channel=channel,
            description='Review supplier bank identity and withholding evidence before signing')

    async def execute(self, request_id):
        request = self._request(request_id)
        bill = self._row(Bill, request.payload['bill_id'])
        self._validate(request, bill)
        amount = money(request.payload['amount'])
        if bill.balance is None or amount > bill.balance:
            raise ValueError('Supplier balance changed before execution')
        funding = request.payload.get('funding')
        if funding and self._funding(funding['account_id']) != funding:
            raise ValueError('Funding identity or consent changed before execution')
        for other in self.db.query(IrreversibleActionRequest).filter_by(organization_id=self.org_id, action_type='payment'):
            if other.id == request.id or (other.payload or {}).get('operation') != OPERATION or other.payload.get('bill_id') != bill.id or other.status not in {'executing', 'executed', 'verified', 'verification_failed', 'failed'}:
                continue
            payment = self._payment(other)
            if payment is None or payment.amount < money(other.payload['amount']):
                raise ValueError('Another supplier attempt has an unresolved outcome')
        self.actions.claim_approved_for_execution(request.id, action_type='payment', submitted_payload=request.payload)
        client = None
        try:
            from ..api.routes.open_finance import get_open_finance_client
            client = get_open_finance_client(self.db, self.org_id)
            creditor = request.payload['creditor']
            information = {'amount': float(amount), 'currency': bill.currency,
                'description': f"Supplier bill {bill.external_id}", 'creditorName': creditor['name'],
                'creditorAccountNumber': creditor['account_number'], 'creditorAccountType': creditor['account_type']}
            if funding:
                information.update(debtorAccountNumber=funding['account_number'], debtorAccountType=request.payload['funding_account_type'])
            created = await client.create_payment({'paymentInformation': information})
            reference = created.get('id') or created.get('paymentId')
            if not reference or not created.get('payUrl'):
                raise ValueError('Provider omitted payment request identity or URL')
            self.actions.mark_executed(request.id, provider_reference=str(reference), execution_result=created)
            observed = await client.get_payment(str(reference))
            if not isinstance(observed, dict) or str(observed.get('id') or observed.get('paymentId') or '') != str(reference):
                raise ValueError('Provider payment readback identity mismatch')
            self.actions.mark_verified(request.id, verification_evidence={**observed, **payment_outcome(observed)})
            return self.status(request.id)
        except Exception as exc:
            self.db.rollback()
            if self.actions.get(request.id).status in {'executing', 'executed'}:
                self.actions.mark_failed(request.id, error=f'Provider outcome unknown: {type(exc).__name__}; no automatic retry')
            raise
        finally:
            if client is not None:
                await client.close()

    def _decision_policy(self, actor, bill, amount, channel):
        from .policy_service import PolicyService
        decision = PolicyService(self.db, self.org_id).evaluate(user=actor, action='reconciliation.approve',
            amount=amount, currency=bill.currency, counterparty_id=bill.vendor_id, channel=channel)
        if not decision.allowed or decision.requires_step_up or decision.required_approvals > 1 or decision.separation_of_duties:
            raise ValueError('Organization policy requires a separate approval path for this bank decision')
        return decision.to_audit()

    def _outcome(self, request):
        from ..models import ProviderEventReceipt
        from .provider_event_service import FINAL_PAYMENT_STATUSES
        outcome = payment_outcome(request.verification_evidence or request.execution_result or {})
        event = self.db.query(ProviderEventReceipt).filter_by(organization_id=self.org_id,
            source='open_finance', entity_type='payment', external_id=request.provider_reference,
            disposition='applied').order_by(ProviderEventReceipt.id.desc()).first() if request.provider_reference else None
        if event:
            observed = payment_outcome(event.evidence)
            old, new = outcome['provider_status'], observed['provider_status']
            conflict = old in FINAL_PAYMENT_STATUSES and old != new and (old, new) != ('ACSC', 'ACCC')
            if not conflict:
                outcome = observed
            outcome['provider_observation'] = {'event_receipt_id': event.id,
                'observed_at': event.observed_at.isoformat(), 'review_required': conflict}
        return outcome

    def settle(self, request_id, *, bank_transaction_id, decided_by, reason, channel='web'):
        self._lock(decided_by)
        request = self._request(request_id)
        bill = self._row(Bill, request.payload['bill_id'])
        self._validate(request, bill)
        bank = self._row(BankTransaction, bank_transaction_id)
        payment = self._payment(request)
        raw = dict(payment.raw_data or {}) if payment else {}
        history = list(raw.get('settlements', []))
        if any(e['bank_transaction_id'] == bank.id for e in history):
            return self.status(request.id)
        if request.status not in {'executed', 'verified', 'verification_failed'} or not request.provider_reference:
            raise ValueError('A provider request must exist before bank settlement')
        outcome = self._outcome(request)
        if outcome['money_status'] in {'failed', 'cancelled', 'unknown'} or outcome.get('provider_observation', {}).get('review_required'):
            raise ValueError('Conflicting or unknown provider result requires review before linking bank evidence')
        if not isinstance(reason, str) or len(reason.strip()) < 20:
            raise ValueError('Record reviewed supplier and bank identity evidence')
        if bank.source != 'open_finance' or not bank.external_id or bank.is_provisional or bank.amount >= 0 or (bank.raw_data or {}).get('status') != 'BOOKED' or bank.is_reconciled or bank.currency != bill.currency:
            raise ValueError('An unallocated, final booked bank outflow in the bill currency is required')
        if request.payload.get('funding') and bank.account_id != request.payload['funding']['account_id']:
            raise ValueError('Bank outflow does not belong to the reviewed funding account')
        amount = -bank.amount
        settled = payment.amount if payment else Decimal(0)
        if settled + amount > money(request.payload['amount']) or amount > bill.balance:
            raise ValueError('Bank amount exceeds the request or bill balance')
        linked = [p for p in self.db.query(Payment).filter_by(organization_id=self.org_id, bill_id=bill.id) if is_accounting_payment(p)]
        if any(p.currency != bill.currency for p in linked) or bill.paid_amount != sum((p.amount for p in linked), Decimal(0)):
            raise ValueError('Supplier paid balance requires source-payment parity review')
        policy = self._decision_policy(decided_by, bill, amount, channel)
        if payment is None:
            payment = Payment(organization_id=self.org_id, source='open_finance',
                external_id=f'payment:{request.provider_reference}', bill_id=bill.id, contact_id=bill.vendor_id,
                amount=0, currency=bill.currency, method='bank_transfer', payment_date=bank.transaction_date,
                reference=request.provider_reference)
            self.db.add(payment); self.db.flush()
        history.append({'bank_transaction_id': bank.id, 'bank_external_id': bank.external_id,
            'bank_source': bank.source, 'amount': str(amount), 'currency': bank.currency,
            'bank_date': bank.transaction_date.isoformat(), 'reason': reason.strip(),
            'decided_by_user_id': decided_by.id, 'observed_at': datetime.now(timezone.utc).isoformat(), 'policy': policy})
        payment.amount = settled + amount
        payment.raw_data = {**raw, 'source_entity_type': 'reviewed_payable_settlement', 'request_id': request.id,
            'bill_external_id': bill.external_id, 'provider_reference': request.provider_reference,
            'bill_total': str(bill.total), 'settlements': history, 'verification_scope': 'human_reviewed_bank_evidence',
            'official_books_verified': False}
        bill.paid_amount += amount; bill.balance -= amount
        bill.status = BillStatus.PAID if bill.balance == 0 else BillStatus.PARTIALLY_PAID
        bank.is_reconciled = True; bank.matched_entity_type = 'payment'; bank.matched_entity_id = payment.id
        bank.reconciliation_dispatch_status = 'unsupported'
        bank.reconciliation_error = 'Reviewed local supplier settlement; official SUMIT posting evidence remains pending'
        self.db.commit()
        return self.status(request.id)

    def reverse(self, request_id, *, bank_transaction_id, decided_by, reason, channel='web'):
        self._lock(decided_by)
        request = self._request(request_id)
        bill = self._row(Bill, request.payload['bill_id'])
        self._validate(request, bill)
        payment = self._payment(request)
        if payment is None:
            raise ValueError('No settlement to reverse')
        raw = dict(payment.raw_data or {})
        reversals = list(raw.get('reversals', []))
        if any(e['bank_transaction_id'] == bank_transaction_id for e in reversals):
            return self.status(request.id)
        entry = next((e for e in raw.get('settlements', []) if e['bank_transaction_id'] == bank_transaction_id), None)
        if entry is None or not isinstance(reason, str) or len(reason.strip()) < 20:
            raise ValueError('A recorded settlement and reviewed reversal reason are required')
        bank = self._row(BankTransaction, bank_transaction_id)
        amount = Decimal(entry['amount'])
        if bill.paid_amount < amount or payment.amount < amount or (bank.matched_entity_type, bank.matched_entity_id) != ('payment', payment.id):
            raise ValueError('Settlement state changed; reconstruction review required')
        policy = self._decision_policy(decided_by, bill, amount, channel)
        reversals.append({'bank_transaction_id': bank.id, 'amount': str(amount), 'reason': reason,
            'decided_by_user_id': decided_by.id, 'observed_at': datetime.now(timezone.utc).isoformat(),
            'policy': policy, 'money_returned': False, 'scope': 'local_relationship_only'})
        payment.raw_data = {**raw, 'reversals': reversals}; payment.amount -= amount
        bill.paid_amount -= amount; bill.balance += amount
        bill.status = BillStatus.PARTIALLY_PAID if bill.paid_amount else BillStatus.RECEIVED
        bank.is_reconciled = False; bank.matched_entity_type = None; bank.matched_entity_id = None
        bank.reconciliation_dispatch_status = None; bank.reconciliation_error = None
        self.db.commit()
        return self.status(request.id)

    def status(self, request_id):
        request = self._request(request_id)
        bill = self._row(Bill, request.payload['bill_id'])
        payment = self._payment(request)
        raw = payment.raw_data or {} if payment else {}
        settled = payment.amount if payment else Decimal(0)
        remaining = money(request.payload['amount']) - settled
        reversed_ids = {e['bank_transaction_id'] for e in raw.get('reversals', [])}
        outcome = self._outcome(request)
        return {'request_id': request.id, 'organization_id': self.org_id, 'bill_id': bill.id,
            'bill_external_id': bill.external_id, 'vendor_id': bill.vendor_id, 'currency': bill.currency,
            'amount': request.payload['amount'], 'approval_status': request.status, 'approval_payload': request.payload,
            'provider_reference': request.provider_reference, 'provider_status': outcome['provider_status'],
            'provider_observation': outcome.get('provider_observation'), 'error': request.error,
            'verification_scope': 'payment_request', 'payment_url': (request.execution_result or {}).get('payUrl'),
            'money_status': ('bank_settled' if remaining == 0 else 'partially_bank_settled') if settled else outcome['money_status'],
            'settled_amount': f'{settled:.2f}', 'remaining_request_amount': f'{remaining:.2f}',
            'remaining_balance': f'{bill.balance:.2f}', 'payment_id': payment.id if payment else None,
            'settlement_history': [{**e, 'status': 'reversed' if e['bank_transaction_id'] in reversed_ids else 'active'} for e in raw.get('settlements', [])],
            'reversals': raw.get('reversals', []), 'official_books_verified': False,
            'official_posting_status': 'unsupported', 'sync_triggered': False}
