"""Shared source intake for email, upload and chat. Reading never runs OCR or sync.

The queue is local and persistent. Extraction runs only on an explicit invocation,
under the existing vision enablement and cost gates. Interrupted claims stay visible
as processing; they are never silently replayed after a restart.
"""
import base64
import hashlib
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from ..models import DocumentIntake, Expense

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
        row = self._row(document_id)
        expense = self.db.query(Expense).filter_by(id=row.expense_id, organization_id=self.organization_id).first() if row.expense_id else None
        return {'id': row.id, 'organization_id': row.organization_id, 'filename': row.filename,
            'content_hash': row.content_hash, 'media_type': row.media_type, 'sources': row.sources,
            'status': row.status, 'attempts': row.attempts, 'version': row.version,
            'expense_id': expense.id if expense else None,
            'amount': str(expense.total) if expense and expense.total is not None else None,
            'accounting_status': expense.status if expense else 'not_created',
            'approval_status': 'not_requested', 'money_status': 'no_payment_evidence',
            'result': row.result, 'updated_at': row.updated_at.isoformat(),
            'official_books_verified': False}

    def list_documents(self, *, limit=100, offset=0):
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError('Invalid pagination')
        rows = self._query().order_by(DocumentIntake.id.desc()).offset(offset).limit(limit).all()
        return {'documents': [self.detail(row.id) for row in rows], 'total': self._query().count(),
            'sync_triggered': False}

    def source(self, document_id):
        row = self._row(document_id)
        return base64.b64decode(row.content_base64), row.media_type

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
