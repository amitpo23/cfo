"""Follow-up acceptance tests: reviewed source fields, never accounting/payment approval."""
import base64
import json
import asyncio
import pytest
from cfo.database import SessionLocal
from cfo.models import Expense, Note


def test_moshko_review_uses_confirmation_and_rechecks_actor(client, fresh_org):
    from cfo.services.ai_chat_tools import TOOLS
    from cfo.models import User
    identity = fresh_org()
    doc = upload(client, identity)
    tool = TOOLS['review_document_source']
    assert tool.category == 'write' and tool.needs_user and tool.policy_action == 'expenses.review'
    payload = correction()
    with SessionLocal() as db:
        actor = db.query(User).filter_by(organization_id=identity['org_id']).one()
        with pytest.raises(PermissionError):
            asyncio.run(tool.fn(db, identity['org_id'], document_id=doc, **payload))
        result = asyncio.run(tool.fn(db, identity['org_id'], document_id=doc, _user_id=actor.id, **payload))
        assert result['status'] == 'created'
        other_doc = upload(client, identity, 'revoked')
        actor.is_active = False
        db.commit()
        with pytest.raises(PermissionError):
            asyncio.run(tool.fn(db, identity['org_id'], document_id=other_doc, _user_id=actor.id, **payload))


def upload(client, identity, suffix='one'):
    response = client.post('/api/expenses/intake', headers=identity['headers'], json={
        'content_base64': base64.b64encode(('%PDF-1.4 review ' + suffix).encode()).decode(),
        'filename': 'review.pdf', 'media_type': 'application/pdf'})
    assert response.status_code == 200, response.text
    return response.json()['document_id']


def correction(version=1):
    return {'version': version, 'reason': 'Reviewed these fields directly against the preserved synthetic source',
        'fields': {'supplier_name': 'Synthetic supplier', 'supplier_tax_id': '520022732',
            'expense_date': '2026-09-07', 'invoice_number': 'SYN-REVIEW-1',
            'amount_total': 118, 'net_amount': 100, 'vat_amount': 18, 'currency': 'ILS',
            'document_type': 'tax_invoice'}}


def test_review_creates_one_draft_and_preserves_original_and_decision(client, fresh_org):
    identity = fresh_org()
    doc = upload(client, identity)
    source = client.get(f'/api/expenses/intake/{doc}/source', headers=identity['headers']).content
    result = client.post(f'/api/expenses/intake/{doc}/review', headers=identity['headers'], json=correction())
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'created'
    assert client.post(f'/api/expenses/intake/{doc}/review', headers=identity['headers'], json=correction()).status_code == 409
    detail = client.get(f'/api/expenses/intake/{doc}', headers=identity['headers']).json()
    assert detail['approval_status'] == 'source_reviewed'
    assert detail['official_books_verified'] is False
    assert client.get(f'/api/expenses/intake/{doc}/source', headers=identity['headers']).content == source
    with SessionLocal() as db:
        expense = db.query(Expense).filter_by(organization_id=identity['org_id']).one()
        assert expense.status == 'pending' and expense.total == 118
        notes = db.query(Note).filter_by(organization_id=identity['org_id'], entity_type='document_intake', entity_id=doc).all()
        assert len(notes) == 1 and notes[0].created_by is not None
        assert json.loads(notes[0].text)['reason'] == correction()['reason']


def test_source_review_is_tenant_scoped_and_rejects_unbalanced_fields(client, fresh_org):
    a, b = fresh_org(), fresh_org()
    doc = upload(client, a)
    assert client.post(f'/api/expenses/intake/{doc}/review', headers=b['headers'], json=correction()).status_code == 404
    payload = correction(); payload['fields']['amount_total'] = 999
    result = client.post(f'/api/expenses/intake/{doc}/review', headers=a['headers'], json=payload)
    assert result.status_code == 400
    with SessionLocal() as db:
        assert db.query(Expense).filter_by(organization_id=a['org_id']).count() == 0
    assert client.get(f'/api/expenses/intake/{doc}', headers=a['headers']).json()['version'] == 1


def test_source_review_reuses_business_duplicate_gate(client, fresh_org):
    a = fresh_org()
    first, second = upload(client, a, 'first'), upload(client, a, 'different_scan')
    assert client.post(f'/api/expenses/intake/{first}/review', headers=a['headers'], json=correction()).status_code == 200
    result = client.post(f'/api/expenses/intake/{second}/review', headers=a['headers'], json=correction())
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'duplicate'
    with SessionLocal() as db:
        assert db.query(Expense).filter_by(organization_id=a['org_id']).count() == 1


def test_vision_normalization_does_not_invent_currency():
    from cfo.services.vision_extractor import _normalize
    assert _normalize({'currency': None})['currency'] is None
    assert _normalize({'currency': ''})['currency'] is None
    assert _normalize({'currency': 'ILS'})['currency'] == 'ILS'


def test_report_actions_record_the_authenticated_actor(client, fresh_org):
    identity = fresh_org()
    response = client.post('/api/financial/reports/templates', headers=identity['headers'], json={
        'name': 'Synthetic actor attribution', 'report_type': 'profit_loss',
        'columns': [{'field_name': 'amount', 'display_name': 'Amount', 'data_type': 'currency'}]})
    assert response.status_code == 200
    created_by = response.json()['data']['created_by']
    assert created_by.startswith('user:')
    report = client.post('/api/financial/reports/generate', headers=identity['headers'], json={
        'template_id': response.json()['data']['template_id'], 'format': 'json'})
    assert report.status_code == 200
    assert report.json()['data']['generated_by'] == created_by
