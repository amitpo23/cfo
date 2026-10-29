"""Per-org SUMIT credentials issue documents without the env allowlist.

The environment key is only for SUMIT_ENV_CREDENTIAL_ORG_IDS. It is not
borrowed for a sibling organization.
"""
from cfo.config import settings
from cfo.database import SessionLocal
from cfo.models import IntegrationConnection, Organization
from cfo.services.credentials_vault import encrypt_credentials
from cfo.services.sumit_credentials import resolve_sumit_credentials


def test_own_connection_is_configured_without_the_env_allowlist(client, fresh_org, monkeypatch):
    monkeypatch.setattr(settings, "sumit_env_credential_org_ids", "1")
    monkeypatch.setattr(settings, "sumit_api_key", "env-key-must-not-leak")
    monkeypatch.setattr(settings, "sumit_company_id", "env-company")
    org = fresh_org()
    other = fresh_org()
    assert org["org_id"] != 1

    db = SessionLocal()
    try:
        db.add(IntegrationConnection(
            organization_id=org["org_id"], source="sumit", status="active",
            credentials_encrypted=encrypt_credentials({"api_key": "foodgroup-key", "company_id": "6"}),
        ))
        db.commit()
        own = resolve_sumit_credentials(db, org["org_id"])
        sibling = resolve_sumit_credentials(db, other["org_id"])
    finally:
        db.close()

    assert own == {"api_key": "foodgroup-key", "company_id": "6"}
    assert sibling is None

    status = client.get("/api/integration/status", headers=org["headers"]).json()
    other_status = client.get("/api/integration/status", headers=other["headers"]).json()
    assert status["configured"]["sumit"] is True
    assert other_status["configured"]["sumit"] is False
    assert "foodgroup-key" not in other_status.__repr__()
    assert "env-key-must-not-leak" not in status.__repr__()


def test_portal_credentials_on_the_org_row_are_used(client, fresh_org, monkeypatch):
    monkeypatch.setattr(settings, "sumit_env_credential_org_ids", "")
    monkeypatch.setattr(settings, "sumit_api_key", "env-key-must-not-leak")
    org = fresh_org()
    db = SessionLocal()
    try:
        row = db.get(Organization, org["org_id"])
        row.api_credentials = {"api_key": "portal-key", "company_id": "portal-co"}
        db.commit()
        resolved = resolve_sumit_credentials(db, org["org_id"])
    finally:
        db.close()
    assert resolved == {"api_key": "portal-key", "company_id": "portal-co"}


def test_missing_sumit_credentials_say_so_in_hebrew(client, fresh_org, monkeypatch):
    from cfo.services.data_sync_service import SumitNotConfiguredError
    from cfo.services.sync_engine import get_connector_for_org

    monkeypatch.setattr(settings, "sumit_env_credential_org_ids", "1")
    monkeypatch.setattr(settings, "sumit_api_key", "env-key-must-not-leak")
    org = fresh_org()
    db = SessionLocal()
    try:
        try:
            get_connector_for_org(db, org["org_id"], preferred_source="sumit")
        except SumitNotConfiguredError as exc:
            message = str(exc)
        else:
            raise AssertionError("a keyless org built a SUMIT client")
    finally:
        db.close()
    assert "אין אישורי SUMIT" in message
    assert "env-key" not in message
