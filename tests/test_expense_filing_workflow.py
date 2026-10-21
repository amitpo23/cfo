"""Source-bound provider expense filing; all provider calls are synthetic."""
import base64
from uuid import uuid4
import pytest
from cfo.auth import create_access_token, get_password_hash
from cfo.database import SessionLocal
from cfo.models import Expense, IrreversibleActionRequest, OrganizationSigningAuthority, Organization, User, UserRole
from cfo.services import membership_service


def source_expense(client, identity, suffix='1'):
    with SessionLocal() as db:
        db.get(Organization, identity['org_id']).api_credentials = {'company_id': '123', 'api_key': 'synthetic-only'}
        db.commit()
    source = client.post('/api/expenses/intake', headers=identity['headers'], json={
        'content_base64': base64.b64encode(('%PDF-1.4 synthetic filing ' + suffix).encode()).decode(),
        'filename': 'source.pdf', 'media_type': 'application/pdf'})
    assert source.status_code == 200
    review = client.post(f"/api/expenses/intake/{source.json()['document_id']}/review", headers=identity['headers'], json={
        'version': 1, 'reason': 'Source invoice fields have been reviewed against the synthetic original',
        'fields': {'supplier_name': 'Synthetic office supplier', 'supplier_tax_id': '520022732',
            'invoice_number': 'SYN-FILE-' + suffix, 'expense_date': '2026-09-07', 'currency': 'ILS',
            'amount_total': 118, 'net_amount': 100, 'vat_amount': 18, 'document_type': 'tax_invoice'}})
    assert review.status_code == 200, review.text
    return review.json()['expense_id']


def approve(client, identity, action_id):
    with SessionLocal() as db:
        owner = db.query(User).filter_by(organization_id=identity['org_id']).one()
        actor = User(organization_id=identity['org_id'], email=f'signer-{uuid4()}@example.com',
            password_hash=get_password_hash('synthetic-password'), full_name='Synthetic signer', role=UserRole.ADMIN, is_active=True)
        db.add(actor); db.flush()
        membership_service.grant(db, organization_id=identity['org_id'], user_id=actor.id,
            role=UserRole.ADMIN, granted_by_user_id=owner.id, status=membership_service.ACTIVE)
        db.add(OrganizationSigningAuthority(organization_id=identity['org_id'], user_id=actor.id,
            authority_type='authorized_signer', action_types=['sumit_writeback'], is_active=True,
            granted_by_user_id=owner.id)); db.commit()
        headers = {'Authorization': f'Bearer {create_access_token({"sub": actor.id})}'}
    response = client.post(f'/api/approvals/{action_id}/approve', headers=headers)
    assert response.status_code == 200, response.text
    return headers


def proposal(client, identity, expense):
    result = client.post(f'/api/expenses/{expense}/filing-proposal', headers=identity['headers'], json={
        'reason': 'Create the reviewed source expense in SUMIT; official books remain unverified'})
    assert result.status_code == 200, result.text
    return result.json()['approval_request_id']


def test_legacy_filing_requires_approval_before_provider_resolution(client, fresh_org, monkeypatch):
    identity = fresh_org(); expense = source_expense(client, identity)
    def forbidden(*args, **kwargs): raise AssertionError('Provider resolved without reviewed approval')
    monkeypatch.setattr('cfo.services.sync_engine.get_connector_for_org', forbidden)
    result = client.post(f'/api/expenses/{expense}/file', headers=identity['headers'])
    assert result.status_code == 409, result.text
    assert client.post('/api/expenses/file-all', headers=identity['headers']).status_code == 409


