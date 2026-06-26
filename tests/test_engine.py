"""Tests for the unifying engine (status + pipeline aggregation)."""
from datetime import date

from cfo.database import SessionLocal
from cfo.models import Invoice, InvoiceStatus
from cfo.services import engine_service


def _seed(org_id):
    db = SessionLocal()
    try:
        db.query(Invoice).filter(Invoice.organization_id == org_id,
                                 Invoice.source == "eng-test").delete()
        db.commit()
        db.add(Invoice(organization_id=org_id, external_id="ENG-INV-1", source="eng-test",
                       invoice_number="1", issue_date=date(2026, 6, 1),
                       status=InvoiceStatus.SENT, subtotal=1000, tax=180, total=1180))
        db.commit()
    finally:
        db.close()


def test_status_reports_counts_and_connections(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        st = engine_service.status(db, org_id)
        assert st["organization_id"] == org_id
        assert st["counts"]["invoices"] >= 1
        assert "sumit" in st["connections"]
        assert st["bank_data_validated"] is False
        assert st["ready"] is True
    finally:
        db.close()


def test_run_pipeline_aggregates_stages_with_state_tags(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        result = engine_service.run_pipeline(db, org_id, year=2026, month=6)
        stage_names = {s["stage"] for s in result["stages"]}
        assert {"ledger", "aging", "cumulative_pl"}.issubset(stage_names)
        # Ledger stage must report a balanced trial balance.
        ledger_stage = next(s for s in result["stages"] if s["stage"] == "ledger")
        assert ledger_stage["state"] == "derived"
        assert ledger_stage["summary"]["balanced"] is True
        # Legend documents every state tag used.
        assert set(result["legend"]) == {"real", "derived", "unvalidated"}
    finally:
        db.close()


def test_status_default_org_sees_env_sumit_credentials(owner):
    # The default org (id 1) gets SUMIT from env credentials, not a connection row.
    org_id = owner["user"]["organization_id"]
    db = SessionLocal()
    try:
        st = engine_service.status(db, org_id)
        assert st["connections"]["sumit"] is True
    finally:
        db.close()


def test_engine_routes_require_auth(client):
    for path in ["/api/engine/status", "/api/engine/run"]:
        assert client.get(path).status_code == 403, path
