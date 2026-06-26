"""Onboarding data-mapping pipeline: checklist materialization, reconcile gate, snapshot.

The full live pipeline is exercised against a real osek during onboarding; here we lock
the deterministic logic offline with a stub connector so the codified checklist behaves
identically for every future business.
"""
import asyncio
from datetime import date
from decimal import Decimal

import pytest

from cfo.database import SessionLocal, init_db
from cfo.models import Organization, Invoice, Bill, InvoiceStatus, BillStatus
from cfo.services import onboarding_service


@pytest.fixture(autouse=True, scope="module")
def _ensure_schema():
    # These service tests use SessionLocal directly (not the TestClient), so the
    # app-startup create_all never runs — create the schema explicitly.
    init_db()


def _make_org(db, name="Onboard Co"):
    org = Organization(name=name, is_active=True)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def test_ensure_tasks_is_idempotent_and_status_reports_steps():
    db = SessionLocal()
    try:
        org = _make_org(db)
        onboarding_service.ensure_tasks(db, org.id, "sumit")
        onboarding_service.ensure_tasks(db, org.id, "sumit")  # twice — no duplicates
        st = onboarding_service.status(db, org.id, "sumit")
        steps = [s["step"] for s in st["steps"]]
        assert steps == [s["step"] for s in onboarding_service.ONBOARDING_STEPS]
        assert st["complete"] is False
        assert all(s["status"] == "pending" for s in st["steps"])
    finally:
        db.close()


def test_financial_snapshot_computes_net_pl():
    db = SessionLocal()
    try:
        org = _make_org(db, "Snapshot Co")
        year = date.today().year
        db.add(Invoice(organization_id=org.id, source="sumit", external_id="i1",
                       issue_date=date(year, 2, 1), status=InvoiceStatus.SENT,
                       subtotal=Decimal("1000"), tax=Decimal("180"), total=Decimal("1180")))
        db.add(Bill(organization_id=org.id, source="sumit", external_id="b1",
                    issue_date=date(year, 2, 2), status=BillStatus.RECEIVED,
                    subtotal=Decimal("400"), tax=Decimal("72"), total=Decimal("472")))
        db.commit()
        out = asyncio.run(onboarding_service._h_financial_snapshot(db, org.id, {}))
        assert out["revenue_net"] == 1000.0
        assert out["expenses_net"] == 400.0
        assert out["profit_net"] == 600.0
        assert out["vat_to_pay"] == 108.0  # 180 - 72
    finally:
        db.close()


class _FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeConnector:
    """Stub connector: connection OK, and live counts that match what's in the DB."""
    def __init__(self, income_docs, expense_docs):
        self._income, self._expense = income_docs, expense_docs

    async def test_connection(self):
        return True

    async def _get_client(self):
        return _FakeClient()

    async def _list_documents_all(self, client, type_code, updated_since):
        return self._income if type_code == "0" else self._expense


def test_run_onboarding_completes_when_db_reconciles(monkeypatch):
    db = SessionLocal()
    try:
        org = _make_org(db, "Reconcile Co")
        # DB has 2 invoices + 1 bill from sumit
        for n in ("i1", "i2"):
            db.add(Invoice(organization_id=org.id, source="sumit", external_id=n,
                           issue_date=date.today(), status=InvoiceStatus.SENT,
                           subtotal=Decimal("100"), tax=Decimal("18"), total=Decimal("118")))
        db.add(Bill(organization_id=org.id, source="sumit", external_id="b1",
                    issue_date=date.today(), status=BillStatus.RECEIVED,
                    subtotal=Decimal("50"), tax=Decimal("9"), total=Decimal("59")))
        db.commit()

        fake = _FakeConnector(income_docs=[1, 2], expense_docs=[1])  # source counts: 2 income, 1 expense

        from cfo.services import sync_engine

        def fake_get_connector(_db, _org, _src):
            return fake, None, "sumit"

        class _FakeRun:
            status = None
            counts = {"invoices": {"created": 0}}

        class _FakeEngine:
            def __init__(self, *a, **k):
                pass

            async def run_full_sync(self):
                return _FakeRun()

        monkeypatch.setattr(sync_engine, "get_connector_for_org", fake_get_connector)
        monkeypatch.setattr(sync_engine, "SyncEngine", _FakeEngine)

        result = asyncio.run(onboarding_service.run_onboarding(db, org.id, "sumit"))
        assert result["complete"] is True, result
        by = {s["step"]: s for s in result["steps"]}
        assert by["reconcile"]["status"] == "completed"
        assert by["reconcile"]["result"]["income"] == {"db": 2, "source": 2}
    finally:
        db.close()


def test_run_onboarding_blocks_when_db_is_missing_documents(monkeypatch):
    db = SessionLocal()
    try:
        org = _make_org(db, "Incomplete Co")
        db.add(Invoice(organization_id=org.id, source="sumit", external_id="i1",
                       issue_date=date.today(), status=InvoiceStatus.SENT,
                       subtotal=Decimal("100"), tax=Decimal("18"), total=Decimal("118")))
        db.commit()

        # Source reports MORE documents than the DB has -> reconcile must fail.
        fake = _FakeConnector(income_docs=[1, 2, 3], expense_docs=[1, 2])

        from cfo.services import sync_engine

        class _FakeRun:
            status = None
            counts = {}

        class _FakeEngine:
            def __init__(self, *a, **k):
                pass

            async def run_full_sync(self):
                return _FakeRun()

        monkeypatch.setattr(sync_engine, "get_connector_for_org",
                            lambda *_a: (fake, None, "sumit"))
        monkeypatch.setattr(sync_engine, "SyncEngine", _FakeEngine)

        result = asyncio.run(onboarding_service.run_onboarding(db, org.id, "sumit"))
        assert result["complete"] is False
        by = {s["step"]: s for s in result["steps"]}
        assert by["reconcile"]["status"] == "failed"
        assert "incomplete" in (by["reconcile"]["error"] or "")
    finally:
        db.close()
