"""Upgrade existing receipt decisions without dropping evidence or faking head."""
import json

import sqlalchemy as sa

from cfo.services.schema_sync import compute_schema_drift, has_schema_drift
from test_fresh_database_migrations import _upgrade


def test_existing_allocation_survives_expansion_with_unknown_legacy_balance_effect(tmp_path):
    url = f"sqlite:///{tmp_path / 'existing.db'}"
    result = _upgrade(url, '62b80d39f715')
    assert result.returncode == 0, result.stderr
    engine = sa.create_engine(url)
    original = {'reason': 'Existing reviewed decision', 'payment_hash': 'original-proof'}
    # Foreign keys are intentionally disabled for this migration-only fixture;
    # the referenced business rows do not change in either migration.
    with engine.begin() as conn:
        conn.execute(sa.text('''INSERT INTO collection_payment_allocations
            (id,organization_id,request_id,invoice_id,payment_id,bank_transaction_id,
             amount,currency,document_external_id,decided_by_user_id,evidence,created_at)
            VALUES (1,1,1,1,1,1,400,'ILS','receipt-1',1,:evidence,'2026-09-06')'''),
            {'evidence': json.dumps(original)})
    result = _upgrade(url)
    assert result.returncode == 0, result.stderr
    with engine.connect() as conn:
        row = conn.execute(sa.text('SELECT * FROM collection_payment_allocations')).mappings().one()
    assert row['id'] == row['request_id'] == row['payment_id'] == row['bank_transaction_id'] == 1
    assert json.loads(row['evidence']) == original
    assert row['status'] == 'active' and row['idempotency_key'] is None
    assert row['amount'] == 400
    uniques = sa.inspect(engine).get_unique_constraints('collection_payment_allocations')
    assert not any(r['column_names'] in [['request_id'], ['payment_id'], ['bank_transaction_id']] for r in uniques)
    assert not has_schema_drift(compute_schema_drift(engine))


def test_obsolete_single_receipt_uniqueness_is_incompatible_drift(tmp_path):
    url = f"sqlite:///{tmp_path / 'obsolete.db'}"
    result = _upgrade(url)
    assert result.returncode == 0, result.stderr
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sa.text('CREATE UNIQUE INDEX old_one_receipt ON collection_payment_allocations(payment_id)'))
    drift = compute_schema_drift(engine)
    assert has_schema_drift(drift)
    assert 'collection_payment_allocations' in drift['incompatible_unique_constraints']
