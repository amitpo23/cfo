"""Super-admin active-organization override (X-Active-Org-Id).

A SUPER_ADMIN may act within any organization by sending an X-Active-Org-Id
header; this is the single chokepoint that lets one operator inspect/sync every
client file. The override must be honored ONLY for a confirmed SUPER_ADMIN
(role read from the DB, never trusting a token claim), must validate the target
org, must reach writes/sync (not just reads), and must NEVER apply to a
non-super user — that would be a cross-tenant financial-data leak.
"""
import pytest
from datetime import date, datetime, timedelta, timezone

from cfo.database import SessionLocal
from cfo.models import (
    Alert,
    AlertSeverity,
    AlertStatus,
    AuditLog,
    BankTransaction,
    Bill,
    Invoice,
    OnboardingTask,
    SyncRun,
    SyncStatus,
    Task,
    TaskStatus,
    User,
    UserRole,
)


def _promote_to_super(email: str) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        user.role = UserRole.SUPER_ADMIN
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="module")
def superadmin(client):
    """A registered user promoted to SUPER_ADMIN in the DB (own org != 1)."""
    resp = client.post("/api/admin/auth/register", json={
        "email": "super-override@example.com",
        "password": "secret123",
        "full_name": "Super Override",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    _promote_to_super("super-override@example.com")
    return {
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
        "own_org": data["user"]["organization_id"],
    }


def _active_org(client, headers):
    """Resolve the org a request is scoped to, via a known org-returning route."""
    return client.get("/api/integration/status", headers=headers).json()["organization_id"]


# --- non-super users: header is completely ignored (P0 isolation) ------------
def test_non_super_user_cannot_override_org(client, tenant):
    headers = {**tenant["headers"], "X-Active-Org-Id": "1"}
    assert _active_org(client, headers) == tenant["user"]["organization_id"]


def test_non_super_override_does_not_leak_writes(client, owner, tenant):
    """A non-super tenant with the header must not write into another org."""
    headers = {**tenant["headers"], "X-Active-Org-Id": str(owner["user"]["organization_id"])}
    r = client.post("/api/tasks", json={"title": "tenant note"}, headers=headers)
    assert r.status_code == 200, r.text
    # The task must belong to the tenant's own org, NOT org 1.
    owner_titles = {t["title"] for t in client.get("/api/tasks", headers=owner["headers"]).json()}
    assert "tenant note" not in owner_titles


# --- super user: override honored for reads ---------------------------------
def test_super_without_header_uses_own_org(client, superadmin):
    assert _active_org(client, superadmin["headers"]) == superadmin["own_org"]


def test_super_with_header_targets_org(client, superadmin):
    headers = {**superadmin["headers"], "X-Active-Org-Id": "1"}
    assert _active_org(client, headers) == 1


def test_super_header_nonexistent_org_rejected(client, superadmin):
    headers = {**superadmin["headers"], "X-Active-Org-Id": "999999"}
    assert client.get("/api/integration/status", headers=headers).status_code == 404


def test_super_header_invalid_value_rejected(client, superadmin):
    headers = {**superadmin["headers"], "X-Active-Org-Id": "not-an-int"}
    assert client.get("/api/integration/status", headers=headers).status_code == 400


# --- super user: override reaches writes/sync, and is audited ----------------
def test_super_override_reaches_writes(client, owner, superadmin):
    """A POST under the override must land in the TARGET org (org 1)."""
    headers = {**superadmin["headers"], "X-Active-Org-Id": str(owner["user"]["organization_id"])}
    r = client.post("/api/tasks", json={"title": "super wrote into org1"}, headers=headers)
    assert r.status_code == 200, r.text
    owner_titles = {t["title"] for t in client.get("/api/tasks", headers=owner["headers"]).json()}
    assert "super wrote into org1" in owner_titles


def test_super_override_write_is_audited(client, owner, superadmin):
    """Mutations under impersonation must leave an AuditLog trail of the target org."""
    headers = {**superadmin["headers"], "X-Active-Org-Id": str(owner["user"]["organization_id"])}
    client.post("/api/tasks", json={"title": "audited write"}, headers=headers)

    db = SessionLocal()
    try:
        rows = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "IMPERSONATE",
                AuditLog.organization_id == owner["user"]["organization_id"],
            )
            .all()
        )
        assert rows, "expected an IMPERSONATE audit row for the targeted org"
    finally:
        db.close()


def test_super_admin_control_lists_all_orgs(client, owner, tenant, superadmin):
    resp = client.get("/api/admin/control/clients", headers=superadmin["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    org_ids = {c["organization_id"] for c in body["clients"]}
    assert owner["user"]["organization_id"] in org_ids
    assert tenant["user"]["organization_id"] in org_ids
    assert body["totals"]["organizations"] >= 2


def test_super_admin_control_includes_command_center_queues(client, fresh_org, superadmin):
    target = fresh_org()
    org_id = target["org_id"]
    db = SessionLocal()
    try:
        db.add(Invoice(
            organization_id=org_id,
            source="test",
            invoice_number="INV-QA",
            due_date=date.today() - timedelta(days=3),
            total=1000,
            balance=1000,
        ))
        db.add(Bill(
            organization_id=org_id,
            source="test",
            bill_number="BILL-QA",
            due_date=date.today() + timedelta(days=7),
            total=300,
            balance=300,
        ))
        db.add(BankTransaction(
            organization_id=org_id,
            source="test",
            external_id="BT-QA",
            transaction_date=date.today(),
            description="unmatched",
            amount=1000,
            is_reconciled=False,
        ))
        db.add(Alert(
            organization_id=org_id,
            alert_type="qa",
            severity=AlertSeverity.WARNING,
            status=AlertStatus.ACTIVE,
            title="QA alert",
        ))
        db.add(Task(
            organization_id=org_id,
            title="QA task",
            status=TaskStatus.OPEN,
        ))
        db.add(OnboardingTask(
            organization_id=org_id,
            source="sumit",
            step="qa_step",
            status="pending",
        ))
        db.add(SyncRun(
            organization_id=org_id,
            source="sumit",
            status=SyncStatus.COMPLETED,
            finished_at=datetime.now(timezone.utc) - timedelta(hours=30),
        ))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/admin/control/clients", headers=superadmin["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    row = next(c for c in body["clients"] if c["organization_id"] == org_id)

    assert row["freshness"]["is_stale"] is True
    assert row["work_queues"]["unreconciled_bank_transactions"] >= 1
    assert row["work_queues"]["overdue_receivables"] >= 1
    assert row["work_queues"]["payables_due_14d"] >= 1
    assert row["work_queues"]["open_alerts"] >= 1
    assert row["work_queues"]["open_tasks"] >= 1
    assert row["work_queues"]["onboarding_pending"] >= 1
    assert row["reconciliation"]["unmatched_txns"] >= 1
    assert body["totals"]["action_score"] >= row["work_queues"]["action_score"]


def test_non_super_cannot_read_control_plane(client, owner):
    resp = client.get("/api/admin/control/clients", headers=owner["headers"])
    assert resp.status_code == 403


def test_super_admin_can_trigger_client_sync_without_connections(client, fresh_org, superadmin):
    client_org = fresh_org()

    resp = client.post(
        f"/api/admin/control/clients/{client_org['org_id']}/sync",
        headers=superadmin["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["organization_id"] == client_org["org_id"]
    assert body["results"] == []
