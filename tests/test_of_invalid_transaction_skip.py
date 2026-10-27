"""One Open Finance transaction with an unreadable amount must not stop the rest.

Production, 27/10/2026: a manual refresh for org 2 updated the accounts, and
then `bank_transactions` failed whole on "Open Finance transaction amount is
missing or invalid" -- no bank row after 13/10 reached Rezef. The connector now
keeps the readable rows and reports each rejected one with its id, the reason,
and the key names of its amount (never a value). The entity checkpoint does not
advance past a run with rejections, so the rows come back on the next refresh
once the shape is read. No provider calls.
"""
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from cfo.database import SessionLocal, init_db
from cfo.models import Organization, SyncCheckpoint
from cfo.services.connector_base import FetchResult, NormalizedBankTransaction
from cfo.services.open_finance_connector import OpenFinanceConnector
from cfo.services.sync_engine import SyncEngine


@pytest.fixture(autouse=True, scope="module")
def _ensure_schema():
    init_db()


class _Client:
    def __init__(self, items):
        self.items = items

    async def list_transactions(self, **_kw):
        return {"items": self.items, "nextPage": None}

    async def close(self):
        pass


def _valid(tx_id, amount):
    return {"id": tx_id, "accountId": "acc", "date": "2026-10-20",
            "amount": {"chargedAmount": {"amount": amount, "currency": "ILS"}}}


def test_the_readable_rows_come_through_and_the_unreadable_one_is_reported():
    conn = OpenFinanceConnector("cid", "secret", "user-1")
    conn.client = _Client([
        _valid("tx-1", -120.5),
        {"id": "tx-2", "accountId": "acc", "date": "2026-10-21",
         "amount": {"chargedAmount": {"currency": "ILS"}, "originalAmount": {"currency": "ILS"}}},
        _valid("tx-3", 300),
    ])

    result = asyncio.run(conn.fetch_bank_transactions())

    assert [t.external_id for t in result.items] == ["open_finance:tx-1", "open_finance:tx-3"]
    assert len(result.rejected) == 1
    rejected = result.rejected[0]
    assert rejected["id"] == "tx-2"
    assert "amount" in rejected["reason"]
    assert rejected["amount_shape"] == {"chargedAmount": ["currency"], "originalAmount": ["currency"]}


def test_a_rejection_report_never_carries_a_value():
    conn = OpenFinanceConnector("cid", "secret", "user-1")
    conn.client = _Client([{"id": "tx-9", "date": "2026-10-21", "amount": "not-a-number-12345"}])

    rejected = asyncio.run(conn.fetch_bank_transactions()).rejected[0]

    assert "12345" not in repr(rejected)
    assert rejected["amount_shape"] == "str"


class _Connector:
    """Every fetch is empty except bank transactions: one row and one rejection."""

    def __getattr__(self, name):
        if name.startswith("fetch_"):
            async def empty(updated_since=None, cursor=None, page_size=100):
                return FetchResult(items=[], has_more=False)
            return empty
        raise AttributeError(name)

    async def fetch_bank_transactions(self, updated_since=None, cursor=None, page_size=100):
        row = NormalizedBankTransaction(
            external_id="open_finance:ok-1", account_external_id=None,
            transaction_date=datetime(2026, 10, 20).date(), description="העברה",
            amount=Decimal("-50"), currency="ILS", raw_data={},
        )
        return FetchResult(items=[row], has_more=False,
                           rejected=[{"id": "bad-1", "reason": "amount", "amount_shape": "dict"}])


def test_the_engine_counts_rejections_and_keeps_the_checkpoint_where_it_was():
    db = SessionLocal()
    try:
        org = Organization(name="Rejected Rows Co", is_active=True)
        db.add(org)
        db.commit()
        before = datetime.utcnow() - timedelta(days=5)
        db.add(SyncCheckpoint(organization_id=org.id, source="open_finance",
                              entity_type="bank_transactions", last_success_at=before))
        db.commit()

        run = asyncio.run(SyncEngine(db, _Connector(), org.id, "open_finance")
                          .run_full_sync(entity_types=["bank_transactions"]))

        counts = run.counts["bank_transactions"]
        assert counts["created"] == 1
        assert counts["rejected"] == 1
        assert counts["rejected_sample"] == [{"id": "bad-1", "reason": "amount", "amount_shape": "dict"}]
        cp = db.query(SyncCheckpoint).filter_by(
            organization_id=org.id, source="open_finance", entity_type="bank_transactions",
        ).one()
        assert cp.last_success_at == before
    finally:
        db.close()
