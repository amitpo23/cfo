"""run_post_sync_tasks used to call DataSyncService.sync_all() (the legacy
Account/Transaction sync path) on every real sync. That path is broken:
data_sync_service.py compares SUMIT's numeric document_type against string
literals ('invoice', 'receipt', 'tax_invoice') -- always False -- so every
document lands as a zero-amount EXPENSE transaction with a garbage
"<code>: Unknown" description. Confirmed live in prod 2026-07-03 (127 such
rows for one real org). Per user decision: stop generating new garbage,
leave existing rows alone (no purge)."""
import asyncio

from cfo.database import SessionLocal
from cfo.models import IntegrationConnection
from cfo.services.client_automation_service import run_post_sync_tasks
from cfo.services.data_sync_service import DataSyncService


def test_run_post_sync_tasks_does_not_invoke_the_broken_data_sync_service(fresh_org, monkeypatch):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(IntegrationConnection(organization_id=org_id, source="sumit", status="active"))
        db.commit()

        called = {"sync_all": False}

        async def _fail_if_called(self):
            called["sync_all"] = True
            raise AssertionError("DataSyncService.sync_all() must not run from the auto-sync hook")

        monkeypatch.setattr(DataSyncService, "sync_all", _fail_if_called)

        result = asyncio.run(run_post_sync_tasks(db, org_id, resume_onboarding=False))

        assert called["sync_all"] is False
        assert "transactions" not in result
        assert "transactions_error" not in result
    finally:
        db.close()
