"""Offline source completeness and atomic pagination regression tests."""
import asyncio
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import Invoice, SyncCheckpoint
from cfo.services.connector_base import FetchResult, NormalizedInvoice
from cfo.services.open_finance_connector import OpenFinanceConnector
from cfo.services.sync_engine import SyncEngine
from test_sync_call_protection import _NoOpConnector


@pytest.mark.parametrize('missing', ['id', 'amount', 'currency', 'date'])
def test_missing_transaction_evidence_is_not_fabricated(missing):
    raw = {'id': 'tx-1', 'amount': '12', 'currency': 'ILS', 'date': '2026-09-06'}
    del raw[missing]
    raw['createdAt'] = '2026-09-06'
    with pytest.raises(ValueError, match='transaction'):
        OpenFinanceConnector('fake', 'fake', 'fake')._normalize_transaction(raw)


@pytest.mark.parametrize('amount', ['nonsense', 'NaN', 'Infinity', '-Infinity', {}, True])
def test_invalid_amount_does_not_become_zero_or_nonfinite(amount):
    with pytest.raises(ValueError, match='amount'):
        OpenFinanceConnector('fake', 'fake', 'fake')._normalize_transaction(
            {'id': 'tx-1', 'amount': amount, 'currency': 'ILS', 'date': '2026-09-06'})


def test_explicit_zero_and_signed_amount_are_preserved():
    connector = OpenFinanceConnector('fake', 'fake', 'fake')
    for amount in ['0', '-12.34']:
        assert connector._normalize_transaction({'id': 'tx', 'amount': amount,
            'currency': 'USD', 'date': '2026-09-06'}).amount == Decimal(amount)


@pytest.mark.parametrize('cursor', [None, 'repeated'])
def test_invalid_pagination_stops_before_replaying_or_committing_page(fresh_org, cursor):
    class Connector(_NoOpConnector):
        calls = 0
        async def fetch_invoices(self, **kwargs):
            self.calls += 1
            return FetchResult(items=[NormalizedInvoice(external_id='bad-page')],
                has_more=True, next_cursor=cursor)
    org = fresh_org()['org_id']
    with SessionLocal() as db:
        db.add(SyncCheckpoint(organization_id=org, source='sumit', entity_type='invoices', cursor=cursor))
        db.commit()
        connector = Connector()
        with pytest.raises(ValueError, match='cursor'):
            asyncio.run(SyncEngine(db, connector, org, 'sumit')._sync_entity_type('invoices'))
        assert connector.calls == 1
        assert db.query(Invoice).filter_by(organization_id=org).count() == 0
        assert db.query(SyncCheckpoint).filter_by(organization_id=org, source='sumit', entity_type='invoices').one().last_success_at is None


def test_conflict_rolls_back_entire_page_and_preserves_previous_page(fresh_org):
    class Connector(_NoOpConnector):
        async def fetch_invoices(self, cursor=None, **kwargs):
            if cursor is None:
                return FetchResult(items=[NormalizedInvoice(external_id='committed')], has_more=True, next_cursor='2')
            return FetchResult(items=[NormalizedInvoice(external_id='must-rollback'), NormalizedInvoice(external_id='conflict')])
    org = fresh_org()['org_id']
    with SessionLocal() as db:
        engine = SyncEngine(db, Connector(), org, 'sumit')
        original = engine._upsert_invoice
        def upsert(item):
            if item.external_id == 'conflict': raise ValueError('reviewed source conflict')
            return original(item)
        engine._upsert_invoice = upsert
        with pytest.raises(ValueError, match='conflict'):
            asyncio.run(engine._sync_entity_type('invoices'))
        assert [row.external_id for row in db.query(Invoice).filter_by(organization_id=org)] == ['committed']
        assert db.query(SyncCheckpoint).filter_by(organization_id=org, source='sumit', entity_type='invoices').one().cursor == '2'
