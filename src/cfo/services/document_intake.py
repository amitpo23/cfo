"""Shared source intake for email, upload and chat. Reading never runs OCR or sync.

The queue is local and persistent. Extraction runs only on an explicit invocation,
under the existing vision enablement and cost gates. Interrupted claims stay visible
as processing; they are never silently replayed after a restart.
"""
import base64
import hashlib
import json
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from ..models import DocumentIntake, Expense, Note, Organization, User, UserRole

MAX_SOURCE_BYTES = 10 * 1024 * 1024
MEDIA_TYPES = {'application/pdf', 'image/png', 'image/jpeg', 'image/webp', 'image/tiff'}


class DocumentIntakeService:
    def __init__(self, db, organization_id):
        self.db, self.organization_id = db, organization_id

    def _query(self):
        return self.db.query(DocumentIntake).filter_by(organization_id=self.organization_id)

    def _row(self, document_id):
        row = self._query().filter_by(id=document_id).first()
        if row is None:
            raise ValueError('Document not found')
        return row

    def receive(self, content, *, media_type, source, filename='document', source_reference=None):
        if not content or len(content) > MAX_SOURCE_BYTES:
            raise ValueError('Source must contain 1 byte to 10 MiB')
        if media_type not in MEDIA_TYPES:
            raise ValueError('Unsupported document media type')
        digest = hashlib.sha256(content).hexdigest()
        observation = {'channel': source, 'reference': source_reference, 'filename': filename[:255]}
        row = self._query().filter_by(content_hash=digest).with_for_update().first()
        duplicate = row is not None
        if row is None:
            try:
                with self.db.begin_nested():
                    row = DocumentIntake(organization_id=self.organization_id, content_hash=digest,
                        content_base64=base64.b64encode(content).decode('ascii'), media_type=media_type,
                        filename=filename[:255], sources=[], status='queued', attempts=0, version=1)
                    self.db.add(row)
                    self.db.flush()
            except IntegrityError:
                row = self._query().filter_by(content_hash=digest).with_for_update().one()
                duplicate = True
        if observation not in row.sources:
            row.sources = [*row.sources, observation]
        self.db.commit()
        return {'status': 'duplicate' if duplicate else 'queued', 'document_id': row.id,
            'expense_id': row.expense_id}

    def detail(self, document_id):
        from .document_derivation import DocumentDerivationService
        from .expense_filing_workflow import ExpenseFilingWorkflow
        row = self._row(document_id)
        expense = self.db.query(Expense).filter_by(id=row.expense_id, organization_id=self.organization_id).first() if row.expense_id else None
        return {'id': row.id, 'organization_id': row.organization_id, 'filename': row.filename,
            'content_hash': row.content_hash, 'media_type': row.media_type, 'sources': row.sources,
            'lineage': DocumentDerivationService(self.db, self.organization_id).lineage(row),
            'status': row.status, 'attempts': row.attempts, 'version': row.version,
            'expense_id': expense.id if expense else None,
            'amount': str(expense.total) if expense and expense.total is not None else None,
            'accounting_status': expense.status if expense else 'not_created',
            'approval_status': 'source_reviewed' if (row.result or {}).get('source_review') else 'not_requested',
            'filing': ExpenseFilingWorkflow(self.db, self.organization_id).status(expense.id) if expense else None,
            'money_status': 'no_payment_evidence',
            'result': row.result, 'updated_at': row.updated_at.isoformat(),
            'official_books_verified': False}

    def review(self, document_id, *, expected_version, fields, reason, actor_id):
        """Review source fields only. Creates a draft, never approves accounting or payment."""
        from . import membership_service
        from .chat_expense_intake import _expense_from_extraction
        allowed = {'supplier_name', 'supplier_tax_id', 'expense_date', 'invoice_number',
            'amount_total', 'net_amount', 'vat_amount', 'currency', 'document_type'}
        if set(fields) - allowed or not 20 <= len(reason.strip()) <= 2000:
            raise ValueError('Provide supported source fields and a review reason of 20–2000 characters')
        try:
            self.db.expire_all()
            self.db.query(Organization).filter_by(id=self.organization_id).with_for_update().one()
            actor = self.db.query(User).filter_by(id=actor_id).first()
            if not actor or not actor.is_active or (actor.role != UserRole.SUPER_ADMIN and
                    membership_service.role_in(self.db, actor_id, self.organization_id) != UserRole.ADMIN):
                raise PermissionError('Source review requires an active organization administrator')
            row = self._row(document_id)
            if row.version != expected_version or row.expense_id or row.status in ('processing', 'created', 'duplicate', 'superseded'):
                raise RuntimeError('Document changed or already handled; reload before reviewing')
            before = row.result
            changed = self._query().filter_by(id=row.id, version=expected_version, status=row.status).update({
                DocumentIntake.version: DocumentIntake.version + 1}, synchronize_session=False)
            if changed != 1:
                raise RuntimeError('Document changed; reload before reviewing')
            self.db.refresh(row)
            result = _expense_from_extraction(self.db, self.organization_id,
                base64.b64decode(row.content_base64), fields, source=row.sources[0]['channel'],
                uploaded_by_user_id=actor_id, commit=False, human_reviewed=True)
            if result['status'] not in ('created', 'duplicate', 'non_accounting'):
                raise ValueError(result.get('message', 'Source evidence remains incomplete'))
            reviewed_at = datetime.utcnow().isoformat()
            note = Note(organization_id=self.organization_id, entity_type='document_intake',
                entity_id=row.id, created_by=actor_id, text=json.dumps({'kind': 'source_review',
                    'reason': reason.strip(), 'before': before, 'fields': fields,
                    'content_hash': row.content_hash, 'reviewed_at': reviewed_at}, ensure_ascii=False))
            self.db.add(note); self.db.flush()
            row.result = dict(result, source_review={'actor_id': actor_id, 'reason': reason.strip(),
                'reviewed_at': reviewed_at, 'note_id': note.id})
            row.status, row.expense_id = result['status'], result.get('expense_id')
            self.db.commit()
            return dict(result, document_id=document_id)
        except Exception:
            self.db.rollback()
            raise

    def list_documents(self, *, limit=100, offset=0):
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError('Invalid pagination')
        rows = self._query().order_by(DocumentIntake.id.desc()).offset(offset).limit(limit).all()
        return {'documents': [self.detail(row.id) for row in rows], 'total': self._query().count(),
            'sync_triggered': False}

    def source(self, document_id):
        row = self._row(document_id)
        try:
            content = base64.b64decode(row.content_base64, validate=True)
        except ValueError as exc:
            raise RuntimeError('Preserved source integrity requires review') from exc
        if hashlib.sha256(content).hexdigest() != row.content_hash:
            raise RuntimeError('Preserved source integrity requires review')
        return content, row.media_type

    def preview(self, document_id, *, page_number=1):
        """Render an explicit source page locally; never extract, sync or mutate."""
        import math
        from contextlib import ExitStack, closing
        from io import BytesIO
        from PIL import Image
        from .pdf_runtime import PDFIUM_LOCK
        row = self._row(document_id)
        content, _ = self.source(document_id)
        try:
            with ExitStack() as stack:
                if row.media_type == 'application/pdf':
                    import pypdfium2 as pdfium
                    stack.enter_context(PDFIUM_LOCK)
                    document = stack.enter_context(closing(pdfium.PdfDocument(content)))
                    count = len(document)
                    if not 1 <= page_number <= count <= 100:
                        raise ValueError('Preview requires a valid page within a document of at most 100 pages')
                    page = stack.enter_context(closing(document[page_number - 1]))
                    width, height = page.get_size()
                    if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                        raise ValueError('Source page dimensions are invalid')
                    bitmap = stack.enter_context(closing(page.render(scale=min(2.0, 1200 / max(width, height)))))
                    rendered = stack.enter_context(closing(bitmap.to_pil()))
                else:
                    source = stack.enter_context(Image.open(BytesIO(content)))
                    count = getattr(source, 'n_frames', 1)
                    if not 1 <= page_number <= count <= 100:
                        raise ValueError('Preview requires a valid page within a document of at most 100 pages')
                    source.seek(page_number - 1)
                    if source.width * source.height > 40_000_000:
                        raise ValueError('Source image exceeds the local preview size limit')
                    rendered = stack.enter_context(source.convert('RGB'))
                    rendered.thumbnail((1200, 1200))
                output = BytesIO()
                rendered.save(output, format='PNG')
                return {'page': page_number, 'page_count': count, 'media_type': 'image/png',
                    'content_base64': base64.b64encode(output.getvalue()).decode('ascii'),
                    'source_sha256': row.content_hash, 'preview_only': True}
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('Source cannot be previewed; retain the original for review') from exc

    async def process(self, document_id, *, retry=False, expected_version=None,
                      uploaded_by_user_id=None, session_id=None, reauthorize=None):
        from .chat_expense_intake import _extract_receipt_bytes
        row = self._row(document_id)
        if expected_version is not None and expected_version != row.version:
            raise ValueError('Document changed; reload before acting')
        if row.status in ('created', 'duplicate'):
            return dict(row.result or {}, status='duplicate', document_id=row.id, expense_id=row.expense_id)
        eligible = ('error', 'unreadable', 'disabled', 'limit_reached') if retry else ('queued',)
        if row.status not in eligible or row.attempts >= 3:
            raise ValueError('Document is not eligible for processing; explicit review is required')
        version = row.version
        changed = self._query().filter_by(id=row.id, version=version, status=row.status).update({
            DocumentIntake.status: 'processing', DocumentIntake.attempts: DocumentIntake.attempts + 1,
            DocumentIntake.version: DocumentIntake.version + 1, DocumentIntake.updated_at: datetime.utcnow()}, synchronize_session=False)
        self.db.commit()
        if changed != 1:
            raise ValueError('Document is already claimed; reload')
        row = self._row(document_id)
        try:
            result = await _extract_receipt_bytes(self.db, self.organization_id,
                base64.b64decode(row.content_base64), media_type=row.media_type,
                source=row.sources[0]['channel'], uploaded_by_user_id=uploaded_by_user_id,
                session_id=session_id, commit=False, reauthorize=reauthorize)
            row.status = result['status']
            row.result = result
            row.expense_id = result.get('expense_id')
            row.version += 1
            self.db.commit()
        except Exception:
            self.db.rollback()
            row = self._row(document_id)
            row.status = 'error'
            row.result = {'status': 'error', 'message': 'Processing failed; review permissions and source before retry'}
            row.version += 1
            self.db.commit()
            raise
        return dict(result, document_id=document_id)
