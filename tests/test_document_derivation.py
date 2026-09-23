"""PDF page provenance and atomic source transformations, entirely synthetic."""
import asyncio
import base64
from io import BytesIO
from contextlib import closing
import pytest
import pypdfium2 as pdfium
from reportlab.pdfgen import canvas
from cfo.database import SessionLocal
from cfo.models import DocumentIntake
from cfo.services.document_intake import DocumentIntakeService


def pdf(*texts):
    output = BytesIO(); document = canvas.Canvas(output)
    for text in texts:
        document.drawString(50, 700, text); document.showPage()
    document.save(); return output.getvalue()


def upload(client, org, data, name='source.pdf'):
    result = client.post('/api/expenses/intake', headers=org['headers'], json={
        'content_base64': base64.b64encode(data).decode(), 'media_type': 'application/pdf', 'filename': name})
    assert result.status_code == 200
    return result.json()['document_id']


def plan(doc):
    return {'parents': [{'document_id': doc, 'version': 1}],
        'outputs': [{'filename': 'first.pdf', 'pages': [{'document_id': doc, 'page': 1}]},
                    {'filename': 'second.pdf', 'pages': [{'document_id': doc, 'page': 2}]}],
        'reason': 'Separate two synthetic source documents after inspecting their page boundaries'}


def derive(client, org, payload):
    return client.post('/api/expenses/intake/derive', headers=org['headers'], json=payload)


def test_split_preserves_original_pages_restart_and_replay(client, fresh_org):
    org = fresh_org(); content = pdf('FIRST', 'SECOND'); doc = upload(client, org, content)
    response = derive(client, org, plan(doc))
    assert response.status_code == 200, response.text
    result = response.json(); assert len(result['outputs']) == 2
    assert derive(client, org, plan(doc)).json() == result
    for i, output in enumerate(result['outputs']):
        raw = client.get(f"/api/expenses/intake/{output['document_id']}/source", headers=org['headers']).content
        with closing(pdfium.PdfDocument(raw)) as document:
            assert len(document) == 1
            page = document[0]; textpage = page.get_textpage()
            assert ('FIRST', 'SECOND')[i] in textpage.get_text_range()
            textpage.close(); page.close()
        detail = client.get(f"/api/expenses/intake/{output['document_id']}", headers=org['headers']).json()
        assert detail['lineage']['parents'][0]['pages'] == [i + 1]
        assert detail['lineage']['derivation_id'] == result['derivation_id']
    with SessionLocal() as db:
        service = DocumentIntakeService(db, org['org_id'])
        assert service.source(doc)[0] == content
        assert service.detail(doc)['status'] == 'superseded'
        with pytest.raises(ValueError): asyncio.run(service.process(doc, expected_version=2))
        assert db.query(DocumentIntake).filter_by(organization_id=org['org_id']).count() == 3


def test_merge_preserves_order_and_parent_identity(client, fresh_org):
    org = fresh_org(); a = upload(client, org, pdf('A')); b = upload(client, org, pdf('B'))
    payload = {'parents': [{'document_id': a, 'version': 1}, {'document_id': b, 'version': 1}],
        'outputs': [{'filename': 'merged.pdf', 'pages': [{'document_id': b, 'page': 1}, {'document_id': a, 'page': 1}]}],
        'reason': 'These pages are one synthetic accounting document, in the specified order'}
    result = derive(client, org, payload)
    assert result.status_code == 200, result.text
    raw = client.get(f"/api/expenses/intake/{result.json()['outputs'][0]['document_id']}/source", headers=org['headers']).content
    with closing(pdfium.PdfDocument(raw)) as document:
        assert len(document) == 2
        for i, expected in enumerate(('B', 'A')):
            page = document[i]; textpage = page.get_textpage()
            assert expected in textpage.get_text_range(); textpage.close(); page.close()


@pytest.mark.parametrize('case', ['missing_page', 'duplicate_page', 'foreign_source', 'stale_version', 'unreadable'])
def test_transform_rejects_ambiguous_or_stale_source_atomically(client, fresh_org, case):
    org = fresh_org(); foreign = fresh_org()
    doc = upload(client, org, b'bad PDF' if case == 'unreadable' else pdf('ONE', 'TWO'))
    payload = plan(doc)
    if case == 'missing_page': payload['outputs'] = payload['outputs'][:1]
    if case == 'duplicate_page': payload['outputs'][1]['pages'][0]['page'] = 1
    if case == 'foreign_source': payload['parents'][0]['document_id'] = upload(client, foreign, pdf('FOREIGN'))
    if case == 'stale_version': payload['parents'][0]['version'] = 9
    response = derive(client, org, payload)
    assert response.status_code in (400, 404, 409), response.text
    with SessionLocal() as db:
        rows = db.query(DocumentIntake).filter_by(organization_id=org['org_id']).all()
        assert len(rows) == 1 and rows[0].status == 'queued' and rows[0].version == 1


def test_transform_refuses_already_processed_source_and_revoked_role(client, fresh_org):
    from cfo.models import User
    org = fresh_org(); doc = upload(client, org, pdf('ONE', 'TWO'))
    with SessionLocal() as db:
        row = db.get(DocumentIntake, doc); row.status = 'created'; db.commit()
    assert derive(client, org, plan(doc)).status_code == 409
    with SessionLocal() as db:
        actor = db.query(User).filter_by(organization_id=org['org_id']).one()
        actor.is_active = False; db.commit()
    assert derive(client, org, plan(doc)).status_code in (401, 403)


def test_superseded_source_review_and_source_changes_remain_blocked(client, fresh_org):
    org = fresh_org(); doc = upload(client, org, pdf('ONE', 'TWO'))
    assert derive(client, org, plan(doc)).status_code == 200
    result = client.post(f'/api/expenses/intake/{doc}/review', headers=org['headers'], json={
        'version': 2, 'reason': 'Synthetic source was already split into individual documents', 'fields': {}})
    assert result.status_code == 409
    with SessionLocal() as db:
        row = db.get(DocumentIntake, doc); row.content_base64 = base64.b64encode(pdf('CHANGED')).decode(); db.commit()
    assert derive(client, org, plan(doc)).status_code == 409


def test_moshko_transform_is_confirmed_and_uses_same_provenance(client, fresh_org):
    from cfo.services.ai_chat_tools import TOOLS
    from cfo.models import User
    org = fresh_org(); doc = upload(client, org, pdf('ONE', 'TWO'))
    tool = TOOLS['derive_document_sources']
    assert tool.category == 'write' and tool.needs_user and tool.policy_action == 'expenses.review'
    with SessionLocal() as db:
        actor = db.query(User).filter_by(organization_id=org['org_id']).one()
        result = asyncio.run(tool.fn(db, org['org_id'], _user_id=actor.id, **plan(doc)))
    assert result == derive(client, org, plan(doc)).json()


def test_image_only_ocr_fallback_cannot_silently_drop_later_pdf_pages():
    from cfo.services.vision_extractor import _pdf_to_image, VisionExtractionError
    with pytest.raises(VisionExtractionError, match='PDF'):
        _pdf_to_image(pdf('FIRST', 'IMPORTANT SECOND PAGE'))
    image, media = _pdf_to_image(pdf('ONE PAGE'))
    assert image.startswith(b'\x89PNG') and media == 'image/png'
