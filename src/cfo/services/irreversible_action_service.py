"""Durable control plane for actions that can move money or close records.

This service deliberately does not call an external provider.  It persists
the reviewed payload, enforces organization scope and idempotency, and exposes
an atomic execution claim.  A provider adapter must then record acceptance and
independent readback as two separate transitions.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..models import (
    IrreversibleActionApproval,
    IrreversibleActionRequest,
    OrganizationSigningAuthority,
    User,
    UserRole,
)
from . import membership_service
from .policy_service import PolicyService


SUPPORTED_ACTION_TYPES = frozenset({
    "payment",
    "refund",
    "mandate",
    "recurring_cancel",
    "document_issue",
    "sumit_writeback",
    "filing_submission",
    "period_close",
})


class ActionWorkflowError(ValueError):
    """Base error for a refused action-workflow transition."""


class ActionValidationError(ActionWorkflowError):
    """The proposal itself is not a supported, stable action."""


class ActionAuthorizationError(ActionWorkflowError):
    """The actor is not permitted to perform the transition."""


class ActionConflictError(ActionWorkflowError):
    """An idempotency key was reused for different immutable content."""


class ActionStateError(ActionWorkflowError):
    """The requested state transition is invalid or the row is not visible."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if not isinstance(payload, dict) or not payload:
        raise ActionValidationError("payload must be a non-empty object")
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ActionValidationError("payload must be JSON serializable") from exc
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return json.loads(encoded), digest


