"""Import-only clients must never inherit a provider or start an automation."""
from copy import deepcopy
from datetime import date
import hashlib
import json

import pytest

from cfo.database import SessionLocal
from cfo.models import Account, AuditLog, BankTransaction, IntegrationConnection, JournalEntry, OnboardingTask, Organization, SumitCompany
from cfo.services import local_client_service as service


def register(db, office_id, tax_id="101010101"):
    return service.register_local_client(db, office_id, name="Foodgroup Test", tax_id=tax_id)


def bundle(kind="journal"):
    rows = ([{"external_id": "entry-173", "date": "2026-10-07", "amount": "5730.00",
              "debit_account": "50016", "credit_account": "10006", "description": "source journal", "currency": "ILS"}]
            if kind == "journal" else
            [{"external_id": "1662-017", "date": "2026-09-27", "amount": "-6000.00",
              "description": "source bank", "currency": "ILS"}])
    return {"kind": kind, "source_name": "synthetic-reviewed-source.json",
            "source_sha256": hashlib.sha256(b"synthetic original").hexdigest(),
            "observed_at": "2026-10-15T12:00:00Z", "bank_account_suffix": "1662" if kind == "bank" else None,
            "rows": rows}


def test_registration_never_creates_connections_or_automation(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        result = register(db, office)
        org_id = result["target_organization_id"]
        assert org_id != office
        assert result["mode"] == "import_only"
        assert result["company_id"] is None
        assert result["automation"]["state"] == "disabled"
        assert db.query(IntegrationConnection).filter_by(organization_id=org_id).count() == 0
        assert db.query(OnboardingTask).filter_by(organization_id=org_id).count() == 0
        org = db.get(Organization, org_id)
        assert org.integration_type.value == "manual"
        assert org.settings["provider_calls_allowed"] is False
        assert db.query(AuditLog).filter_by(organization_id=org_id, action="CREATE_IMPORT_ONLY_CLIENT").count() == 1


def test_registration_is_idempotent_and_cannot_capture_another_office_client(fresh_org):
    office_a, office_b = fresh_org()["org_id"], fresh_org()["org_id"]
    with SessionLocal() as db:
        first = register(db, office_a, "123456782")
        again = register(db, office_a, "123456782")
        assert first["target_organization_id"] == again["target_organization_id"]
        assert db.query(Organization).filter_by(tax_id="123456782").count() == 1
        with pytest.raises(ValueError, match="identity|office"):
            register(db, office_b, "123456782")


def test_existing_live_organization_cannot_be_repurposed(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        other = Organization(name="Existing independently owned company", tax_id="999999999", is_active=True)
        db.add(other); db.commit()
        with pytest.raises(ValueError, match="identity|office"):
            register(db, office, "999999999")
        assert db.get(Organization, other.id).name == "Existing independently owned company"


def test_import_is_atomic_repeatable_and_keeps_original_source(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = register(db, office, "222222222")
        payload = bundle()
        first = service.import_reviewed_source(db, office, client["id"], payload)
        second = service.import_reviewed_source(db, office, client["id"], payload)
        assert first["inserted"] == 1
        assert second["inserted"] == 0 and second["unchanged"] == 1
        row = db.query(JournalEntry).filter_by(organization_id=client["target_organization_id"], source=service.SOURCE).one()
        assert row.entry_date == date(2026, 10, 7)
        assert row.raw_data["source_sha256"] == payload["source_sha256"]
        assert row.raw_data["original"]["external_id"] == "entry-173"
        assert row.raw_data["reporting_status"] == "source_chart_unmapped"
        assert row.lines[0]["account"] == "50016"
        assert row.lines[1]["credit"] == "5730.00"
        assert first["provider_calls"] == 0


def test_reimport_source_conflict_never_silently_overwrites(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = register(db, office, "333333333")
        payload = bundle()
        service.import_reviewed_source(db, office, client["id"], payload)
        altered = deepcopy(payload)
        altered["rows"][0]["amount"] = "999.00"
        altered["rows"].insert(0, {**payload["rows"][0], "external_id": "new-before-conflict"})
        with pytest.raises(ValueError, match="conflict"):
            service.import_reviewed_source(db, office, client["id"], altered)
        assert db.query(JournalEntry).filter_by(organization_id=client["target_organization_id"]).count() == 1


def test_bank_import_has_separate_tenant_and_unknown_balance(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = register(db, office, "444444444")
        service.import_reviewed_source(db, office, client["id"], bundle("bank"))
        row = db.query(BankTransaction).filter_by(organization_id=client["target_organization_id"]).one()
        account = db.get(Account, row.account_id)
        assert account.organization_id == row.organization_id
        assert account.balance is None
        assert account.owner_national_id is None
        assert account.source == service.SOURCE
        assert account.open_finance_connection_id is None
        assert row.is_provisional is True and row.is_reconciled is False
        assert row.raw_data["source_observed_at"] == "2026-10-15T12:00:00+00:00"
        assert row.raw_data.get("status") != "BOOKED"
        assert row.raw_data["source_account_suffix"] == "1662"


def test_office_scope_and_invalid_payloads_are_refused_before_any_write(fresh_org):
    office_a, office_b = fresh_org()["org_id"], fresh_org()["org_id"]
    with SessionLocal() as db:
        client = register(db, office_a, "555555555")
        with pytest.raises(ValueError, match="office"):
            service.import_reviewed_source(db, office_b, client["id"], bundle())
        invalid = bundle()
        invalid["rows"].append({**invalid["rows"][0], "external_id": "bad", "amount": "NaN"})
        with pytest.raises(ValueError):
            service.import_reviewed_source(db, office_a, client["id"], invalid)
        assert db.query(JournalEntry).filter_by(organization_id=client["target_organization_id"]).count() == 0


def test_expected_daily_coverage_includes_local_client_without_sync(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = register(db, office, "666666666")
        report = service.local_client_coverage(db, office)
        row = next(r for r in report["clients"] if r["organization_id"] == client["target_organization_id"])
        assert row["mode"] == "import_only"
        assert row["sources"]["open_finance"]["status"] == "not_connected"
        assert row["sources"]["sumit"]["status"] == "disabled"
        assert row["morning_cycle"]["status"] == "not_run"
        assert report["provider_calls"] == 0


def test_http_registration_and_import_require_active_office_admin(client, owner):
    assert client.post("/api/office/clients/import-only", json={"name": "Example", "tax_id": "777777777"}).status_code == 403
    response = client.post("/api/office/clients/import-only", headers=owner["headers"], json={"name": "HTTP import only", "tax_id": "777777777"})
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["mode"] == "import_only"
    imported = client.post(f'/api/office/clients/{row["id"]}/reviewed-import', headers=owner["headers"], json=bundle())
    assert imported.status_code == 200, imported.text
    assert imported.json()["provider_calls"] == 0
    coverage = client.get("/api/office/clients/daily-coverage", headers=owner["headers"])
    assert coverage.status_code == 200, coverage.text
    assert any(r["organization_id"] == row["target_organization_id"] for r in coverage.json()["clients"])


def test_import_only_mode_refuses_connector_even_if_credentials_are_added(fresh_org):
    from cfo.services.sync_engine import get_connector_for_org
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        local = register(db, office, "888888888")
        db.add(IntegrationConnection(organization_id=local["target_organization_id"], source="sumit", status="active", credentials_encrypted="must-not-decrypt"))
        db.commit()
        with pytest.raises(ValueError, match="disabled"):
            get_connector_for_org(db, local["target_organization_id"], "sumit")
