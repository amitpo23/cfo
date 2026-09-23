"""Offline read-only source previews preserve bytes and show each explicit page."""
import base64
import hashlib
from io import BytesIO
from PIL import Image
from reportlab.pdfgen import canvas
from cfo.database import SessionLocal
from cfo.models import DocumentIntake, Expense


def upload(client, identity, content, media='application/pdf'):
    response = client.post('/api/expenses/intake', headers=identity['headers'], json={
        'content_base64': base64.b64encode(content).decode(), 'media_type': media, 'filename': 'synthetic-source'})
    assert response.status_code == 200
    return response.json()['document_id']


def test_pdf_preview_renders_each_page_without_processing_or_mutating_source(client, fresh_org):
    identity, foreign = fresh_org(), fresh_org()
    data = BytesIO(); pdf = canvas.Canvas(data)
    for label in ('FIRST SOURCE PAGE', 'SECOND SOURCE PAGE'):
        pdf.drawString(50, 700, label); pdf.showPage()
    pdf.save(); content = data.getvalue(); doc = upload(client, identity, content)
    pages = []
    for page in (1, 2):
        response = client.get(f'/api/expenses/intake/{doc}/preview?page={page}', headers=identity['headers'])
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['page'] == page and result['page_count'] == 2
        assert result['source_sha256'] == hashlib.sha256(content).hexdigest()
        raw = base64.b64decode(result['content_base64']); pages.append(raw)
        with Image.open(BytesIO(raw)) as image:
            assert image.format == 'PNG' and max(image.size) <= 1200
    assert pages[0] != pages[1]
    assert client.get(f'/api/expenses/intake/{doc}/preview?page=3', headers=identity['headers']).status_code == 400
    assert client.get(f'/api/expenses/intake/{doc}/preview', headers=foreign['headers']).status_code == 404
    assert client.get(f'/api/expenses/intake/{doc}/source', headers=identity['headers']).content == content
    with SessionLocal() as db:
        row = db.get(DocumentIntake, doc)
        assert row.status == 'queued' and row.version == 1 and row.attempts == 0
        assert db.query(Expense).filter_by(organization_id=identity['org_id']).count() == 0


def test_corrupted_source_cannot_be_previewed_as_the_preserved_original(client, fresh_org):
    identity = fresh_org(); doc = upload(client, identity, b'%PDF corrupt synthetic')
    with SessionLocal() as db:
        db.get(DocumentIntake, doc).content_base64 = base64.b64encode(b'changed source').decode(); db.commit()
    assert client.get(f'/api/expenses/intake/{doc}/preview', headers=identity['headers']).status_code == 409
    assert client.get(f'/api/expenses/intake/{doc}/source', headers=identity['headers']).status_code == 409


def test_unreadable_pdf_has_an_explicit_preview_failure_and_original_download(client, fresh_org):
    identity = fresh_org(); raw = b'%PDF unreadable synthetic'; doc = upload(client, identity, raw)
    response = client.get(f'/api/expenses/intake/{doc}/preview', headers=identity['headers'])
    assert response.status_code == 400
    assert client.get(f'/api/expenses/intake/{doc}/source', headers=identity['headers']).content == raw


def test_multiframe_tiff_preview_preserves_page_count_and_original(client, fresh_org):
    identity = fresh_org(); data = BytesIO()
    first, second = Image.new('RGB', (40, 30), 'white'), Image.new('RGB', (40, 30), 'black')
    first.save(data, format='TIFF', save_all=True, append_images=[second]); first.close(); second.close()
    doc = upload(client, identity, data.getvalue(), 'image/tiff')
    result = client.get(f'/api/expenses/intake/{doc}/preview?page=2', headers=identity['headers'])
    assert result.status_code == 200, result.text
    assert result.json()['page_count'] == 2
    with Image.open(BytesIO(base64.b64decode(result.json()['content_base64']))) as image:
        assert image.getpixel((0, 0)) == (0, 0, 0)
    assert client.get(f'/api/expenses/intake/{doc}/source', headers=identity['headers']).content == data.getvalue()
