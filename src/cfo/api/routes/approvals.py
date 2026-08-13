"""Review API for durable irreversible-action proposals.

Execution is intentionally not exposed as a generic HTTP route. Provider
adapters must claim an approved request internally and then persist provider
acceptance and independent readback through IrreversibleActionService.
"""
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...database import get_db_session
from ...models import (
    IrreversibleActionRequest,
    OrganizationSigningAuthority,
    PolicyGrant,
    User,
    UserRole,
)
from ...services.irreversible_action_service import (
    ActionAuthorizationError,
    ActionConflictError,
    ActionStateError,
    ActionValidationError,
    IrreversibleActionService,
)
from ...services.signing_authority_service import SigningAuthorityService
from ...services.policy_service import PolicyService
from ..dependencies import (
    OrganizationAccessContext,
    get_access_context,
    get_current_org_id,
    get_current_user,
)


router = APIRouter(prefix="/approvals", tags=["Irreversible Action Approvals"])


class ActionProposalBody(BaseModel):
    action_type: str
    payload: dict[str, Any]
    idempotency_key: str = Field(min_length=1, max_length=160)
    description: str | None = None


class ActionRejectionBody(BaseModel):
    reason: str | None = None


class SigningAuthorityBody(BaseModel):
    user_id: int
    authority_type: str
    action_types: list[str]


class OwnerBootstrapBody(BaseModel):
    confirmation: str


class PolicyGrantBody(BaseModel):
    action: str
    effect: str
    role: UserRole | None = None
    user_id: int | None = None
    max_amount: Decimal | None = None
    daily_limit_amount: Decimal | None = None
    monthly_limit_amount: Decimal | None = None
    currency: str = Field(default="ILS", min_length=3, max_length=3)
    allowed_bank_accounts: list[str] | None = None
    allowed_counterparties: list[int] | None = None
    allowed_document_types: list[str] | None = None
    allowed_channels: list[str] | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    requires_step_up: bool = False
    required_approvals: int = Field(default=1, ge=1)
    separation_of_duties: bool = False
    requires_reason: bool = False


def _serialize(row: IrreversibleActionRequest) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "action_type": row.action_type,
        "description": row.description,
        "payload": row.payload,
        "payload_sha256": row.payload_sha256,
        "idempotency_key": row.idempotency_key,
        "origin_channel": row.origin_channel,
        "status": row.status,
        "proposed_by_user_id": row.proposed_by_user_id,
        "approved_by_user_id": row.approved_by_user_id,
        "approver_role": row.approver_role,
        "approved_by_authority_id": row.approved_by_authority_id,
        "approver_authority_type": row.approver_authority_type,
        "provider_reference": row.provider_reference,
        "proposed_at": row.proposed_at,
        "approved_at": row.approved_at,
        "rejected_at": row.rejected_at,
        "execution_started_at": row.execution_started_at,
        "executed_at": row.executed_at,
        "verified_at": row.verified_at,
        "policy_proposed_decision": row.policy_proposed_decision,
        "policy_approved_decision": row.policy_approved_decision,
        "policy_execution_decision": row.policy_execution_decision,
    }


def _serialize_authority(
    row: OrganizationSigningAuthority,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "user_id": row.user_id,
        "authority_type": row.authority_type,
        "action_types": row.action_types,
        "is_active": row.is_active,
        "granted_by_user_id": row.granted_by_user_id,
        "revoked_by_user_id": row.revoked_by_user_id,
        "created_at": row.created_at,
        "revoked_at": row.revoked_at,
    }


def _serialize_policy(row: PolicyGrant) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "action": row.action,
        "effect": row.effect,
        "role": row.role.value if row.role else None,
        "user_id": row.user_id,
        "max_amount": row.max_amount,
        "daily_limit_amount": row.daily_limit_amount,
        "monthly_limit_amount": row.monthly_limit_amount,
        "currency": row.currency,
        "allowed_bank_accounts": row.allowed_bank_accounts,
        "allowed_counterparties": row.allowed_counterparties,
        "allowed_document_types": row.allowed_document_types,
        "allowed_channels": row.allowed_channels,
        "valid_from": row.valid_from,
        "valid_until": row.valid_until,
        "requires_step_up": row.requires_step_up,
        "required_approvals": row.required_approvals,
        "separation_of_duties": row.separation_of_duties,
        "requires_reason": row.requires_reason,
        "is_active": row.is_active,
        "created_by_user_id": row.created_by_user_id,
        "revoked_by_user_id": row.revoked_by_user_id,
        "created_at": row.created_at,
        "revoked_at": row.revoked_at,
    }


