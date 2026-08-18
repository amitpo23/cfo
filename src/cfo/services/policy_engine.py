"""Pure organization policy evaluation for financial and operational actions.

RBAC answers whether a role may generally do something.  This layer adds the
money-specific boundaries: amount and period ceilings, allowed accounts and
counterparties, channels, validity windows, separation of duties and explicit
denies.  It is deliberately free of database or provider access so callers can
re-evaluate the same immutable action at proposal, approval and execution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

from ..models import UserRole


ALLOW = "allow"
DENY = "deny"

SIGNING_ACTIONS = frozenset({
    "bank_payment.approve", "bank_payment.execute",
    "mandate.create", "mandate.cancel", "recurring.charge",
    "refund.approve", "filing.approve", "period_close.approve",
})

READ_ACTIONS = frozenset({
    "financial.read", "reports.read", "bank.read",
    "collections.read", "mandate.read",
})

WRITE_ACTIONS = frozenset({
    "invoices.draft", "invoices.issue", "invoices.credit",
    "expenses.review", "expenses.file",
    "reconciliation.propose", "reconciliation.approve",
    "collections.contact", "collections.escalate",
    "payment_link.create", "bank_payment.propose",
    "bank_connection.create",
    "mandate.propose", "recurring_cancel.propose",
    "refund.propose", "filing.prepare", "period_close.propose",
    "accounting.writeback.propose", "expenses.manage_categories", "expenses.manage_vehicle_profile",
    "expenses.classify", "reports.email", "moshko.memory.write",
    "tasks.write", "users.manage", "policies.manage",
})

KNOWN_ACTIONS = READ_ACTIONS | WRITE_ACTIONS | SIGNING_ACTIONS

ROLE_PRESETS: dict[UserRole, frozenset[str]] = {
    UserRole.ADMIN: frozenset({
        "financial.read", "reports.read", "bank.read",
        "invoices.draft", "invoices.issue", "invoices.credit",
        "expenses.review", "expenses.file",
        "reconciliation.propose", "reconciliation.approve",
        "collections.read", "collections.contact", "collections.escalate",
        "payment_link.create", "bank_payment.propose", "mandate.propose",
        "bank_connection.create",
        "recurring_cancel.propose", "mandate.read", "refund.propose",
        "filing.prepare", "period_close.propose",
        "accounting.writeback.propose", "expenses.manage_categories", "expenses.manage_vehicle_profile",
        "expenses.classify", "reports.email", "moshko.memory.write",
        "tasks.write", "users.manage", "policies.manage",
    }),
    UserRole.ACCOUNTANT: frozenset({
        "financial.read", "reports.read", "bank.read",
        "invoices.draft", "invoices.issue", "invoices.credit",
        "expenses.review", "expenses.file", "reconciliation.propose",
        "reconciliation.approve", "collections.read", "payment_link.create",
        "bank_payment.propose", "mandate.propose", "recurring_cancel.propose",
        "mandate.read", "refund.propose", "filing.prepare",
        "accounting.writeback.propose",
        "expenses.manage_categories", "expenses.manage_vehicle_profile", "expenses.classify", "reports.email",
        "moshko.memory.write", "tasks.write",
    }),
    UserRole.MANAGER: frozenset({
        "financial.read", "reports.read", "bank.read", "invoices.draft",
        "expenses.review", "reconciliation.propose", "collections.read",
        "collections.contact", "payment_link.create", "bank_payment.propose",
        "mandate.propose", "recurring_cancel.propose", "mandate.read",
        "bank_connection.create", "reports.email", "moshko.memory.write",
        "tasks.write",
    }),
    UserRole.USER: frozenset({"expenses.review", "moshko.memory.write", "tasks.write"}),
    UserRole.VIEWER: frozenset({
        "financial.read", "reports.read", "bank.read",
        "collections.read", "mandate.read",
    }),
}


@dataclass(frozen=True)
class Grant:
    action: str
    effect: str = ALLOW
    organization_id: Optional[int] = None
    role: Optional[UserRole] = None
    user_id: Optional[int] = None
    max_amount: Optional[Decimal] = None
    daily_limit_amount: Optional[Decimal] = None
    monthly_limit_amount: Optional[Decimal] = None
    currency: str = "ILS"
    allowed_bank_accounts: Optional[Sequence[str]] = None
    allowed_counterparties: Optional[Sequence[int]] = None
    allowed_document_types: Optional[Sequence[str]] = None
    allowed_channels: Optional[Sequence[str]] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    requires_step_up: bool = False
    required_approvals: int = 1
    separation_of_duties: bool = False
    requires_reason: bool = False


@dataclass(frozen=True)
class Decision:
    action: str
    allowed: bool
    reason: str
    requires_signing_authority: bool = False
    requires_step_up: bool = False
    requires_reason: bool = False
    required_approvals: int = 1
    separation_of_duties: bool = False
    matched: tuple[str, ...] = field(default_factory=tuple)

    def to_audit(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "allowed": self.allowed,
            "reason": self.reason,
            "requires_signing_authority": self.requires_signing_authority,
            "requires_step_up": self.requires_step_up,
            "requires_reason": self.requires_reason,
            "required_approvals": self.required_approvals,
            "separation_of_duties": self.separation_of_duties,
            "matched": list(self.matched),
        }


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _in_window(grant: Grant, at: datetime) -> bool:
    start, end = _aware(grant.valid_from), _aware(grant.valid_until)
    return not ((start is not None and at < start) or (end is not None and at >= end))


def _applies_to(
    grant: Grant, *, role: UserRole, user_id: int, organization_id: int,
) -> bool:
    if grant.organization_id is not None and grant.organization_id != organization_id:
        return False
    if grant.user_id is not None:
        return grant.user_id == user_id
    return grant.role == role if grant.role is not None else False


def _deny(action: str, reason: str, **kwargs: Any) -> Decision:
    return Decision(action=action, allowed=False, reason=reason, **kwargs)


def evaluate(
    *,
    grants: Sequence[Grant],
    organization_id: int,
    user_id: int,
    role: UserRole,
    action: str,
    amount: Optional[Decimal] = None,
    currency: str = "ILS",
    spent_today: Optional[Decimal] = None,
    spent_this_month: Optional[Decimal] = None,
    bank_account: Optional[str] = None,
    counterparty_id: Optional[int] = None,
    document_type: Optional[str] = None,
    channel: Optional[str] = None,
    proposed_by_user_id: Optional[int] = None,
    at: Optional[datetime] = None,
) -> Decision:
    at = at or datetime.now(timezone.utc)
    if action not in KNOWN_ACTIONS:
        return _deny(action, "unknown_action")
    if amount is not None and amount <= 0:
        return _deny(action, "amount_not_positive")

    relevant = [
        grant for grant in grants
        if grant.action == action
        and _applies_to(
            grant, role=role, user_id=user_id, organization_id=organization_id,
        )
        and _in_window(grant, at)
    ]
    if any(grant.effect == DENY for grant in relevant):
        return _deny(action, "explicit_deny", matched=("deny",))
    if action in SIGNING_ACTIONS:
        return _deny(
            action, "requires_signing_authority", requires_signing_authority=True,
        )

    allows = [grant for grant in relevant if grant.effect == ALLOW]
    preset_allows = action in ROLE_PRESETS.get(role, frozenset())
    if not allows and not preset_allows:
        return _deny(action, "no_policy_grants_this_action")

    step_up = False
    needs_reason = False
    approvals = 1
    separation = False
    for grant in allows:
        if grant.separation_of_duties and proposed_by_user_id == user_id:
            return _deny(action, "self_approval_forbidden")
        separation = separation or grant.separation_of_duties
        has_money_limit = any(value is not None for value in (
            grant.max_amount, grant.daily_limit_amount, grant.monthly_limit_amount,
        ))
        if has_money_limit:
            if amount is None:
                return _deny(action, "amount_required_by_policy")
            if currency != grant.currency:
                return _deny(action, "currency_mismatch")
        if grant.max_amount is not None and amount > grant.max_amount:
            return _deny(action, "amount_exceeds_ceiling")
        if grant.daily_limit_amount is not None:
            if spent_today is None:
                return _deny(action, "daily_spend_unknown")
            if spent_today + amount > grant.daily_limit_amount:
                return _deny(action, "daily_limit_exceeded")
        if grant.monthly_limit_amount is not None:
            if spent_this_month is None:
                return _deny(action, "monthly_spend_unknown")
            if spent_this_month + amount > grant.monthly_limit_amount:
                return _deny(action, "monthly_limit_exceeded")
        if grant.allowed_bank_accounts is not None and (
            bank_account is None or bank_account not in grant.allowed_bank_accounts
        ):
            return _deny(action, "bank_account_not_allowed")
        if grant.allowed_counterparties is not None and (
            counterparty_id is None or counterparty_id not in grant.allowed_counterparties
        ):
            return _deny(action, "counterparty_not_allowed")
        if grant.allowed_document_types is not None and (
            document_type is None or document_type not in grant.allowed_document_types
        ):
            return _deny(action, "document_type_not_allowed")
        if grant.allowed_channels is not None and (
            channel is None or channel not in grant.allowed_channels
        ):
            return _deny(action, "channel_not_allowed")
        step_up = step_up or grant.requires_step_up
        needs_reason = needs_reason or grant.requires_reason
        approvals = max(approvals, grant.required_approvals)

    return Decision(
        action=action,
        allowed=True,
        reason="granted_by_policy" if allows else "granted_by_role_preset",
        requires_step_up=step_up,
        requires_reason=needs_reason,
        required_approvals=approvals,
        separation_of_duties=separation,
        matched=("grant",) if allows else ("preset",),
    )
