"""Durable control-plane tests for irreversible financial actions."""
import pytest

from cfo.database import SessionLocal
from cfo.models import User, UserRole
from cfo.services.irreversible_action_service import (
    ActionAuthorizationError,
    ActionConflictError,
    ActionStateError,
    IrreversibleActionService,
)


def _owner_row(owner):
    db = SessionLocal()
    try:
        return db.get(User, owner["user"]["id"])
    finally:
        db.close()


def test_action_lifecycle_is_persistent_idempotent_and_execute_once(owner):
    db = SessionLocal()
    try:
        owner_row = db.get(User, owner["user"]["id"])
        service = IrreversibleActionService(db, owner_row.organization_id)

        proposed = service.propose(
            proposed_by=owner_row,
            action_type="payment",
            payload={"bill_id": 17, "amount": "125.40", "currency": "ILS"},
            idempotency_key="payment:bill:17:v1",
            description="תשלום חשבון 17",
        )
        duplicate = service.propose(
            proposed_by=owner_row,
            action_type="payment",
            payload={"currency": "ILS", "amount": "125.40", "bill_id": 17},
            idempotency_key="payment:bill:17:v1",
            description="תשלום חשבון 17",
        )

        assert duplicate.id == proposed.id
        assert proposed.status == "proposed"
        assert proposed.payload_sha256

        approved = service.approve(proposed.id, approved_by=owner_row)
        assert approved.status == "approved"
        assert approved.approved_by_user_id == owner_row.id
        assert approved.approver_role == UserRole.ADMIN.value

        claimed = service.claim_for_execution(proposed.id)
        assert claimed.status == "executing"
        with pytest.raises(ActionStateError, match="approved"):
            service.claim_for_execution(proposed.id)

        executed = service.mark_executed(
            proposed.id,
            provider_reference="provider-payment-17",
            execution_result={"accepted": True},
        )
        assert executed.status == "executed"

        verified = service.mark_verified(
            proposed.id,
            verification_evidence={
                "provider_reference": "provider-payment-17",
                "readback_status": "completed",
            },
        )
        assert verified.status == "verified"
        assert verified.verified_at is not None
    finally:
        db.close()


def test_idempotency_key_cannot_hide_a_changed_payload(owner):
    db = SessionLocal()
    try:
        owner_row = db.get(User, owner["user"]["id"])
        service = IrreversibleActionService(db, owner_row.organization_id)
        service.propose(
            proposed_by=owner_row,
            action_type="refund",
            payload={"payment_id": "p1", "amount": "10.00"},
            idempotency_key="refund:p1:v1",
        )

        with pytest.raises(ActionConflictError, match="different action or payload"):
            service.propose(
                proposed_by=owner_row,
                action_type="refund",
                payload={"payment_id": "p1", "amount": "11.00"},
                idempotency_key="refund:p1:v1",
            )
    finally:
        db.close()


def test_non_signer_cannot_approve_and_cross_org_cannot_observe(owner, tenant):
    db = SessionLocal()
    try:
        owner_row = db.get(User, owner["user"]["id"])
        tenant_row = db.get(User, tenant["user"]["id"])
        regular = User(
            organization_id=owner_row.organization_id,
            email="approval-regular@example.com",
            password_hash="not-used",
            full_name="Regular",
            role=UserRole.USER,
            is_active=True,
        )
        db.add(regular)
        db.commit()
        db.refresh(regular)

        owner_service = IrreversibleActionService(db, owner_row.organization_id)
        proposed = owner_service.propose(
            proposed_by=regular,
            action_type="period_close",
            payload={"period": "2026-07"},
            idempotency_key="period-close:2026-07",
        )

        with pytest.raises(ActionAuthorizationError, match="signing authority"):
            owner_service.approve(proposed.id, approved_by=regular)

        tenant_service = IrreversibleActionService(db, tenant_row.organization_id)
        assert tenant_service.get(proposed.id) is None
        with pytest.raises(ActionStateError, match="not found"):
            tenant_service.claim_for_execution(proposed.id)
    finally:
        db.close()


def test_approval_routes_expose_propose_review_and_reject(client, owner, tenant):
    proposal = client.post(
        "/api/approvals",
        headers=owner["headers"],
        json={
            "action_type": "filing_submission",
            "payload": {"period": "2026-06", "report": "vat"},
            "idempotency_key": "vat-filing:2026-06:v1",
            "description": "שידור דוח מע״מ יוני",
        },
    )
    assert proposal.status_code == 201, proposal.text
    action_id = proposal.json()["id"]
    assert proposal.json()["status"] == "proposed"

    hidden = client.get(f"/api/approvals/{action_id}", headers=tenant["headers"])
    assert hidden.status_code == 404

    approved = client.post(
        f"/api/approvals/{action_id}/approve",
        headers=owner["headers"],
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    listing = client.get("/api/approvals", headers=owner["headers"])
    assert listing.status_code == 200
    assert any(row["id"] == action_id for row in listing.json()["items"])

    rejected_proposal = client.post(
        "/api/approvals",
        headers=owner["headers"],
        json={
            "action_type": "period_close",
            "payload": {"period": "2026-06"},
            "idempotency_key": "period-close:2026-06:rejection-test",
        },
    )
    rejected_id = rejected_proposal.json()["id"]
    rejected = client.post(
        f"/api/approvals/{rejected_id}/reject",
        headers=owner["headers"],
        json={"reason": "ההתאמות טרם הושלמו"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