def test_filing_approval_preserves_source_and_acknowledgement_is_not_books(client, fresh_org, monkeypatch):
    identity = fresh_org(); expense = source_expense(client, identity)
    action_id = proposal(client, identity, expense)
    assert proposal(client, identity, expense) == action_id
    visible = client.get(f'/api/expenses/{expense}/filing-status', headers=identity['headers']).json()
    assert visible['approval_payload']['source_fields']['invoice_number'] == 'SYN-FILE-1'
    with SessionLocal() as db:
        action = db.get(IrreversibleActionRequest, action_id)
        assert action.payload['expense_id'] == expense
        assert action.payload['amount'] == '118.00' and action.payload['currency'] == 'ILS'
        assert 'receipt_file' not in str(action.payload) and action.payload['source_sha256']
    approve(client, identity, action_id)
    calls = []
    class FakeConnector:
        company_id = '123'
        async def add_expense(self, request):
            calls.append(request); return {'expense_id': '991', 'DocumentID': 991}
    monkeypatch.setattr('cfo.services.sync_engine.get_connector_for_org', lambda *a, **kw: (FakeConnector(), None, 'sumit'))
    headers = dict(identity['headers'], **{'X-Rezef-Approval-Id': str(action_id)})
    result = client.post(f'/api/expenses/{expense}/file', headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()['data']['status'] == 'submitted'
    assert result.json()['data']['official_books_verified'] is False
    assert client.post(f'/api/expenses/{expense}/file', headers=headers).status_code == 409
    assert len(calls) == 1 and calls[0].invoice_number == 'SYN-FILE-1'
    assert calls[0].is_draft is True  # Provider tax/book classification remains a separate review.
    with SessionLocal() as db:
        assert db.get(Expense, expense).sumit_expense_id == '991'
        assert db.get(IrreversibleActionRequest, action_id).status == 'executed'


@pytest.mark.parametrize('response', [None, {}, {'expense_id': None}])
def test_unknown_result_blocks_replay_and_new_proposal(client, fresh_org, monkeypatch, response):
    identity = fresh_org(); expense = source_expense(client, identity); action_id = proposal(client, identity, expense)
    approve(client, identity, action_id); calls = []
    class FakeConnector:
        company_id = '123'
        async def add_expense(self, request):
            calls.append(1)
            if response is None: raise TimeoutError('Synthetic ambiguous external outcome')
            return response
    monkeypatch.setattr('cfo.services.sync_engine.get_connector_for_org', lambda *a, **kw: (FakeConnector(), None, 'sumit'))
    headers = dict(identity['headers'], **{'X-Rezef-Approval-Id': str(action_id)})
    assert client.post(f'/api/expenses/{expense}/file', headers=headers).status_code == 502
    assert client.post(f'/api/expenses/{expense}/file', headers=headers).status_code == 409
    assert client.post(f'/api/expenses/{expense}/filing-proposal', headers=identity['headers'], json={
        'reason': 'Do not repeat an ambiguous provider operation with a new approval'}).status_code == 409
    assert calls == [1]
    with SessionLocal() as db:
        assert db.get(Expense, expense).status == 'outcome_unknown'


def test_changed_source_and_foreign_org_cannot_execute_approved_filing(client, fresh_org, monkeypatch):
    identity, foreign = fresh_org(), fresh_org(); expense = source_expense(client, identity)
    action_id = proposal(client, identity, expense); approve(client, identity, action_id)
    def forbidden(*args, **kwargs): raise AssertionError('Provider resolved for stale or foreign source')
    monkeypatch.setattr('cfo.services.sync_engine.get_connector_for_org', forbidden)
    assert client.post(f'/api/expenses/{expense}/filing-proposal', headers=foreign['headers'], json={
        'reason': 'A foreign organization must not be able to propose this expense'}).status_code == 404
    with SessionLocal() as db:
        db.get(Expense, expense).total = 999; db.commit()
    result = client.post(f'/api/expenses/{expense}/file', headers=dict(identity['headers'], **{'X-Rezef-Approval-Id': str(action_id)}))
    assert result.status_code == 409, result.text


def test_existing_provider_document_is_never_replaced_or_cancelled_implicitly(client, fresh_org, monkeypatch):
    identity = fresh_org(); expense = source_expense(client, identity)
    with SessionLocal() as db:
        row = db.get(Expense, expense); row.source = 'sumit'; row.external_id = 'existing-991'; db.commit()
    def forbidden(*args, **kwargs): raise AssertionError('Existing provider document must be reviewed, not replaced')
    monkeypatch.setattr('cfo.services.sync_engine.get_connector_for_org', forbidden)
    result = client.post(f'/api/expenses/{expense}/filing-proposal', headers=identity['headers'], json={
        'reason': 'Existing provider evidence must be identified before creating another document'})
    assert result.status_code == 409, result.text


def test_submitted_expense_cannot_be_edited_into_a_different_approved_source(client, fresh_org):
    identity = fresh_org(); expense = source_expense(client, identity)
    with SessionLocal() as db:
        db.get(Expense, expense).status = 'submitted'; db.commit()
    response = client.patch(f'/api/expenses/{expense}', headers=identity['headers'], json={'amount': 1})
    assert response.status_code == 409, response.text
    with SessionLocal() as db: assert db.get(Expense, expense).amount == 100


def test_generic_invoice_label_is_not_assumed_to_be_a_tax_invoice(client, fresh_org):
    from cfo.services.chat_expense_intake import _expense_from_extraction
    identity = fresh_org()
    with SessionLocal() as db:
        result = _expense_from_extraction(db, identity['org_id'], b'synthetic generic invoice', {
            'supplier_name': 'Office supplier', 'supplier_tax_id': '520022732', 'invoice_number': 'GENERIC',
            'expense_date': '2026-09-07', 'amount_total': 118, 'net_amount': 100, 'vat_amount': 18,
            'currency': 'ILS', 'document_type': 'invoice'}, source='upload', human_reviewed=True)
        expense = db.get(Expense, result['expense_id'])
        assert expense.doc_kind == 'unknown' and expense.vat_claimable is None


def test_moshko_proposal_and_execution_require_the_real_actor():
    from cfo.services.ai_chat_tools import TOOLS
    proposal_tool = TOOLS['propose_expense_filing']
    assert proposal_tool.category == 'write' and proposal_tool.needs_user
    assert proposal_tool.policy_action == 'accounting.writeback.propose'
    execute_tool = TOOLS['file_expense']
    assert execute_tool.needs_user and 'approval_id' in execute_tool.input_schema['required']


def test_unsupported_connector_keeps_approval_unexecuted(client, fresh_org, monkeypatch):
    identity = fresh_org(); expense = source_expense(client, identity)
    action_id = proposal(client, identity, expense); approve(client, identity, action_id)
    monkeypatch.setattr('cfo.services.sync_engine.get_connector_for_org', lambda *a, **kw: (object(), 1, 'sumit'))
    response = client.post(f'/api/expenses/{expense}/file', headers=dict(identity['headers'], **{'X-Rezef-Approval-Id': str(action_id)}))
    assert response.status_code == 400 and 'not supported' in response.text
    with SessionLocal() as db:
        assert db.get(IrreversibleActionRequest, action_id).status == 'approved'
        assert db.get(Expense, expense).status == 'pending'


def test_receipt_recorded_after_approval_stops_creation_before_provider_call(client, fresh_org, monkeypatch):
    identity = fresh_org(); expense = source_expense(client, identity)
    action_id = proposal(client, identity, expense); approve(client, identity, action_id)
    with SessionLocal() as db:
        row = db.get(Expense, expense)
        db.add(Expense(organization_id=identity['org_id'], supplier_name=row.supplier_name,
            supplier_tax_id=row.supplier_tax_id, invoice_number=row.invoice_number, expense_date=row.expense_date,
            amount=row.amount, vat_amount=row.vat_amount, total=row.total, status='filed', source='sumit', external_id='992'))
        db.commit()
    def forbidden(*args, **kwargs): raise AssertionError('Existing receipt was ignored')
    monkeypatch.setattr('cfo.services.sync_engine.get_connector_for_org', forbidden)
    response = client.post(f'/api/expenses/{expense}/file', headers=dict(identity['headers'], **{'X-Rezef-Approval-Id': str(action_id)}))
    assert response.status_code == 409, response.text


def test_source_change_during_provider_call_preserves_acknowledgement_and_queues_conflict(client, fresh_org, monkeypatch):
    identity = fresh_org(); expense = source_expense(client, identity)
    action_id = proposal(client, identity, expense); approve(client, identity, action_id)
    class FakeConnector:
        company_id = '123'
        async def add_expense(self, request):
            with SessionLocal() as db:
                db.get(Expense, expense).total = 999; db.commit()
            return {'DocumentID': 993, 'expense_id': '993'}
    monkeypatch.setattr('cfo.services.sync_engine.get_connector_for_org', lambda *a, **kw: (FakeConnector(), None, 'sumit'))
    response = client.post(f'/api/expenses/{expense}/file', headers=dict(identity['headers'], **{'X-Rezef-Approval-Id': str(action_id)}))
    assert response.status_code == 200, response.text
    assert response.json()['data']['status'] == 'source_conflict'
    with SessionLocal() as db:
        assert db.get(Expense, expense).total == 999 and db.get(Expense, expense).sumit_expense_id == '993'
        action = db.get(IrreversibleActionRequest, action_id)
        assert action.payload['amount'] == '118.00' and action.status == 'executed'
        assert action.execution_result['source_matches_approved'] is False


@pytest.mark.parametrize('state', ['submitting', 'submitted', 'outcome_unknown', 'source_conflict'])
def test_unresolved_provider_evidence_survives_reclassification_and_local_account_filing(client, fresh_org, state):
    from cfo.models import Account, AccountType
    from cfo.services.expense_account_filing import ExpenseFilingError, file_expense_to_account
    from cfo.services.expense_filing_service import ExpenseFilingService
    identity = fresh_org(); expense = source_expense(client, identity)
    with SessionLocal() as db:
        row = db.get(Expense, expense); row.status = state; row.category = 'other'
        account = Account(organization_id=identity['org_id'], name='Synthetic office account', account_type=AccountType.BANK)
        db.add(account); db.commit()
        assert ExpenseFilingService(db, identity['org_id']).classify_uncategorized(reclassify_all=True)['classified'] == 0
        assert db.get(Expense, expense).category == 'other'
        with pytest.raises(ExpenseFilingError, match='provider'):
            file_expense_to_account(db, identity['org_id'], expense, account.id)
        db.refresh(row); assert row.status == state and row.account_id is None
    assert client.patch(f'/api/expenses/{expense}', headers=identity['headers'], json={'amount': 1}).status_code == 409


def test_revoked_executor_cannot_execute_an_earlier_approval(client, fresh_org, monkeypatch):
    identity = fresh_org(); expense = source_expense(client, identity)
    action_id = proposal(client, identity, expense); approve(client, identity, action_id)
    with SessionLocal() as db:
        actor = db.query(User).filter_by(organization_id=identity['org_id']).order_by(User.id).first()
        membership_service.revoke(db, organization_id=identity['org_id'], user_id=actor.id, revoked_by_user_id=actor.id)
        db.commit()
    def forbidden(*args, **kwargs): raise AssertionError('Revoked executor reached provider')
    monkeypatch.setattr('cfo.services.sync_engine.get_connector_for_org', forbidden)
    response = client.post(f'/api/expenses/{expense}/file', headers=dict(identity['headers'], **{'X-Rezef-Approval-Id': str(action_id)}))
    assert response.status_code == 403, response.text
    with SessionLocal() as db: assert db.get(IrreversibleActionRequest, action_id).status == 'approved'


def test_non_admin_cannot_modify_classification_or_source_amounts(client, fresh_org):
    identity = fresh_org(); expense = source_expense(client, identity)
    with SessionLocal() as db:
        actor = db.query(User).filter_by(organization_id=identity['org_id']).one()
        membership_service.grant(db, organization_id=identity['org_id'], user_id=actor.id,
            role=UserRole.VIEWER, granted_by_user_id=actor.id, status=membership_service.ACTIVE)
        actor.role = UserRole.VIEWER; db.commit()
    assert client.patch(f'/api/expenses/{expense}', headers=identity['headers'], json={'amount': 1}).status_code == 403
    assert client.post('/api/expenses/classify?reclassify_all=true', headers=identity['headers']).status_code == 403


def test_source_detail_exposes_filing_approval_separately_from_source_review(client, fresh_org):
    from cfo.models import DocumentIntake
    identity = fresh_org(); expense = source_expense(client, identity)
    action_id = proposal(client, identity, expense)
    with SessionLocal() as db:
        source_id = db.query(DocumentIntake).filter_by(organization_id=identity['org_id'], expense_id=expense).one().id
    result = client.get(f'/api/expenses/intake/{source_id}', headers=identity['headers'])
    assert result.status_code == 200
    assert result.json()['approval_status'] == 'source_reviewed'
    assert result.json()['filing']['approval_request_id'] == action_id
    assert result.json()['filing']['approval_status'] == 'proposed'
    assert result.json()['filing']['official_books_verified'] is False


def test_provider_expense_payload_preserves_explicit_draft_and_source_identity():
    import asyncio
    from decimal import Decimal
    from cfo.integrations.sumit_integration import SumitIntegration
    from cfo.integrations.sumit_models import ExpenseRequest
    provider = SumitIntegration(api_key='synthetic-not-live', company_id='1')
    captured = []
    async def fake_post(path, payload):
        captured.append((path, payload)); return {'DocumentID': 999}
    provider._post = fake_post
    async def run():
        try:
            return await provider.add_expense(ExpenseRequest(supplier_name='Synthetic supplier', supplier_tax_id='520022732',
                amount=Decimal('100'), vat_amount=Decimal('18'), expense_date='2026-09-07', invoice_number='SOURCE-17',
                receipt_file='c3ludGhldGlj', receipt_filename='source.png', is_draft=True))
        finally:
            await provider.client.aclose()
    result = asyncio.run(run())
    path, payload = captured[0]
    assert path == '/accounting/documents/addexpense/'
    assert payload['IsDraft'] is True and payload['ExpenseNumber'] == 'SOURCE-17'
    assert payload['Supplier']['CompanyNumber'] == '520022732'
    assert payload['ExpenseFilename'] == 'source.png' and payload['ExpenseFile'] == 'c3ludGhldGlj'
    assert payload['Lines'][0]['Amount'] == 118
    assert result == {'DocumentID': 999, 'expense_id': '999'}


def test_changed_provider_company_invalidates_existing_approval_without_resolving_provider(client, fresh_org, monkeypatch):
    identity = fresh_org(); expense = source_expense(client, identity)
    action_id = proposal(client, identity, expense); approve(client, identity, action_id)
    with SessionLocal() as db:
        action = db.get(IrreversibleActionRequest, action_id)
        assert action.payload['provider_target'] == {'source': 'sumit', 'connection_id': None, 'company_id': '123'}
        assert 'synthetic-only' not in str(action.payload)
        db.get(Organization, identity['org_id']).api_credentials = {'company_id': '456', 'api_key': 'synthetic-only'}
        db.commit()
    def forbidden(*args, **kwargs): raise AssertionError('Changed provider company reached connector')
    monkeypatch.setattr('cfo.services.sync_engine.get_connector_for_org', forbidden)
    response = client.post(f'/api/expenses/{expense}/file', headers=dict(identity['headers'], **{'X-Rezef-Approval-Id': str(action_id)}))
    assert response.status_code == 409, response.text


def test_signer_can_withdraw_stale_approval_before_execution_and_replace_proposal(client, fresh_org):
    from cfo.models import IrreversibleActionApproval
    identity = fresh_org(); expense = source_expense(client, identity)
    action_id = proposal(client, identity, expense); signer_headers = approve(client, identity, action_id)
    assert client.patch(f'/api/expenses/{expense}', headers=identity['headers'], json={'amount': 200}).status_code == 200
    result = client.post(f'/api/approvals/{action_id}/reject', headers=signer_headers, json={
        'reason': 'Withdraw the stale source approval before any provider execution'})
    assert result.status_code == 200, result.text
    replacement = proposal(client, identity, expense)
    assert replacement != action_id
    with SessionLocal() as db:
        original = db.get(IrreversibleActionRequest, action_id)
        assert original.status == 'rejected' and original.execution_started_at is None
        assert original.payload['amount'] == '118.00'
        assert db.query(IrreversibleActionApproval).filter_by(request_id=action_id).count() == 1
        assert db.get(IrreversibleActionRequest, replacement).payload['amount'] == '218.00'


def test_signer_cannot_withdraw_after_execution_claim(client, fresh_org):
    from cfo.services.irreversible_action_service import IrreversibleActionService
    identity = fresh_org(); expense = source_expense(client, identity)
    action_id = proposal(client, identity, expense); signer_headers = approve(client, identity, action_id)
    with SessionLocal() as db:
        IrreversibleActionService(db, identity['org_id']).claim_for_execution(action_id)
    result = client.post(f'/api/approvals/{action_id}/reject', headers=signer_headers, json={
        'reason': 'Withdrawal cannot undo an already started external request'})
    assert result.status_code == 409, result.text


def test_later_sumit_sync_reuses_acknowledged_document_without_duplicate_or_overwriting_review(client, fresh_org, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from cfo.services.expense_filing_service import ExpenseFilingService
    identity = fresh_org(); expense = source_expense(client, identity)
    action_id = proposal(client, identity, expense); approve(client, identity, action_id)
    class FakeConnector:
        company_id = '123'
        async def add_expense(self, request): return {'DocumentID': 994}
        async def list_documents(self, request):
            return [SimpleNamespace(document_id='994', document_type='16', status='draft', total_amount=118,
                vat_amount=18, customer_name='Provider observed supplier', document_number='SYN-FILE-1')]
    monkeypatch.setattr('cfo.services.sync_engine.get_connector_for_org', lambda *a, **kw: (FakeConnector(), None, 'sumit'))
    response = client.post(f'/api/expenses/{expense}/file', headers=dict(identity['headers'], **{'X-Rezef-Approval-Id': str(action_id)}))
    assert response.status_code == 200
    with SessionLocal() as db:
        result = asyncio.run(ExpenseFilingService(db, identity['org_id']).sync_pending_from_sumit())
        assert result['imported'] == 0 and result['linked_existing_documents'] == 1
        assert db.query(Expense).filter_by(organization_id=identity['org_id']).count() == 1
        row = db.get(Expense, expense)
        assert row.status == 'submitted' and row.supplier_name == 'Synthetic office supplier'
