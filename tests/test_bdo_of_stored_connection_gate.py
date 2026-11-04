"""The nightly bank sync reads only the org's stored Open Finance connection.

When that stored connection has expired while a newer one is ACTIVE, the sync
used to pass the consent gate and ingest nothing newer than the expiry. Now it
is an explicit skip, so the stale feed is visible. Made-up ids only.
"""
import pytest

from cfo.database import SessionLocal, init_db
from cfo.models import BankConnection, IntegrationConnection, Organization
from cfo.services.credentials_vault import encrypt_credentials


@pytest.fixture(autouse=True, scope="module")
def _ensure_schema():
    init_db()


def _org(db, stored: str, rows: dict) -> int:
    org = Organization(name="OF Stored Gate Co", is_active=True)
    db.add(org)
    db.flush()
    db.add(IntegrationConnection(
        organization_id=org.id, source="open_finance", status="active",
        credentials_encrypted=encrypt_credentials({"connection_id": stored}),
    ))
    for connection_id, status in rows.items():
        db.add(BankConnection(organization_id=org.id, source="open_finance",
                              connection_id=connection_id, status=status))
    db.commit()
    return org.id


def test_expired_stored_connection_is_an_explicit_skip():
    from cfo.api.routes.cron import _of_consent_gate

    with SessionLocal() as db:
        org_id = _org(db, "t-old", {"t-old": "EXPIRED", "t-new": "ACTIVE"})
        gated = _of_consent_gate(db, org_id)
    assert gated == {
        "organization_id": org_id,
        "source": "open_finance",
        "skipped": "stored_connection_not_active",
        "stored_connection_status": "EXPIRED",
        "active_connections": 1,
    }


def test_active_stored_connection_passes():
    from cfo.api.routes.cron import _of_consent_gate

    with SessionLocal() as db:
        org_id = _org(db, "t-live", {"t-old-2": "EXPIRED", "t-live": "ACTIVE"})
        assert _of_consent_gate(db, org_id) is None
