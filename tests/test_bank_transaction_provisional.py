"""Open Finance bank data is provisional/unverified until the consent journey +
OPEN_FINANCE_USER_ID are fully live (documented principle in
docs/PRODUCT_AUDIT_AND_ROADMAP.md's preamble) -- but nothing in the model or
sync path actually marked a row as such, so the UI had no way to show a
"provisional" label even once it existed. This closes that specific,
well-scoped gap (not the whole Open Finance readiness question)."""
from datetime import date
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import BankTransaction
from cfo.services.connector_base import NormalizedBankTransaction
from cfo.services.sync_engine import SyncEngine


def _upsert(org_id, source, external_id="of-tx-1"):
    db = SessionLocal()
    try:
        engine = SyncEngine(db, connector=None, organization_id=org_id, source=source)
        item = NormalizedBankTransaction(
            external_id=external_id,
            transaction_date=date(2026, 6, 1),
            description="test",
            amount=Decimal("-100"),
        )
        engine._upsert_bank_transaction(item)
        db.commit()
    finally:
        db.close()


def test_open_finance_transactions_are_marked_provisional(fresh_org):
    org_id = fresh_org()["org_id"]
    _upsert(org_id, source="open_finance")

    db = SessionLocal()
    try:
        row = db.query(BankTransaction).filter(
            BankTransaction.organization_id == org_id, BankTransaction.source == "open_finance",
        ).first()
    finally:
        db.close()

    assert row is not None
    assert row.is_provisional is True


def test_sumit_transactions_are_not_provisional(fresh_org):
    org_id = fresh_org()["org_id"]
    _upsert(org_id, source="sumit")

    db = SessionLocal()
    try:
        row = db.query(BankTransaction).filter(
            BankTransaction.organization_id == org_id, BankTransaction.source == "sumit",
        ).first()
    finally:
        db.close()

    assert row is not None
    assert row.is_provisional is False
