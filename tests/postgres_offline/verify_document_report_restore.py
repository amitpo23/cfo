"""Restore populated synthetic intake/report evidence into an explicitly empty local DB."""
import base64
import hashlib
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from environment import test_engine, evidence_path
from verify_postgres_restore import local_test_url, fingerprint, run
import sqlalchemy as sa
from sqlalchemy.orm import Session
from cfo.models import DocumentDerivation, DocumentIntake, ReportRecord, Expense, IrreversibleActionRequest
from cfo.services.schema_sync import compute_schema_drift, has_schema_drift

source = test_engine()
target_url = local_test_url(os.environ['REZEF_TEST_POSTGRES_RESTORE_URL'])
target = sa.create_engine(target_url)
assert not sa.inspect(target).get_table_names(), 'Restore target must be empty'
with Session(source) as db:
    assert db.query(DocumentIntake).count() > 0
    assert db.query(ReportRecord).filter_by(kind='file').count() > 0
before = fingerprint(source)
with tempfile.TemporaryDirectory(prefix='rezef-populated-restore-') as temporary:
    folder = Path(temporary)
    original, encrypted, decoded = folder / 'source.sql', folder / 'encrypted.bin', folder / 'decoded.sql'
    source_url = source.url.render_as_string(hide_password=False).replace('postgresql+psycopg://', 'postgresql://')
    run(['pg_dump', source_url, '--no-owner', '--no-privileges', '--file', str(original)])
    crypto = {**os.environ, 'REZEF_SYNTHETIC_RESTORE_KEY': secrets.token_urlsafe(40)}
    run(['openssl', 'enc', '-aes-256-cbc', '-pbkdf2', '-salt', '-in', str(original), '-out', str(encrypted),
         '-pass', 'env:REZEF_SYNTHETIC_RESTORE_KEY'], env=crypto)
    run(['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-in', str(encrypted), '-out', str(decoded),
         '-pass', 'env:REZEF_SYNTHETIC_RESTORE_KEY'], env=crypto)
    assert original.read_bytes() == decoded.read_bytes()
    run(['psql', target_url.replace('postgresql+psycopg://', 'postgresql://'), '-v', 'ON_ERROR_STOP=1', '-f', str(decoded)])
assert before == fingerprint(target)
assert not has_schema_drift(compute_schema_drift(target))
with Session(target) as db:
    for row in db.query(DocumentIntake):
        assert hashlib.sha256(base64.b64decode(row.content_base64)).hexdigest() == row.content_hash
        assert row.sources
    for row in db.query(ReportRecord).filter_by(kind='file'):
        assert hashlib.sha256(base64.b64decode(row.payload['content_base64'])).hexdigest() == row.payload['sha256']
    for recipe in db.query(DocumentDerivation):
        for doc, digest in recipe.recipe['source_hashes'].items():
            parent = db.query(DocumentIntake).filter_by(id=int(doc), organization_id=recipe.organization_id).one()
            assert parent.content_hash == digest and parent.status == 'superseded'
        for output in recipe.outputs:
            child = db.query(DocumentIntake).filter_by(id=output['document_id'], organization_id=recipe.organization_id).one()
            assert child.content_hash == output['content_hash']
    filing_acknowledgements = 0
    for action in db.query(IrreversibleActionRequest).filter_by(action_type='sumit_writeback'):
        payload, result = action.payload or {}, action.execution_result or {}
        if payload.get('operation') != 'expenses.add_source_expense_draft' or not action.provider_reference:
            continue
        original = db.query(DocumentIntake).filter_by(id=payload['document_id'], organization_id=action.organization_id).one()
        expense = db.query(Expense).filter_by(id=payload['expense_id'], organization_id=action.organization_id).one()
        assert original.content_hash == payload['source_sha256']
        assert expense.sumit_expense_id == action.provider_reference == result['provider_document_id']
        assert payload['provider_target'] == result['provider_target']
        assert result['official_books_verified'] is False
        filing_acknowledgements += 1
result = {'status': 'passed', 'synthetic_only': True, 'tables': len(before),
    'intake_rows': before['document_intakes']['rows'], 'report_rows': before['report_records']['rows'],
    'derivation_rows': before['document_derivations']['rows'], 'filing_acknowledgements': filing_acknowledgements,
    'checks': ['populated encrypted restore', 'all-table row hash parity', 'source bytes and provenance',
        'saved report file integrity', 'source-bound filing and provider destination identity', 'derived pages and retired parent identity', 'schema parity'], 'production_backup_verified': False}
evidence_path('2026-09-07-document-report-populated-restore.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
source.dispose(); target.dispose()
