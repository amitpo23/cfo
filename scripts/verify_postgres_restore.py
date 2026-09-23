#!/usr/bin/env python3
"""Synthetic local PostgreSQL migration/encrypted-restore drill. Never accepts remote DSNs.

Create two empty databases named rezef_test_* before running. No database is
created, dropped, truncated or reused by this script. Secrets for a real backup
and production restore remain governed by docs/RESTORE_RUNBOOK.md.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def local_test_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in {'postgresql', 'postgresql+psycopg'}
            or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}
            or not parsed.path.startswith('/rezef_test_') or parsed.query or parsed.fragment):
        raise ValueError('Only explicit loopback PostgreSQL databases named rezef_test_* are allowed')
    return value.replace('postgresql://', 'postgresql+psycopg://', 1)


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, text=True, check=False, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{Path(command[0]).name} failed: {result.stderr[-4000:]}')
    return result.stdout


def fingerprint(engine):
    import sqlalchemy as sa
    result = {}
    with engine.connect() as connection:
        for table in sorted(sa.inspect(engine).get_table_names()):
            quoted = engine.dialect.identifier_preparer.quote(table)
            rows = connection.execute(sa.text(f'SELECT * FROM {quoted}')).mappings().all()
            serialized = sorted(json.dumps(dict(row), sort_keys=True, default=str) for row in rows)
            result[table] = {'rows':len(rows), 'sha256':hashlib.sha256('\n'.join(serialized).encode()).hexdigest()}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-url', required=True)
    parser.add_argument('--restore-url', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    source, target = local_test_url(args.source_url), local_test_url(args.restore_url)
    if source == target:
        raise ValueError('Source and restore databases must differ')
    import sqlalchemy as sa
    from sqlalchemy.orm import Session
    from datetime import date
    from cfo.models import Organization, Account, AccountType, BankTransaction, BillingCheckout
    from cfo.services.schema_sync import compute_schema_drift, has_schema_drift
    for executable in ('pg_dump', 'psql', 'openssl'):
        if not shutil.which(executable):
            raise RuntimeError(f'{executable} must be on PATH')
    engines = [sa.create_engine(source), sa.create_engine(target)]
    if any(sa.inspect(engine).get_table_names() for engine in engines):
        raise ValueError('Both databases must be empty; existing data is never modified')
    started = time.monotonic()
    migration_env = {**os.environ, 'DATABASE_URL':source}
    run([sys.executable,'-m','alembic','upgrade','head'], cwd=ROOT, env=migration_env)
    assert not has_schema_drift(compute_schema_drift(engines[0])), 'Fresh PostgreSQL migration has drift'
    with Session(engines[0]) as db:
        org = Organization(name='SYNTHETIC RESTORE FIXTURE', settings={'synthetic':True})
        db.add(org); db.flush()
        db.add(Account(organization_id=org.id, name='Synthetic bank', account_type=AccountType.BANK, balance=1250))
        db.add(BankTransaction(organization_id=org.id, transaction_date=date(2026,1,1), amount=1250, description='Synthetic receipt'))
        db.add(BillingCheckout(session_id='mock_restore_fixture', selected_plan='office', payment_status='pending', organization_id=org.id))
        db.commit()
    before = fingerprint(engines[0])
    with tempfile.TemporaryDirectory(prefix='rezef-synthetic-restore-') as temporary:
        root = Path(temporary)
        dump, encrypted, restored = root/'source.sql', root/'backup.enc', root/'restored.sql'
        run(['pg_dump', source.replace('postgresql+psycopg://','postgresql://'), '--no-owner','--no-privileges','--file',str(dump)])
        crypto_env = {**os.environ,'REZEF_DRILL_PASSPHRASE':secrets.token_urlsafe(40)}
        run(['openssl','enc','-aes-256-cbc','-pbkdf2','-salt','-in',str(dump),'-out',str(encrypted),'-pass','env:REZEF_DRILL_PASSPHRASE'],env=crypto_env)
        run(['openssl','enc','-d','-aes-256-cbc','-pbkdf2','-in',str(encrypted),'-out',str(restored),'-pass','env:REZEF_DRILL_PASSPHRASE'],env=crypto_env)
        assert hashlib.sha256(dump.read_bytes()).digest() == hashlib.sha256(restored.read_bytes()).digest()
        run(['psql',target.replace('postgresql+psycopg://','postgresql://'),'-v','ON_ERROR_STOP=1','-f',str(restored)])
    after = fingerprint(engines[1])
    assert before == after, 'Restored rows differ from source'
    assert not has_schema_drift(compute_schema_drift(engines[1])), 'Restored schema has drift'
    from sqlalchemy.exc import IntegrityError
    with Session(engines[1]) as db:
        db.add(BillingCheckout(session_id='mock_bad_fk', selected_plan='office', payment_status='pending', organization_id=999999999))
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
        else:
            db.rollback()
            raise AssertionError('PostgreSQL did not enforce organization FK')
    with Session(engines[1]) as db:
        db.add(BillingCheckout(session_id='mock_restore_fixture', selected_plan='office', payment_status='pending'))
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
        else:
            db.rollback()
            raise AssertionError('Checkout uniqueness was not enforced')
    result = {'status':'passed','synthetic_only':True,'elapsed_seconds':round(time.monotonic()-started,2),
              'tables':len(after),'row_count':sum(t['rows'] for t in after.values()),
              'checks':['fresh migrations','schema parity','encrypted round trip','all-table row hashes','foreign keys','checkout uniqueness'],
              'production_backup_verified':False}
    Path(args.output).write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    for engine in engines:
        engine.dispose()


if __name__ == '__main__':
    main()
