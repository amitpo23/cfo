"""Persistent organization policy and three-moment enforcement tests."""
import asyncio
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import (
    OrganizationMembership,
    OrganizationSigningAuthority,
    ChatMessage,
    PolicyGrant,
    User,
    UserRole,
)
from cfo.services import membership_service
from cfo.services.irreversible_action_service import (
    ActionAuthorizationError,
    IrreversibleActionService,
)
from cfo.services.policy_service import PolicyService
from cfo.services.ai_chat_service import AIChatService, ChatConfirmationError
from cfo.services import ai_chat_service
from cfo.services.ai_chat_tools import TOOLS
from cfo.services import policy_engine


def _owner(db, fixture):
    if "user" in fixture:
        return db.get(User, fixture["user"]["id"])
    return db.query(User).filter(User.organization_id == fixture["org_id"]).one()


def test_explicit_deny_is_persistent_scoped_and_beats_admin_preset(fresh_org):
    owner, tenant = fresh_org(), fresh_org()
    db = SessionLocal()
    try:
        owner_row = _owner(db, owner)
        tenant_row = _owner(db, tenant)
        service = PolicyService(db, owner_row.organization_id)
        grant = service.create_grant(
            created_by=owner_row,
            action="bank_payment.propose",
            effect="deny",
            role=UserRole.ADMIN,
        )
        db.commit()

        assert db.get(PolicyGrant, grant.id).organization_id == owner_row.organization_id
        decision = service.evaluate(
            user=owner_row,
            action="bank_payment.propose",
            amount=Decimal("10"),
        )
        assert decision.allowed is False
        assert decision.reason == "explicit_deny"

        foreign = PolicyService(db, tenant_row.organization_id).list_grants()
        assert all(row.id != grant.id for row in foreign)
    finally:
        db.close()


def test_policy_is_enforced_at_proposal_and_decision_is_persisted(fresh_org):
    owner = fresh_org()
    db = SessionLocal()
    try:
        owner_row = _owner(db, owner)
        PolicyService(db, owner_row.organization_id).create_grant(
            created_by=owner_row,
            action="bank_payment.propose",
            effect="allow",
            role=UserRole.ADMIN,
            max_amount=Decimal("50"),
        )
        db.commit()

        service = IrreversibleActionService(db, owner_row.organization_id)
        with pytest.raises(ActionAuthorizationError, match="amount_exceeds_ceiling"):
            service.propose(
                proposed_by=owner_row,
                action_type="payment",
                payload={"amount": "51", "currency": "ILS"},
                idempotency_key="policy-over-ceiling",
            )

        row = service.propose(
            proposed_by=owner_row,
            action_type="payment",
            payload={"amount": "49", "currency": "ILS"},
            idempotency_key="policy-within-ceiling",
        )
        assert row.policy_proposed_decision["allowed"] is True
        assert row.policy_proposed_decision["action"] == "bank_payment.propose"
    finally:
        db.close()


def test_role_change_between_proposal_and_approval_fails_closed(fresh_org):
    owner = fresh_org()
    db = SessionLocal()
    try:
        owner_row = _owner(db, owner)
        service = IrreversibleActionService(db, owner_row.organization_id)
        row = service.propose(
            proposed_by=owner_row,
            action_type="payment",
            payload={"amount": "10", "currency": "ILS"},
            idempotency_key="policy-demotion-before-approval",
        )

        membership = db.query(OrganizationMembership).filter_by(
            organization_id=owner_row.organization_id,
            user_id=owner_row.id,
        ).one()
        membership.role = UserRole.VIEWER
        db.commit()

        with pytest.raises(ActionAuthorizationError, match="no_policy_grants"):
            service.approve(row.id, approved_by=owner_row)
    finally:
        db.close()


def test_revoked_grant_after_approval_blocks_execution_claim(fresh_org):
    owner = fresh_org()
    db = SessionLocal()
    try:
        owner_row = _owner(db, owner)
        policies = PolicyService(db, owner_row.organization_id)
        grant = policies.create_grant(
            created_by=owner_row,
            action="bank_payment.propose",
            effect="allow",
            user_id=owner_row.id,
            max_amount=Decimal("100"),
        )
        db.commit()
        service = IrreversibleActionService(db, owner_row.organization_id)
        row = service.propose(
            proposed_by=owner_row,
            action_type="payment",
            payload={"amount": "10", "currency": "ILS"},
            idempotency_key="policy-revoked-before-execute",
        )
        service.approve(row.id, approved_by=owner_row)

        policies.revoke_grant(grant.id, revoked_by=owner_row)
        policies.create_grant(
            created_by=owner_row,
            action="bank_payment.propose",
            effect="deny",
            user_id=owner_row.id,
        )
        db.commit()

        with pytest.raises(ActionAuthorizationError, match="explicit_deny"):
            service.claim_for_execution(row.id)
        db.refresh(row)
        assert row.status == "approved"
        assert row.execution_started_at is None
    finally:
        db.close()


