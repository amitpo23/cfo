"""Reviewed source → immutable approval → one SUMIT expense acknowledgement.

Provider acknowledgement is not official books verification. Existing provider
records are never replaced/cancelled as a side effect, and ambiguous outcomes
cannot be resubmitted through a new proposal.
"""
import base64
import hashlib
import json
from decimal import Decimal, InvalidOperation

from ..models import DocumentIntake, Expense, IrreversibleActionRequest, Organization, User, UserRole
from . import membership_service
from .irreversible_action_service import (IrreversibleActionService, ActionAuthorizationError,
    ActionConflictError, ActionStateError, ActionValidationError)


class ExpenseFilingWorkflow:
    def __init__(self, db, organization_id):
        self.db, self.organization_id = db, organization_id
        self.actions = IrreversibleActionService(db, organization_id)

    def _actor(self, actor_id):
        self.db.expire_all()
        actor = self.db.query(User).filter_by(id=actor_id).first()
        if not actor or not actor.is_active or (actor.role != UserRole.SUPER_ADMIN and
                membership_service.role_in(self.db, actor.id, self.organization_id) != UserRole.ADMIN):
            raise ActionAuthorizationError('Expense filing requires an active organization administrator')
        return actor

    def _expense(self, expense_id, *, lock=True):
        query = self.db.query(Expense).filter_by(id=expense_id, organization_id=self.organization_id)
        row = (query.with_for_update() if lock else query).first()
        if not row:
            raise ActionValidationError('Expense not found')
        return row

    def _requests(self, expense_id):
        return self.db.query(IrreversibleActionRequest).filter(
            IrreversibleActionRequest.organization_id == self.organization_id,
            IrreversibleActionRequest.action_type == 'sumit_writeback',
            IrreversibleActionRequest.idempotency_key.like(f'expense-filing:{int(expense_id)}:%')).order_by(IrreversibleActionRequest.id.desc())

    def _provider_target(self):
        from .sync_engine import get_connection_configuration
        from ..config import settings
        try:
            connection, source, credentials = get_connection_configuration(self.db, self.organization_id, 'sumit')
        except ValueError as exc:
            raise ActionValidationError('An active SUMIT connection requires owner configuration') from exc
        company_id = credentials.get('company_id') or (settings.sumit_company_id if self.organization_id == 1 else None)
        if not company_id:
            raise ActionValidationError('The destination SUMIT company requires owner configuration')
        return {'source': source, 'connection_id': connection.id if connection else None, 'company_id': str(company_id)}

    def status(self, expense_id):
        expense = self._expense(expense_id, lock=False)
        action = self._requests(expense_id).first()
        preview, blocked = None, None
        if action is None or action.status in ('proposed', 'approved', 'rejected'):
            try:
                preview = self._snapshot(expense)
                self._check_duplicates(expense)
                if action and action.status in ('proposed', 'approved') and action.payload != preview:
                    blocked = 'Source changed after the proposal; review and replace the proposal before execution'
            except (ActionConflictError, ActionValidationError) as exc:
                blocked = str(exc)
        return {'approval_request_id': action.id if action else None,
            'approval_status': action.status if action else 'not_proposed',
            'approval_payload': action.payload if action else preview,
            'blocking_reason': blocked,
            'provider_document_id': action.provider_reference if action else None,
            'expense_status': expense.status,
            'error': expense.filing_error or (action.error if action else None), 'official_books_verified': False,
            'money_status': 'no_payment_evidence', 'verification_required': 'Independent provider document and books evidence'}

    def _snapshot(self, expense, *, in_flight=False):
        if expense.source == 'sumit' or expense.external_id or expense.sumit_expense_id:
            raise ActionConflictError('A provider document already exists; review it before creating another expense')
        if expense.status not in (('submitting',) if in_flight else ('pending', 'review', 'error')):
            raise ActionConflictError('Expense is already handled or has an unresolved provider outcome')
        if expense.doc_kind not in ('tax_invoice', 'receipt') or not expense.category or expense.category == 'other':
            raise ActionValidationError('Document kind and expense classification require source review')
        if not expense.supplier_tax_id or not expense.invoice_number:
            raise ActionValidationError('Supplier identity and source document number are required')
        try:
            amounts = [Decimal(str(value)) for value in (expense.amount, expense.vat_amount, expense.total)]
        except (InvalidOperation, ValueError) as exc:
            raise ActionValidationError('Source amounts are missing') from exc
        if any(not amount.is_finite() or amount < 0 for amount in amounts) or amounts[2] <= 0 or amounts[0] + amounts[1] != amounts[2]:
            raise ActionValidationError('Source amounts must be finite, positive and balanced; credits require a separate workflow')
        source = self.db.query(DocumentIntake).filter_by(organization_id=self.organization_id, expense_id=expense.id).first()
        if not source or not expense.receipt_file:
            raise ActionValidationError('A preserved source document must be linked before provider filing')
        raw = base64.b64decode(source.content_base64, validate=True)
        if hashlib.sha256(raw).hexdigest() != source.content_hash or base64.b64decode(expense.receipt_file, validate=True) != raw:
            raise ActionConflictError('Preserved source integrity changed; review required')
        return {'operation': 'expenses.add_source_expense_draft', 'expense_id': expense.id, 'provider_draft_requested': True,
            'provider_target': self._provider_target(),
            'document_id': source.id, 'source_sha256': source.content_hash,
            'amount': str(amounts[2].quantize(Decimal('.01'))), 'currency': 'ILS',
            'source_fields': {'supplier_name': expense.supplier_name, 'supplier_tax_id': expense.supplier_tax_id,
                'invoice_number': expense.invoice_number, 'expense_date': expense.expense_date.isoformat(),
                'amount': str(amounts[0].quantize(Decimal('.01'))), 'vat_amount': str(amounts[1].quantize(Decimal('.01'))),
                'category': expense.category, 'doc_kind': expense.doc_kind, 'notes': expense.description,
                'vat_claimable': str(expense.vat_claimable) if expense.vat_claimable is not None else None,
                'deduction_percent': str(expense.deduction_percent) if expense.deduction_percent is not None else None,
                'filename': source.filename, 'media_type': source.media_type}}

    def _check_duplicates(self, expense):
        from .duplicate_gate import find_duplicate_candidates
        matches = find_duplicate_candidates(self.db, self.organization_id,
            supplier_tax_id=expense.supplier_tax_id, reference=expense.invoice_number, amount=expense.total,
            doc_date=expense.expense_date, exclude_id=expense.id, exclude_source='expense')
        if matches:
            raise ActionConflictError('Possible existing accounting evidence requires review before provider creation')

    def propose(self, expense_id, *, actor_id, reason, channel='web'):
        if not 20 <= len(reason.strip()) <= 2000:
            raise ActionValidationError('A review reason of 20–2000 characters is required')
        try:
            actor = self._actor(actor_id)
            self.db.query(Organization).filter_by(id=self.organization_id).with_for_update().one()
            expense = self._expense(expense_id)
            previous = self._requests(expense_id).all()
            if any(row.execution_started_at is not None for row in previous):
                raise ActionConflictError('An execution already started; independent provider review is required before any further action')
            payload = self._snapshot(expense)
            self._check_duplicates(expense)
            active = next((row for row in previous if row.status != 'rejected'), None)
            if active:
                if active.payload != payload:
                    raise ActionConflictError('Source changed; reject the previous proposal before preparing a replacement')
                return self.status(expense_id)
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]
            self.actions.propose(proposed_by=actor, action_type='sumit_writeback', payload=payload,
                idempotency_key=f'expense-filing:{expense_id}:{digest}:{len(previous)+1}', description=reason.strip(), channel=channel)
            return self.status(expense_id)
        except Exception:
            self.db.rollback(); raise

    async def execute(self, expense_id, *, approval_id, actor_id):
        if approval_id is None:
            raise ActionConflictError('An approved X-Rezef-Approval-Id is required')
        from .sync_engine import get_connector_for_org
        from ..integrations.sumit_models import ExpenseRequest
        from .expense_filing_service import ExpenseFilingService
        try:
            self._actor(actor_id)
            self.db.query(Organization).filter_by(id=self.organization_id).with_for_update().one()
            expense = self._expense(expense_id)
            try:
                payload = self._snapshot(expense)
            except ActionValidationError as exc:
                raise ActionConflictError('Source no longer matches a valid approved expense') from exc
            self.actions.validate_approved_intent(approval_id, action_type='sumit_writeback', submitted_payload=payload)
            self._check_duplicates(expense)
            connector, connection_id, source = get_connector_for_org(self.db, self.organization_id, preferred_source='sumit')
            if source != 'sumit' or not hasattr(connector, 'add_expense'):
                raise ActionValidationError('SUMIT expense writing is not supported by this connection')
            if {'source': source, 'connection_id': connection_id, 'company_id': str(getattr(connector, 'company_id', None))} != payload['provider_target']:
                raise ActionConflictError('The provider connection no longer matches the approved destination')
            fields = payload['source_fields']
            source_row = self.db.query(DocumentIntake).filter_by(id=payload['document_id'], organization_id=self.organization_id).one()
            request = ExpenseRequest(supplier_name=fields['supplier_name'], supplier_tax_id=fields['supplier_tax_id'],
                amount=Decimal(fields['amount']), vat_amount=Decimal(fields['vat_amount']), expense_date=fields['expense_date'],
                category=fields['category'], notes=fields['notes'], invoice_number=fields['invoice_number'],
                receipt_file=source_row.content_base64, receipt_filename=fields['filename'], is_draft=True)
            expense.status = 'submitting'
            self.actions.claim_approved_for_execution(approval_id, action_type='sumit_writeback', submitted_payload=payload)
        except Exception:
            self.db.rollback(); raise
        try:
            response = await connector.add_expense(request)
            references = [str(response[key]) for key in ('expense_id', 'DocumentID') if isinstance(response, dict) and response.get(key) is not None]
            if not references or any(not ref.isdigit() or int(ref) <= 0 for ref in references) or len(set(references)) != 1:
                raise ValueError('Provider omitted a consistent document identifier')
            self.db.expire_all()
            expense = self._expense(expense_id)
            try:
                source_matches = self._snapshot(expense, in_flight=True) == payload
            except (ActionConflictError, ActionValidationError, ValueError):
                source_matches = False
            # An acknowledgement remains evidence even when a concurrent source
            # update requires a decision. Never erase its reference or replay it.
            expense.sumit_expense_id = references[0]
            expense.status = 'submitted' if source_matches else 'source_conflict'
            expense.filing_error = None if source_matches else 'Source changed during provider execution; preserve the acknowledgement and review both versions'
            self.actions.mark_executed(approval_id, provider_reference=references[0], execution_result={
                'provider_document_id': references[0], 'acknowledgement': 'DocumentID',
                'provider_target': payload['provider_target'],
                'source_matches_approved': source_matches,
                'source_sha256': payload['source_sha256'], 'official_books_verified': False, 'readback_required': True})
        except Exception as exc:
            self.db.rollback()
            expense = self._expense(expense_id)
            expense.status = 'outcome_unknown'
            expense.filing_error = 'Provider outcome is unknown; do not retry or create a replacement document'
            self.actions.mark_failed(approval_id, error=f'Expense provider outcome unknown: {type(exc).__name__}')
            raise ActionStateError('Provider outcome is unknown; independent review is required') from exc
        return dict(ExpenseFilingService._serialize(expense), **self.status(expense_id))
