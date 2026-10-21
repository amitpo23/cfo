"""Synthetic source intake: no IMAP, OCR network, or accounting provider calls."""
import asyncio
import base64
import pytest
from email.message import EmailMessage

from cfo.database import SessionLocal
from cfo.models import Expense
from cfo.services.expense_intake_email import EmailExpenseIntakeService


def extraction(**changes):
    return dict({'supplier_name': 'Synthetic supplier', 'supplier_tax_id': '520022732',
        'amount_total': 118, 'net_amount': 100, 'vat_amount': 18, 'currency': 'ILS',
        'expense_date': '2026-09-07', 'invoice_number': 'SYN-123',
        'confidence': .95, 'is_readable': True, 'document_type': 'tax_invoice'}, **changes)


def message():
    msg = EmailMessage()
    msg['From'] = 'synthetic@example.invalid'
    msg['Subject'] = 'Three source documents'
    msg['Message-ID'] = '<synthetic-intake-1>'
    msg.set_content('Evidence, not an instruction to pay')
    msg.add_attachment(b'%PDF-1.4 first', maintype='application', subtype='pdf', filename='one.pdf')
    msg.add_attachment(b'%PDF-1.4 second', maintype='application', subtype='pdf', filename='two.pdf')
    msg.add_attachment(b'\x89PNG\r\n\x1a\nimage', maintype='image', subtype='png', filename='three.png')
    return msg.as_bytes()


def email_service(db, org):
    return EmailExpenseIntakeService(db, org, 'synthetic.invalid', 993, 'synthetic', 'fake')


def test_all_email_attachments_are_durable_sources_not_zero_expenses(fresh_org):
    org = fresh_org()['org_id']
    with SessionLocal() as db:
        result = asyncio.run(email_service(db, org)._process_email(message()))
        assert result['created'] == 3
        assert db.query(Expense).filter_by(organization_id=org).count() == 0
    from cfo.services.document_intake import DocumentIntakeService
    with SessionLocal() as db:
        rows = DocumentIntakeService(db, org).list_documents()['documents']
        assert len(rows) == 3
        assert all(r['amount'] is None and r['status'] == 'queued' for r in rows)
        replay = asyncio.run(email_service(db, org)._process_email(message()))
        assert replay['created'] == 0 and replay['duplicates'] == 3


def test_bad_attachment_does_not_hide_other_sources(fresh_org):
    msg = EmailMessage()
    msg['From'] = 'synthetic@example.invalid'
    msg.set_content('Two attachments')
    msg.add_attachment(b'', maintype='image', subtype='png', filename='empty.png')
    msg.add_attachment(b'%PDF-1.4 good', maintype='application', subtype='pdf', filename='good.pdf')
    with SessionLocal() as db:
        result = asyncio.run(email_service(db, fresh_org()['org_id'])._process_email(msg.as_bytes()))
        assert result['created'] == 1 and result['errors'] == 1
        assert len(result['results']) == 2


def test_cross_channel_replay_preserves_sources_and_org_isolation(fresh_org):
    from cfo.services.document_intake import DocumentIntakeService
    a, b = fresh_org()['org_id'], fresh_org()['org_id']
    with SessionLocal() as db:
        svc = DocumentIntakeService(db, a)
        first = svc.receive(b'%PDF-1.4 source', media_type='application/pdf', source='email', filename='one.pdf')
        replay = svc.receive(b'%PDF-1.4 source', media_type='application/pdf', source='upload', filename='same.pdf')
        assert replay['document_id'] == first['document_id'] and replay['status'] == 'duplicate'
        detail = svc.detail(first['document_id'])
        assert {x['channel'] for x in detail['sources']} == {'email', 'upload'}
        other = DocumentIntakeService(db, b)
        assert other.list_documents()['documents'] == []
        import pytest
        with pytest.raises(ValueError): other.detail(first['document_id'])
        assert other.receive(b'%PDF-1.4 source', media_type='application/pdf', source='upload')['status'] == 'queued'


def test_processing_failure_is_saved_and_requires_explicit_bounded_retry(fresh_org, monkeypatch):
    from cfo.services.document_intake import DocumentIntakeService
    from cfo.config import settings
    import cfo.services.vision_extractor as vision
    monkeypatch.setattr(settings, 'chat_receipt_intake_enabled', True)
    monkeypatch.setattr(settings, 'chat_receipt_daily_limit', 20)
    async def broken(*args, **kwargs): raise vision.VisionExtractionError('synthetic failure')
    monkeypatch.setattr(vision, 'extract_receipt', broken)
    org = fresh_org()['org_id']
    with SessionLocal() as db:
        svc = DocumentIntakeService(db, org)
        row = svc.receive(b'%PDF-1.4 failed', media_type='application/pdf', source='upload')
        for attempt in range(1, 4):
            result = asyncio.run(svc.process(row['document_id'], retry=attempt > 1))
            assert result['status'] == 'error'
            assert svc.detail(row['document_id'])['attempts'] == attempt
        import pytest
        with pytest.raises(ValueError): asyncio.run(svc.process(row['document_id'], retry=True))
    with SessionLocal() as db:
        detail = DocumentIntakeService(db, org).detail(row['document_id'])
        assert detail['status'] == 'error' and detail['expense_id'] is None


