"""Binding an existing consent can share the Financy identity of a sibling entity.

Production, 27/10/2026: the Hapoalim consent of an import-only entity was bound,
and the first sync failed on "Open Finance credentials not configured:
OPEN_FINANCE_USER_ID". The consent lives under the same Financy user as the
group's primary entity; Rezef's design shares one identity across organizations
with a per-organization connection scope, but the bind gave the new organization
the scope and no identity. ``identity_from_organization_id`` copies the identity
server side, only between two entities of one dashboard, never returns it, and
records the copy in the audit log without a value. No provider calls.
"""
import pytest

from cfo.database import SessionLocal, init_db
from cfo.models import (
    AuditLog, ClientDashboard, DashboardEntity, IntegrationConnection, Organization,
)
from cfo.services.bank_coverage import OpenFinanceBindError, bind_existing_connection
from cfo.services.credentials_vault import decrypt_credentials, encrypt_credentials
from cfo.services.sync_engine import get_connector_for_org

SECRET_USER = "owner-identity@example.com"


@pytest.fixture(autouse=True, scope="module")
def _ensure_schema():
    init_db()


def _org(db, name):
    org = Organization(name=name, is_active=True)
    db.add(org)
    db.flush()
    return org


def _identity(db, org_id, connection_id="conn-primary"):
    db.add(IntegrationConnection(
        organization_id=org_id, source="open_finance", status="active",
        credentials_encrypted=encrypt_credentials({"user_id": SECRET_USER, "connection_id": connection_id}),
    ))


def _group(db, primary_id, entity_id):
    dashboard = ClientDashboard(slug=f"group-{primary_id}-{entity_id}", title="קבוצה",
                                primary_organization_id=primary_id)
    db.add(dashboard)
    db.flush()
    db.add(DashboardEntity(dashboard_id=dashboard.id, organization_id=entity_id, label="ישות", role="related"))


def _creds(db, org_id):
    row = db.query(IntegrationConnection).filter_by(organization_id=org_id, source="open_finance").one()
    return decrypt_credentials(row.credentials_encrypted)


def test_a_sibling_entity_gets_the_identity_and_its_own_scope():
    with SessionLocal() as db:
        primary, entity = _org(db, "ראשית"), _org(db, "ישות")
        _identity(db, primary.id)
        _group(db, primary.id, entity.id)
        db.commit()

        result = bind_existing_connection(
            db, entity.id, connection_id="conn-entity", status="ACTIVE",
            identity_from_organization_id=primary.id,
        )

        creds = _creds(db, entity.id)
        assert creds["user_id"] == SECRET_USER
        assert creds["connection_id"] == "conn-entity"
        assert SECRET_USER not in repr(result)
        audit = db.query(AuditLog).filter_by(organization_id=entity.id,
                                             action="BIND_OPEN_FINANCE_CONNECTION").one()
        assert audit.details["identity_from_organization_id"] == primary.id
        assert SECRET_USER not in repr(audit.details)


def test_a_rerun_on_an_already_bound_organization_adds_the_identity():
    with SessionLocal() as db:
        primary, entity = _org(db, "ראשית"), _org(db, "ישות")
        _identity(db, primary.id)
        _group(db, primary.id, entity.id)
        db.commit()
        bind_existing_connection(db, entity.id, connection_id="conn-rerun", status="ACTIVE")
        assert "user_id" not in _creds(db, entity.id)

        bind_existing_connection(db, entity.id, connection_id="conn-rerun", status="ACTIVE",
                                 identity_from_organization_id=primary.id)

        assert _creds(db, entity.id)["user_id"] == SECRET_USER


def test_the_identity_is_never_copied_between_unrelated_organizations():
    with SessionLocal() as db:
        primary, stranger = _org(db, "ראשית"), _org(db, "זר")
        _identity(db, primary.id)
        db.commit()

        with pytest.raises(OpenFinanceBindError):
            bind_existing_connection(db, stranger.id, connection_id="conn-stranger", status="ACTIVE",
                                     identity_from_organization_id=primary.id)


def test_a_source_without_an_identity_is_refused():
    with SessionLocal() as db:
        primary, entity = _org(db, "ראשית"), _org(db, "ישות")
        _group(db, primary.id, entity.id)
        db.commit()

        with pytest.raises(OpenFinanceBindError):
            bind_existing_connection(db, entity.id, connection_id="conn-none", status="ACTIVE",
                                     identity_from_organization_id=primary.id)


def test_the_bound_entity_then_resolves_a_connector_scoped_to_its_own_consent(monkeypatch):
    from cfo.config import settings

    monkeypatch.setattr(settings, "open_finance_client_id", "client")
    monkeypatch.setattr(settings, "open_finance_client_secret", "secret")
    with SessionLocal() as db:
        primary, entity = _org(db, "ראשית"), _org(db, "ישות")
        _identity(db, primary.id)
        _group(db, primary.id, entity.id)
        db.commit()
        bind_existing_connection(db, entity.id, connection_id="conn-scope", status="ACTIVE",
                                 identity_from_organization_id=primary.id)

        connector, _conn_id, source = get_connector_for_org(db, entity.id, "open_finance")

        assert source == "open_finance"
        assert connector.connection_id == "conn-scope"


def test_the_admin_route_passes_the_identity_source_and_never_returns_it(client, fresh_org):
    from tests.test_open_finance_bind_and_coverage import _super

    admin = _super(fresh_org())
    with SessionLocal() as db:
        primary, entity = _org(db, "ראשית"), _org(db, "ישות")
        _identity(db, primary.id)
        _group(db, primary.id, entity.id)
        db.commit()
        primary_id, entity_id = primary.id, entity.id

    response = client.post(
        f"/api/admin/organizations/{entity_id}/open-finance/bind",
        headers=admin["headers"],
        json={"connection_id": "conn-route", "status": "ACTIVE", "identity_from_organization_id": primary_id},
    )

    assert response.status_code == 200, response.text
    assert SECRET_USER not in response.text
    with SessionLocal() as db:
        assert _creds(db, entity_id)["user_id"] == SECRET_USER