def test_non_admin_cannot_manage_policy_grants(fresh_org):
    owner = fresh_org()
    db = SessionLocal()
    try:
        owner_row = _owner(db, owner)
        user = User(
            organization_id=owner_row.organization_id,
            email="policy-user@example.com",
            password_hash="unused",
            full_name="Policy User",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(user)
        db.flush()
        membership_service.grant(
            db,
            organization_id=owner_row.organization_id,
            user_id=user.id,
            role=UserRole.USER,
            granted_by_user_id=owner_row.id,
        )
        db.commit()

        with pytest.raises(PermissionError, match="organization admin"):
            PolicyService(db, owner_row.organization_id).create_grant(
                created_by=user,
                action="invoices.issue",
                effect="allow",
                user_id=user.id,
            )
    finally:
        db.close()


def test_platform_super_admin_can_manage_policy_in_an_explicit_org(fresh_org):
    """Platform operations may configure policy, but never signing authority."""
    owner = fresh_org()
    db = SessionLocal()
    try:
        owner_row = _owner(db, owner)
        operator = User(
            organization_id=None,
            email="policy-platform-operator@example.com",
            password_hash="unused",
            full_name="Policy Platform Operator",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
        )
        db.add(operator)
        db.flush()

        grant = PolicyService(db, owner_row.organization_id).create_grant(
            created_by=operator,
            action="bank_payment.propose",
            effect="allow",
            role=UserRole.MANAGER,
            max_amount=Decimal("2500"),
        )
        db.commit()

        assert grant.organization_id == owner_row.organization_id
        assert grant.created_by_user_id == operator.id
    finally:
        db.close()


def test_two_distinct_current_signers_are_required_when_policy_says_two(fresh_org):
    owner = fresh_org()
    db = SessionLocal()
    try:
        owner_row = _owner(db, owner)
        second = User(
            organization_id=owner_row.organization_id,
            email="policy-second-signer@example.com",
            password_hash="unused",
            full_name="Second Signer",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(second)
        db.flush()
        membership_service.grant(
            db,
            organization_id=owner_row.organization_id,
            user_id=second.id,
            role=UserRole.ADMIN,
            granted_by_user_id=owner_row.id,
        )
        db.add(OrganizationSigningAuthority(
            organization_id=owner_row.organization_id,
            user_id=second.id,
            authority_type="authorized_signer",
            action_types=["payment"],
            is_active=True,
            granted_by_user_id=owner_row.id,
        ))
        PolicyService(db, owner_row.organization_id).create_grant(
            created_by=owner_row,
            action="bank_payment.propose",
            effect="allow",
            role=UserRole.ADMIN,
            required_approvals=2,
        )
        db.commit()

        service = IrreversibleActionService(db, owner_row.organization_id)
        row = service.propose(
            proposed_by=owner_row,
            action_type="payment",
            payload={"amount": "10", "currency": "ILS"},
            idempotency_key="policy-two-signers",
        )
        first = service.approve(row.id, approved_by=owner_row)
        assert first.status == "proposed"
        second_approval = service.approve(row.id, approved_by=second)
        assert second_approval.status == "approved"
        assert service.claim_for_execution(row.id).status == "executing"
    finally:
        db.close()


def test_daily_ceiling_reserves_open_proposals(fresh_org):
    owner = fresh_org()
    db = SessionLocal()
    try:
        owner_row = _owner(db, owner)
        PolicyService(db, owner_row.organization_id).create_grant(
            created_by=owner_row,
            action="bank_payment.propose",
            effect="allow",
            role=UserRole.ADMIN,
            daily_limit_amount=Decimal("100"),
        )
        db.commit()
        service = IrreversibleActionService(db, owner_row.organization_id)
        service.propose(
            proposed_by=owner_row,
            action_type="payment",
            payload={"amount": "60", "currency": "ILS"},
            idempotency_key="policy-reservation-one",
        )
        with pytest.raises(ActionAuthorizationError, match="daily_limit_exceeded"):
            service.propose(
                proposed_by=owner_row,
                action_type="payment",
                payload={"amount": "41", "currency": "ILS"},
                idempotency_key="policy-reservation-two",
            )
    finally:
        db.close()


def test_policy_http_api_is_org_scoped_and_admin_only(client, fresh_org):
    org = fresh_org()
    created = client.post(
        "/api/approvals/policies",
        headers=org["headers"],
        json={
            "action": "invoices.issue",
            "effect": "allow",
            "role": "accountant",
            "max_amount": "2500",
        },
    )
    assert created.status_code == 201, created.text
    grant_id = created.json()["id"]

    listing = client.get("/api/approvals/policies", headers=org["headers"])
    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()["items"]] == [grant_id]

    revoked = client.delete(
        f"/api/approvals/policies/{grant_id}", headers=org["headers"],
    )
    assert revoked.status_code == 200
    assert revoked.json()["is_active"] is False


def test_every_non_office_chat_write_has_a_known_policy_action():
    for tool in TOOLS.values():
        if tool.category == "write" and not tool.office:
            assert tool.policy_action in policy_engine.KNOWN_ACTIONS, tool.name


def test_chat_rechecks_policy_before_atomic_execution_claim(
    monkeypatch, fresh_org,
):
    org = fresh_org()
    db = SessionLocal()
    try:
        owner_row = _owner(db, org)
        message = ChatMessage(
            organization_id=owner_row.organization_id,
            user_id=owner_row.id,
            session_id="policy-chat-recheck",
            role="assistant",
            content="לאשר?",
            pending_action={
                **ai_chat_service._pending_action_envelope(
                    TOOLS["create_expense_category"],
                    {"key": "blocked", "name_he": "חסום"},
                ),
                "policy_amount": None,
            },
            action_status="pending",
        )
        db.add(message)
        PolicyService(db, owner_row.organization_id).create_grant(
            created_by=owner_row,
            action="expenses.manage_categories",
            effect="deny",
            user_id=owner_row.id,
        )
        db.commit()
        db.refresh(message)

        called = {"count": 0}

        async def forbidden(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr(AIChatService, "_execute_tool_observed", forbidden)
        service = AIChatService(db, owner_row.organization_id, owner_row.id)
        with pytest.raises(ChatConfirmationError, match="explicit_deny"):
            asyncio.run(service.confirm_action(message.id))
        db.refresh(message)
        assert message.action_status == "pending"
        assert called["count"] == 0
    finally:
        db.close()
