"""Guarded PostgreSQL races: one page recipe, processing claim and revoked authority."""
import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import patch
from uuid import uuid4
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from environment import test_engine, evidence_path
from sqlalchemy.orm import Session
from cfo.models import DocumentDerivation, DocumentIntake, Organization, OrganizationMembership, User, UserRole
from cfo.services.document_intake import DocumentIntakeService
from cfo.services.document_derivation import DocumentDerivationService

engine = test_engine()
with Session(engine) as db:
    org = Organization(name='SYNTHETIC PDF CONCURRENCY', settings={'synthetic': True})
    db.add(org); db.flush()
    actor = User(organization_id=org.id, email=f'{uuid4()}@example.invalid', full_name='Synthetic',
        password_hash='not-a-login-hash', role=UserRole.ADMIN, is_active=True)
    db.add(actor); db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=actor.id, role=UserRole.ADMIN, status='active'))
    db.commit(); org_id, actor_id = org.id, actor.id


def source(label):
    buffer = BytesIO(); document = canvas.Canvas(buffer)
    for i in range(2): document.drawString(50, 700, f'{label} {i}'); document.showPage()
    document.save()
    with Session(engine) as db:
        return DocumentIntakeService(db, org_id).receive(buffer.getvalue(), media_type='application/pdf', source='upload')['document_id']


def plan(doc, suffix=''):
    return {'parents': [{'document_id': doc, 'version': 1}], 'outputs': [
        {'filename': f'{page}{suffix}.pdf', 'pages': [{'document_id': doc, 'page': page}]} for page in (1, 2)],
        'reason': 'Synthetic source page boundaries were reviewed before the split', 'actor_id': actor_id}


def transform(payload):
    with Session(engine) as db:
        # Hold a cached membership as a long-lived request may do.
        membership = db.query(OrganizationMembership).filter_by(user_id=actor_id, organization_id=org_id).one()
        assert membership is not None
        return DocumentDerivationService(db, org_id).derive(**payload)


def race(same):
    doc = source('same' if same else 'conflict'); barrier = Barrier(2)
    def worker(suffix):
        barrier.wait(timeout=10)
        try: return transform(plan(doc, suffix))
        except RuntimeError: return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result(timeout=20) for f in [pool.submit(worker, ''), pool.submit(worker, '' if same else 'other')]]
    if same: assert results[0] == results[1]
    else: assert sum(result == 'conflict' for result in results) == 1
    with Session(engine) as db:
        row = db.get(DocumentIntake, doc); assert row.status == 'superseded' and row.version == 2
    return doc

race(True); race(False)
# Processing has already committed its claim: splitting must not retire this source.
doc = source('processing'); claimed, release = Event(), Event()
async def fake_extract(*args, **kwargs):
    claimed.set(); assert release.wait(10)
    return {'status': 'needs_review', 'message': 'Synthetic missing source evidence'}
def process():
    with Session(engine) as db:
        return asyncio.run(DocumentIntakeService(db, org_id).process(doc, expected_version=1))
with patch('cfo.services.chat_expense_intake._extract_receipt_bytes', fake_extract):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(process); assert claimed.wait(10)
        try:
            try: transform(plan(doc)); raise AssertionError('Processing source was transformed')
            except RuntimeError: pass
        finally: release.set()
        assert future.result(timeout=10)['status'] == 'needs_review'
# Revoke authority while native PDF generation is underway, before the final write.
import pypdfium2 as pdfium
original_save = pdfium.PdfDocument.save
entered, release = Event(), Event()
def delayed_save(self, *args, **kwargs):
    entered.set(); assert release.wait(10)
    return original_save(self, *args, **kwargs)
doc = source('revocation')
with patch.object(pdfium.PdfDocument, 'save', delayed_save):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(transform, plan(doc)); assert entered.wait(10)
        with Session(engine) as db:
            db.query(User).filter_by(id=actor_id).update({'is_active': False}); db.commit()
        release.set()
        try: future.result(timeout=15); raise AssertionError('Revoked actor transformed a source')
        except PermissionError: pass
with Session(engine) as db:
    row = db.get(DocumentIntake, doc); assert row.status == 'queued' and row.version == 1
    assert db.query(DocumentDerivation).filter_by(organization_id=org_id).count() == 2
    db.query(User).filter_by(id=actor_id).update({'is_active': True}); db.commit()
doc = source('membership revocation'); entered, release = Event(), Event()
with patch.object(pdfium.PdfDocument, 'save', delayed_save):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(transform, plan(doc)); assert entered.wait(10)
        with Session(engine) as db:
            db.query(OrganizationMembership).filter_by(user_id=actor_id, organization_id=org_id).update({'status': 'revoked'}); db.commit()
        release.set()
        try: future.result(timeout=15); raise AssertionError('Cached revoked membership transformed a source')
        except PermissionError: pass
with Session(engine) as db:
    row = db.get(DocumentIntake, doc); assert row.status == 'queued' and row.version == 1
result = {'status': 'passed', 'synthetic_only': True, 'provider_requests': 0,
    'checks': ['concurrent identical page recipes replay one durable outcome',
        'conflicting recipes preserve the first decision', 'processing claim excludes transformation',
        'authority revoked during PDF generation rolls back parent retirement and derived outputs',
        'cached membership cannot retain revoked authority during native PDF generation'],
    'official_books_verified': False}
evidence_path('2026-09-07-document-derivation-concurrency.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result)); engine.dispose()
