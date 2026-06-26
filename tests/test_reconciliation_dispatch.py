"""Tests for the Open Finance -> SUMIT reconciliation dispatch boundary."""
from datetime import date

from cfo.database import SessionLocal
from cfo.models import BankTransaction, Invoice, InvoiceStatus
from cfo.services import reconciliation_dispatch


def test_sumit_dispatch_marks_unsupported_when_connector_has_no_writeback(client, owner):
    org_id = owner["user"]["organization_id"]
    db = SessionLocal()
    try:
        inv = Invoice(
            organization_id=org_id,
            external_id="SUMIT-INV-1",
            source="sumit",
            issue_date=date(2026, 6, 4),
            status=InvoiceStatus.SENT,
            total=1170,
            balance=1170,
        )
        tx = BankTransaction(
            organization_id=org_id,
            external_id="OF-TXN-1",
            source="open_finance",
            transaction_date=date(2026, 6, 5),
            description="תשלום מאת לקוח",
            amount=1170,
            currency="ILS",
        )
        db.add_all([inv, tx])
        db.commit()

        result = client.post(
            "/api/open-finance/reconcile/sumit-dispatch",
            headers=owner["headers"],
        )

        assert result.status_code == 200, result.text
        body = result.json()
        assert body["local_reconciliation"]["matched_count"] >= 1
        assert body["unsupported"] >= 1

        db.refresh(tx)
        assert tx.is_reconciled is True
        assert tx.reconciliation_dispatch_status == "unsupported"
        assert "write-back" in tx.reconciliation_error
    finally:
        db.close()


def test_dispatch_service_dry_run_does_not_mutate_status(client, owner):
    org_id = owner["user"]["organization_id"]
    db = SessionLocal()
    try:
        inv = Invoice(
            organization_id=org_id,
            external_id="SUMIT-INV-DRY",
            source="sumit",
            issue_date=date(2026, 7, 4),
            status=InvoiceStatus.SENT,
            total=900,
            balance=900,
        )
        tx = BankTransaction(
            organization_id=org_id,
            external_id="OF-TXN-DRY",
            source="open_finance",
            transaction_date=date(2026, 7, 5),
            description="תשלום",
            amount=900,
            currency="ILS",
        )
        db.add_all([inv, tx])
        db.commit()

        import asyncio
        body = asyncio.run(
            reconciliation_dispatch.dispatch_reconciliation_to_sumit(
                db, org_id, dry_run=True
            )
        )

        assert body["dry_run"] is True
        db.refresh(tx)
        assert tx.reconciliation_dispatch_status in (None, "not_sent")
        assert tx.reconciliation_error is None
    finally:
        db.close()