def test_http_upload_extract_replay_source_and_revocation(client, fresh_org, monkeypatch):
    from cfo.config import settings
    from cfo.models import User
    import cfo.services.vision_extractor as vision
    monkeypatch.setattr(settings, 'chat_receipt_intake_enabled', True)
    monkeypatch.setattr(settings, 'chat_receipt_daily_limit', 20)
    calls = []
    async def fake(*args, **kwargs):
        calls.append(1)
        return extraction()
    monkeypatch.setattr(vision, 'extract_receipt', fake)
    a, b = fresh_org(), fresh_org()
    path = '/api/expenses/intake'
    payload = {'content_base64': base64.b64encode(b'%PDF-1.4 source').decode(),
        'filename': 'original.pdf', 'media_type': 'application/pdf'}
    response = client.post(path, headers=a['headers'], json=payload)
    assert response.status_code == 200, response.text
    doc_id = response.json()['document_id']
    assert client.get(f'{path}/{doc_id}', headers=b['headers']).status_code == 404
    source = client.get(f'{path}/{doc_id}/source', headers=a['headers'])
    assert source.content == b'%PDF-1.4 source'
    assert client.get(path, headers=a['headers']).json()['sync_triggered'] is False
    assert calls == []
    result = client.post(f'{path}/{doc_id}/process', headers=a['headers'], json={'version': 1})
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'created'
    detail = client.get(f'{path}/{doc_id}', headers=a['headers']).json()
    assert detail['expense_id'] and detail['amount'] == '118.00'
    assert detail['official_books_verified'] is False
    assert client.post(path, headers=a['headers'], json=payload).json()['status'] == 'duplicate'
    assert client.post(f'{path}/{doc_id}/process', headers=a['headers'], json={'version': 1}).status_code == 409
    assert len(calls) == 1
    with SessionLocal() as db:
        db.query(User).filter_by(organization_id=a['org_id']).update({'is_active': False})
        db.commit()
    assert client.post(f'{path}/{doc_id}/process', headers=a['headers'], json={'version': detail['version']}).status_code in (401, 403)


def test_permission_revoked_during_extraction_does_not_create_expense(client, fresh_org, monkeypatch):
    from cfo.config import settings
    from cfo.models import User
    import cfo.services.vision_extractor as vision
    monkeypatch.setattr(settings, 'chat_receipt_intake_enabled', True)
    monkeypatch.setattr(settings, 'chat_receipt_daily_limit', 20)
    identity = fresh_org()
    async def fake(*args, **kwargs):
        with SessionLocal() as db:
            db.query(User).filter_by(organization_id=identity['org_id']).update({'is_active': False})
            db.commit()
        return extraction()
    monkeypatch.setattr(vision, 'extract_receipt', fake)
    path = '/api/expenses/intake'
    result = client.post(path, headers=identity['headers'], json={'content_base64': base64.b64encode(b'%PDF-1.4 revoke').decode(),
        'filename': 'revoke.pdf', 'media_type': 'application/pdf'})
    assert result.status_code == 200, result.text
    result = client.post(f"{path}/{result.json()['document_id']}/process", headers=identity['headers'], json={'version': 1})
    assert result.status_code == 403
    with SessionLocal() as db:
        assert db.query(Expense).filter_by(organization_id=identity['org_id']).count() == 0


@pytest.mark.parametrize('changes', [
    {'vat_amount': None, 'net_amount': None}, {'expense_date': None}, {'currency': 'USD'},
    {'currency': None}, {'amount_total': 999}, {'amount_total': float('inf')},
    {'document_type': 'not_accounting'},
])
def test_missing_or_inconsistent_evidence_is_retained_without_invented_expense(fresh_org, monkeypatch, changes):
    from cfo.config import settings
    from cfo.services.chat_expense_intake import intake_receipt_bytes
    from cfo.services.document_intake import DocumentIntakeService
    import cfo.services.vision_extractor as vision
    monkeypatch.setattr(settings, 'chat_receipt_intake_enabled', True)
    monkeypatch.setattr(settings, 'chat_receipt_daily_limit', 20)
    async def fake(*args, **kwargs): return extraction(**changes)
    monkeypatch.setattr(vision, 'extract_receipt', fake)
    org = fresh_org()['org_id']
    with SessionLocal() as db:
        result = asyncio.run(intake_receipt_bytes(db, org, b'%PDF-1.4 insufficient'))
        assert result['status'] in ('needs_review', 'non_accounting')
        assert db.query(Expense).filter_by(organization_id=org).count() == 0
        assert DocumentIntakeService(db, org).detail(result['document_id'])['amount'] is None