class IrreversibleActionService:
    """Organization-bound lifecycle manager for irreversible actions."""

    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.organization_id = organization_id

    def _actor_in_scope(self, actor: User) -> bool:
        if actor.role == UserRole.SUPER_ADMIN:
            return True
        return membership_service.is_member(
            self.db, actor.id, self.organization_id,
        )

    def _require_actor_scope(self, actor: User) -> None:
        if not actor.is_active or not self._actor_in_scope(actor):
            raise ActionAuthorizationError(
                "actor is not active in this organization",
            )

    def _query(self):
        return self.db.query(IrreversibleActionRequest).filter(
            IrreversibleActionRequest.organization_id == self.organization_id,
        )

    @staticmethod
    def _decision_evidence(decision) -> dict[str, Any]:
        evidence = decision.to_audit()
        evidence["evaluated_at"] = _utc_now().isoformat()
        return evidence

    @staticmethod
    def _require_policy_allowed(decision) -> None:
        if not decision.allowed:
            raise ActionAuthorizationError(
                f"organization policy refused action: {decision.reason}",
            )

    def get(self, request_id: int) -> IrreversibleActionRequest | None:
        return self._query().filter(
            IrreversibleActionRequest.id == request_id,
        ).first()

    def list(self, *, status: str | None = None) -> list[IrreversibleActionRequest]:
        query = self._query()
        if status is not None:
            query = query.filter(IrreversibleActionRequest.status == status)
        return query.order_by(IrreversibleActionRequest.id.desc()).all()

    def require_signing_approver(
        self,
        *,
        proposed_by_user_id: int,
        approved_by: User,
        action_type: str,
        require_distinct: bool,
    ) -> OrganizationSigningAuthority:
        """Resolve current organization signing authority for an approval.

        Moshko's IRREVERSIBLE policy class always passes require_distinct=True.
        The durable request workflow also reuses this method and may demand
        separation through a persisted organization policy grant. Keeping the
        lookup here prevents chat from growing a parallel authority model.
        """
        self._require_actor_scope(approved_by)
        if require_distinct and approved_by.id == proposed_by_user_id:
            raise ActionAuthorizationError(
                "an irreversible action requires a distinct signing approver",
            )
        authorities = self.db.query(OrganizationSigningAuthority).filter(
            OrganizationSigningAuthority.organization_id == self.organization_id,
            OrganizationSigningAuthority.user_id == approved_by.id,
            OrganizationSigningAuthority.is_active.is_(True),
        ).all()
        authority = next(
            (
                candidate for candidate in authorities
                if "*" in (candidate.action_types or [])
                or action_type in (candidate.action_types or [])
            ),
            None,
        )
        if authority is None:
            raise ActionAuthorizationError(
                "active signing authority for this action is required",
            )
        return authority

    def propose(
        self,
        *,
        proposed_by: User,
        action_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        description: str | None = None,
        channel: str = "internal",
    ) -> IrreversibleActionRequest:
        self._require_actor_scope(proposed_by)
        if action_type not in SUPPORTED_ACTION_TYPES:
            raise ActionValidationError(f"unsupported action_type: {action_type}")
        if not idempotency_key or len(idempotency_key) > 160:
            raise ActionValidationError(
                "idempotency_key must contain 1-160 characters",
            )

        canonical_payload, payload_sha256 = _canonical_payload(payload)
        existing = self._query().filter(
            IrreversibleActionRequest.idempotency_key == idempotency_key,
        ).first()
        if existing is not None:
            if (
                existing.action_type != action_type
                or existing.payload_sha256 != payload_sha256
            ):
                raise ActionConflictError(
                    "idempotency key already exists with a different action or payload",
                )
            return existing

        decision = PolicyService(
            self.db, self.organization_id,
        ).evaluate_irreversible(
            user=proposed_by,
            action_type=action_type,
            payload=canonical_payload,
            channel=channel,
        )
        self._require_policy_allowed(decision)
        if decision.requires_reason and not (description or "").strip():
            raise ActionAuthorizationError(
                "organization policy requires a proposal reason",
            )

        row = IrreversibleActionRequest(
            organization_id=self.organization_id,
            action_type=action_type,
            description=description,
            payload=canonical_payload,
            payload_sha256=payload_sha256,
            idempotency_key=idempotency_key,
            origin_channel=channel,
            status="proposed",
            proposed_by_user_id=proposed_by.id,
            policy_proposed_decision=self._decision_evidence(decision),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def approve(
        self,
        request_id: int,
        *,
        approved_by: User,
    ) -> IrreversibleActionRequest:
        self._require_actor_scope(approved_by)

        row = self.get(request_id)
        if row is None:
            raise ActionStateError(f"action request {request_id} not found")
        if row.status != "proposed":
            raise ActionStateError("only a proposed action can be approved")
        proposer = self.db.get(User, row.proposed_by_user_id)
        if proposer is None:
            raise ActionAuthorizationError("proposal author no longer exists")
        decision = PolicyService(
            self.db, self.organization_id,
        ).evaluate_irreversible(
            user=proposer,
            action_type=row.action_type,
            payload=row.payload,
            channel=row.origin_channel,
            exclude_request_id=row.id,
        )
        self._require_policy_allowed(decision)
        if decision.requires_step_up:
            raise ActionAuthorizationError(
                "organization policy requires step-up authentication",
            )
        authority = self.require_signing_approver(
            proposed_by_user_id=row.proposed_by_user_id,
            approved_by=approved_by,
            action_type=row.action_type,
            require_distinct=decision.separation_of_duties,
        )

        approval = self.db.query(IrreversibleActionApproval).filter(
            IrreversibleActionApproval.request_id == row.id,
            IrreversibleActionApproval.approved_by_user_id == approved_by.id,
        ).first()
        if approval is None:
            self.db.add(IrreversibleActionApproval(
                organization_id=self.organization_id,
                request_id=row.id,
                approved_by_user_id=approved_by.id,
                authority_id=authority.id,
                authority_type=authority.authority_type,
                policy_decision=self._decision_evidence(decision),
            ))
            self.db.flush()

        approval_count = self.db.query(IrreversibleActionApproval).filter(
            IrreversibleActionApproval.organization_id == self.organization_id,
            IrreversibleActionApproval.request_id == row.id,
        ).count()
        row.policy_approved_decision = self._decision_evidence(decision)
        if approval_count >= decision.required_approvals:
            row.status = "approved"
            row.approved_by_user_id = approved_by.id
            row.approver_role = (
                membership_service.role_in(
                    self.db, approved_by.id, self.organization_id,
                ) or approved_by.role
            ).value
            row.approved_by_authority_id = authority.id
            row.approver_authority_type = authority.authority_type
            row.approved_at = _utc_now()
        self.db.commit()
        self.db.refresh(row)
        return row

    def reject(
        self,
        request_id: int,
        *,
        rejected_by: User,
        reason: str | None = None,
    ) -> IrreversibleActionRequest:
        self._require_actor_scope(rejected_by)

        row = self.get(request_id)
        if row is None:
            raise ActionStateError(f"action request {request_id} not found")
        if row.status != "proposed":
            raise ActionStateError("only a proposed action can be rejected")
        authority = self.db.query(OrganizationSigningAuthority).filter(
            OrganizationSigningAuthority.organization_id
            == self.organization_id,
            OrganizationSigningAuthority.user_id == rejected_by.id,
            OrganizationSigningAuthority.is_active.is_(True),
        ).all()
        authority = next(
            (
                candidate for candidate in authority
                if "*" in (candidate.action_types or [])
                or row.action_type in (candidate.action_types or [])
            ),
            None,
        )
        if authority is None:
            raise ActionAuthorizationError(
                "active signing authority for this action is required",
            )

        row.status = "rejected"
        row.approved_by_user_id = rejected_by.id
        row.approver_role = rejected_by.role.value
        row.approved_by_authority_id = authority.id
        row.approver_authority_type = authority.authority_type
        row.rejected_at = _utc_now()
        row.error = reason
        self.db.commit()
        self.db.refresh(row)
        return row

    def claim_for_execution(
        self,
        request_id: int,
    ) -> IrreversibleActionRequest:
        """Atomically move one approved request to executing.

        The conditional UPDATE is the execute-once lock. Concurrent workers
        cannot both observe and claim the same approved row.
        """
        row = self.get(request_id)
        if row is None:
            raise ActionStateError(f"action request {request_id} not found")
        if row.status != "approved":
            raise ActionStateError(
                f"action must be approved before execution; current status is {row.status}",
            )
        proposer = self.db.get(User, row.proposed_by_user_id)
        if proposer is None:
            raise ActionAuthorizationError("proposal author no longer exists")
        decision = PolicyService(
            self.db, self.organization_id,
        ).evaluate_irreversible(
            user=proposer,
            action_type=row.action_type,
            payload=row.payload,
            channel=row.origin_channel,
            exclude_request_id=row.id,
        )
        self._require_policy_allowed(decision)

        approvals = self.db.query(IrreversibleActionApproval).filter(
            IrreversibleActionApproval.organization_id == self.organization_id,
            IrreversibleActionApproval.request_id == row.id,
        ).all()
        valid_approvers: set[int] = set()
        for approval in approvals:
            authority = self.db.get(OrganizationSigningAuthority, approval.authority_id)
            approver = self.db.get(User, approval.approved_by_user_id)
            if (
                authority is not None
                and authority.is_active
                and authority.organization_id == self.organization_id
                and approver is not None
                and self._actor_in_scope(approver)
                and ("*" in (authority.action_types or [])
                     or row.action_type in (authority.action_types or []))
            ):
                valid_approvers.add(approval.approved_by_user_id)
        if len(valid_approvers) < decision.required_approvals:
            raise ActionAuthorizationError(
                "active signing approvals no longer satisfy organization policy",
            )

        evidence = self._decision_evidence(decision)
        evidence["valid_signing_approvals"] = len(valid_approvers)
        row.policy_execution_decision = evidence
        self.db.flush()
        claimed = self._query().filter(
            IrreversibleActionRequest.id == request_id,
            IrreversibleActionRequest.status == "approved",
        ).update(
            {
                IrreversibleActionRequest.status: "executing",
                IrreversibleActionRequest.execution_started_at: _utc_now(),
            },
            synchronize_session=False,
        )
        if claimed != 1:
            self.db.rollback()
            row = self.get(request_id)
            raise ActionStateError(
                f"action must be approved before execution; current status is {row.status}",
            )
        self.db.commit()
        return self.get(request_id)

    def claim_approved_for_execution(
        self,
        request_id: int,
        *,
        action_type: str,
        submitted_payload: dict[str, Any],
    ) -> IrreversibleActionRequest:
        """Validate immutable intent, then atomically claim the approved row."""
        self.validate_approved_intent(
            request_id,
            action_type=action_type,
            submitted_payload=submitted_payload,
        )
        return self.claim_for_execution(request_id)

    def validate_approved_intent(
        self,
        request_id: int,
        *,
        action_type: str,
        submitted_payload: dict[str, Any],
    ) -> IrreversibleActionRequest:
        """Validate type, exact payload and state without claiming execution."""
        row = self.get(request_id)
        if row is None:
            raise ActionStateError(f"action request {request_id} not found")
        if row.action_type != action_type:
            raise ActionConflictError(
                f"approval is for {row.action_type}, not {action_type}",
            )
        _, submitted_sha256 = _canonical_payload(submitted_payload)
        if submitted_sha256 != row.payload_sha256:
            raise ActionConflictError(
                "submitted payload differs from the approved payload",
            )
        if row.status != "approved":
            raise ActionStateError(
                "action must be approved before execution; "
                f"current status is {row.status}",
            )
        proposer = self.db.get(User, row.proposed_by_user_id)
        if proposer is None:
            raise ActionAuthorizationError("proposal author no longer exists")
        decision = PolicyService(
            self.db, self.organization_id,
        ).evaluate_irreversible(
            user=proposer,
            action_type=row.action_type,
            payload=row.payload,
            channel=row.origin_channel,
            exclude_request_id=row.id,
        )
        self._require_policy_allowed(decision)
        return row

    def mark_executed(
        self,
        request_id: int,
        *,
        provider_reference: str,
        execution_result: dict[str, Any],
    ) -> IrreversibleActionRequest:
        row = self.get(request_id)
        if row is None:
            raise ActionStateError(f"action request {request_id} not found")
        if row.status != "executing":
            raise ActionStateError("only an executing action can be marked executed")
        if not provider_reference:
            raise ActionValidationError("provider_reference is required")

        row.status = "executed"
        row.provider_reference = provider_reference
        row.execution_result = execution_result
        row.executed_at = _utc_now()
        self.db.commit()
        self.db.refresh(row)
        return row

    def mark_verified(
        self,
        request_id: int,
        *,
        verification_evidence: dict[str, Any],
    ) -> IrreversibleActionRequest:
        row = self.get(request_id)
        if row is None:
            raise ActionStateError(f"action request {request_id} not found")
        if row.status != "executed":
            raise ActionStateError("only an executed action can be verified")
        if not verification_evidence:
            raise ActionValidationError("verification evidence is required")

        row.status = "verified"
        row.verification_evidence = verification_evidence
        row.verified_at = _utc_now()
        self.db.commit()
        self.db.refresh(row)
        return row

    def mark_failed(
        self,
        request_id: int,
        *,
        error: str,
    ) -> IrreversibleActionRequest:
        row = self.get(request_id)
        if row is None:
            raise ActionStateError(f"action request {request_id} not found")
        if row.status == "executing":
            row.status = "failed"
        elif row.status == "executed":
            row.status = "verification_failed"
        else:
            raise ActionStateError(
                "only an executing or executed action can be marked failed",
            )
        row.error = error
        self.db.commit()
        self.db.refresh(row)
        return row
