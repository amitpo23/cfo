"""Explicit PDF splitting/merging. Local transformations never approve accounting.

Every parent page must occur exactly once. Parent/child creation, page lineage and
parent retirement commit together. A retired parent remains readable, but cannot
be extracted/reviewed separately. No file is deleted, and no OCR/network is invoked.
"""
import base64
import hashlib
import json
from contextlib import ExitStack, closing
from io import BytesIO

import pypdfium2 as pdfium

from ..models import DocumentDerivation, DocumentIntake, Organization, User, UserRole
from .document_intake import MAX_SOURCE_BYTES
from . import membership_service
from .pdf_runtime import PDFIUM_LOCK

ELIGIBLE = {'queued', 'needs_review', 'unreadable', 'error', 'disabled', 'limit_reached', 'non_accounting'}


class DocumentDerivationService:
    def __init__(self, db, organization_id):
        self.db, self.organization_id = db, organization_id

    def derive(self, *, parents, outputs, reason, actor_id):
        if not 20 <= len(reason.strip()) <= 2000 or not 1 <= len(parents) <= 10 or not 1 <= len(outputs) <= 100:
            raise ValueError('Provide 1–10 PDF sources, 1–100 outputs and a reason of 20–2000 characters')
        if len(parents) == len(outputs) == 1:
            raise ValueError('Choose a split or merge with at least two sources or outputs')
        ids = [item['document_id'] for item in parents]
        if len(set(ids)) != len(ids):
            raise ValueError('Each parent must be selected once')
        recipe = {'parents': sorted(parents, key=lambda item: item['document_id']), 'outputs': outputs}
        recipe_hash = hashlib.sha256(json.dumps(recipe, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        try:
            self.db.expire_all()
            self.db.query(Organization).filter_by(id=self.organization_id).with_for_update().one()
            self._authorize(actor_id)
            prior = self.db.query(DocumentDerivation).filter_by(organization_id=self.organization_id, recipe_hash=recipe_hash).first()
            if prior:
                for doc, digest in prior.recipe['source_hashes'].items():
                    source = self.db.query(DocumentIntake).filter_by(id=int(doc), organization_id=self.organization_id).first()
                    if not source or source.content_hash != digest or hashlib.sha256(base64.b64decode(source.content_base64)).hexdigest() != digest:
                        raise RuntimeError('Preserved source differs from the approved page recipe; review required')
                return self._result(prior)
            rows = self.db.query(DocumentIntake).filter(DocumentIntake.organization_id == self.organization_id,
                DocumentIntake.id.in_(ids)).order_by(DocumentIntake.id).with_for_update().all()
            if len(rows) != len(ids):
                raise ValueError('Document not found')
            sources = {row.id: row for row in rows}
            for parent in parents:
                row = sources[parent['document_id']]
                if row.version != parent['version'] or row.status not in ELIGIBLE or row.expense_id:
                    raise RuntimeError('Source changed or already handled; reload before splitting or merging')
                if row.media_type != 'application/pdf':
                    raise ValueError('Only PDF sources support page transformations')
                if hashlib.sha256(base64.b64decode(row.content_base64)).hexdigest() != row.content_hash:
                    raise RuntimeError('Stored source integrity changed; review required')
            if sum(len(row.content_base64) for row in rows) > 70_000_000:
                raise ValueError('Combined source size exceeds the local transformation limit')
            binaries = []
            with PDFIUM_LOCK, ExitStack() as stack:
                loaded = {}
                for row in rows:
                    try:
                        loaded[row.id] = stack.enter_context(closing(pdfium.PdfDocument(base64.b64decode(row.content_base64))))
                    except Exception as exc:
                        raise ValueError('PDF cannot be read; inspect the original source') from exc
                expected = {(doc, page) for doc, pdf in loaded.items() for page in range(1, len(pdf) + 1)}
                selected = [(page['document_id'], page['page']) for output in outputs for page in output['pages']]
                if not expected or len(expected) > 100 or len(selected) != len(expected) or set(selected) != expected:
                    raise ValueError('Each source page must appear exactly once, without omission or duplication; maximum 100 pages')
                for output in outputs:
                    if not output['pages'] or not output['filename'].strip() or len(output['filename']) > 255:
                        raise ValueError('Each output requires a filename and at least one page')
                    with closing(pdfium.PdfDocument.new()) as pdf:
                        for page in output['pages']:
                            pdf.import_pages(loaded[page['document_id']], pages=[page['page'] - 1])
                        buffer = BytesIO(); pdf.save(buffer); content = buffer.getvalue()
                    if not content or len(content) > MAX_SOURCE_BYTES:
                        raise ValueError('An output exceeds the 10 MiB document limit')
                    binaries.append(content)
            # Serialize with processing claims as well as other transformations.
            # The CAS covers SQLite, where SELECT FOR UPDATE is not available.
            for parent in parents:
                row = sources[parent['document_id']]
                changed = self.db.query(DocumentIntake).filter_by(id=row.id, organization_id=self.organization_id,
                    version=parent['version'], status=row.status, expense_id=None).update({
                        DocumentIntake.status: 'superseded', DocumentIntake.version: DocumentIntake.version + 1}, synchronize_session=False)
                if changed != 1:
                    raise RuntimeError('Source was claimed by another worker; reload')
            self._authorize(actor_id)
            record = DocumentDerivation(organization_id=self.organization_id, recipe_hash=recipe_hash,
                recipe=dict(recipe, source_hashes={str(row.id): row.content_hash for row in rows}),
                outputs=[], created_by=actor_id, reason=reason.strip())
            self.db.add(record); self.db.flush()
            results = []
            for output, content in zip(outputs, binaries):
                digest = hashlib.sha256(content).hexdigest()
                if self.db.query(DocumentIntake).filter_by(organization_id=self.organization_id, content_hash=digest).first():
                    raise ValueError('An output already exists; review its source identity before transforming')
                child = DocumentIntake(organization_id=self.organization_id, content_hash=digest,
                    content_base64=base64.b64encode(content).decode(), media_type='application/pdf',
                    filename=output['filename'], sources=[{'channel': 'derivation', 'reference': str(record.id),
                        'filename': output['filename']}], status='queued', attempts=0, version=1)
                self.db.add(child); self.db.flush()
                results.append({'document_id': child.id, 'filename': child.filename, 'content_hash': digest, 'pages': output['pages']})
            record.outputs = results
            self.db.commit()
            return self._result(record)
        except Exception:
            self.db.rollback()
            raise

    def _authorize(self, actor_id):
        # A request may already hold a membership object. Re-querying alone can
        # return that stale ORM identity after another session revokes it.
        self.db.expire_all()
        actor = self.db.query(User).filter_by(id=actor_id).populate_existing().first()
        if not actor or not actor.is_active or (actor.role != UserRole.SUPER_ADMIN and
                membership_service.role_in(self.db, actor_id, self.organization_id) != UserRole.ADMIN):
            raise PermissionError('Document transformation requires an active organization administrator')

    @staticmethod
    def _result(record):
        return {'derivation_id': record.id, 'outputs': record.outputs,
            'official_books_verified': False, 'status': 'derived'}

    def lineage(self, row):
        references = [source.get('reference') for source in row.sources if source.get('channel') == 'derivation']
        if not references:
            return None
        record = self.db.query(DocumentDerivation).filter(DocumentDerivation.organization_id == self.organization_id,
            DocumentDerivation.id.in_([int(ref) for ref in references if str(ref).isdigit()])).first()
        if not record:
            return None
        output = next((item for item in record.outputs if item['document_id'] == row.id), None)
        if not output:
            return None
        parent_ids = list(dict.fromkeys(page['document_id'] for page in output['pages']))
        return {'derivation_id': record.id, 'reason': record.reason, 'created_by': record.created_by,
            'page_map': output['pages'], 'parents': [{'document_id': doc,
                'pages': [page['page'] for page in output['pages'] if page['document_id'] == doc],
                'content_hash': record.recipe['source_hashes'][str(doc)]} for doc in parent_ids]}
