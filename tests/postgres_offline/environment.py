"""Only explicitly selected synthetic local PostgreSQL databases are allowed."""
import os
from pathlib import Path
from urllib.parse import urlsplit
import sqlalchemy as sa


def test_engine():
    value = os.environ.get('REZEF_TEST_POSTGRES_URL', '')
    url = urlsplit(value)
    if (url.scheme != 'postgresql+psycopg' or url.hostname not in {'127.0.0.1', 'localhost'}
            or not url.path.startswith('/rezef_test_') or url.username != 'rezef_test'
            or url.password not in {None, 'synthetic_ci_only'} or url.query or url.fragment):
        raise ValueError('Set REZEF_TEST_POSTGRES_URL to an explicit loopback rezef_test_* database with the synthetic rezef_test user')
    engine = sa.create_engine(value)
    with engine.connect() as connection:
        rows = connection.execute(sa.text('SELECT settings FROM organizations')).scalars().all()
        if any(not isinstance(row, dict) or row.get('synthetic') is not True for row in rows):
            engine.dispose()
            raise ValueError('Existing organizations must all be explicitly synthetic')
    return engine


def evidence_path(name):
    root = Path(os.environ.get('REZEF_TEST_EVIDENCE_DIR', '/private/tmp/rezef-provider-concurrency'))
    root.mkdir(parents=True, exist_ok=True)
    return root / name