def _raise_workflow_error(exc: ValueError) -> None:
    if isinstance(exc, ActionAuthorizationError):
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    if isinstance(exc, (ActionConflictError, ActionStateError)):
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if isinstance(exc, ActionValidationError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    raise exc


@router.post("", status_code=status.HTTP_201_CREATED)
def propose_action(
    body: ActionProposalBody,
    ctx: OrganizationAccessContext = Depends(get_access_context),
    db: Session = Depends(get_db_session),
):
    service = IrreversibleActionService(db, ctx.organization_id)
    try:
        row = service.propose(
            proposed_by=ctx.user,
            action_type=body.action_type,
            payload=body.payload,
            idempotency_key=body.idempotency_key,
            description=body.description,
            channel=ctx.channel,
        )
    except ValueError as exc:
        _raise_workflow_error(exc)
    return _serialize(row)


@router.get("")
def list_actions(
    workflow_status: str | None = Query(None, alias="status"),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    rows = IrreversibleActionService(db, org_id).list(status=workflow_status)
    return {"items": [_serialize(row) for row in rows]}


@router.get("/signing-authorities")
def list_signing_authorities(
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    rows = SigningAuthorityService(db, org_id).list()
    return {"items": [_serialize_authority(row) for row in rows]}


@router.post("/signing-authorities", status_code=status.HTTP_201_CREATED)
def grant_signing_authority(
    body: SigningAuthorityBody,
    org_id: int = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    try:
        row = SigningAuthorityService(db, org_id).grant(
            granted_by=user,
            user_id=body.user_id,
            authority_type=body.authority_type,
            action_types=body.action_types,
        )
    except ValueError as exc:
        _raise_workflow_error(exc)
    return _serialize_authority(row)


@router.post(
    "/signing-authorities/bootstrap",
    status_code=status.HTTP_201_CREATED,
)
def bootstrap_owner_authority(
    body: OwnerBootstrapBody,
    org_id: int = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    try:
        row = SigningAuthorityService(db, org_id).bootstrap_owner(
            user=user,
            confirmation=body.confirmation,
        )
    except ValueError as exc:
        _raise_workflow_error(exc)
    return _serialize_authority(row)


@router.delete("/signing-authorities/{authority_id}")
def revoke_signing_authority(
    authority_id: int,
    org_id: int = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    try:
        row = SigningAuthorityService(db, org_id).revoke(
            authority_id,
            revoked_by=user,
        )
    except ValueError as exc:
        _raise_workflow_error(exc)
    return _serialize_authority(row)


@router.get("/policies")
def list_policy_grants(
    include_inactive: bool = False,
    ctx: OrganizationAccessContext = Depends(get_access_context),
    db: Session = Depends(get_db_session),
):
    if ctx.effective_role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "organization admin required")
    rows = PolicyService(db, ctx.organization_id).list_grants(
        include_inactive=include_inactive,
    )
    return {"items": [_serialize_policy(row) for row in rows]}


@router.post("/policies", status_code=status.HTTP_201_CREATED)
def create_policy_grant(
    body: PolicyGrantBody,
    ctx: OrganizationAccessContext = Depends(get_access_context),
    db: Session = Depends(get_db_session),
):
    try:
        row = PolicyService(db, ctx.organization_id).create_grant(
            created_by=ctx.user,
            **body.model_dump(),
        )
        db.commit()
        db.refresh(row)
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _serialize_policy(row)


@router.delete("/policies/{grant_id}")
def revoke_policy_grant(
    grant_id: int,
    ctx: OrganizationAccessContext = Depends(get_access_context),
    db: Session = Depends(get_db_session),
):
    try:
        row = PolicyService(db, ctx.organization_id).revoke_grant(
            grant_id, revoked_by=ctx.user,
        )
        db.commit()
        db.refresh(row)
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _serialize_policy(row)


@router.get("/{request_id}")
def get_action(
    request_id: int,
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    row = IrreversibleActionService(db, org_id).get(request_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Action request not found")
    return _serialize(row)


@router.post("/{request_id}/approve")
def approve_action(
    request_id: int,
    ctx: OrganizationAccessContext = Depends(get_access_context),
    db: Session = Depends(get_db_session),
):
    try:
        row = IrreversibleActionService(db, ctx.organization_id).approve(
            request_id,
            approved_by=ctx.user,
        )
    except ValueError as exc:
        _raise_workflow_error(exc)
    return _serialize(row)


@router.post("/{request_id}/reject")
def reject_action(
    request_id: int,
    body: ActionRejectionBody,
    ctx: OrganizationAccessContext = Depends(get_access_context),
    db: Session = Depends(get_db_session),
):
    try:
        row = IrreversibleActionService(db, ctx.organization_id).reject(
            request_id,
            rejected_by=ctx.user,
            reason=body.reason,
        )
    except ValueError as exc:
        _raise_workflow_error(exc)
    return _serialize(row)
