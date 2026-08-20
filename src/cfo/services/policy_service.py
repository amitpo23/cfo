"""Persistence, audit and current-context evaluation for organization policy."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import (
    AuditLog,
    ChatMessage,
    Expense,
    IrreversibleActionRequest,
    Invoice,
    PolicyGrant,
    User,
    UserRole,
)
from . import membership_service, policy_engine


ACTION_TYPE_TO_POLICY_ACTION = {
    "payment": "bank_payment.propose",
    "refund": "refund.propose",
    "mandate": "mandate.propose",
    "recurring_cancel": "recurring_cancel.propose",
    "document_issue": "invoices.issue",
    "sumit_writeback": "accounting.writeback.propose",
    "filing_submission": "filing.prepare",
    "period_close": "period_close.propose",
}

RESERVED_STATUSES = frozenset({
    "proposed", "approved", "executing", "executed", "verified",
    # A provider error after claim is ambiguous and therefore remains reserved.
    "failed", "verification_failed",
})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _payload_context(payload: dict[str, Any]) -> dict[str, Any]:
    amount = next(
        (_decimal(payload.get(key)) for key in ("amount", "amount_ils", "total_amount")
         if payload.get(key) is not None),
        None,
    )
    bank_account = next(
        (str(payload[key]) for key in (
            "bank_account", "bank_account_id", "from_account_id", "account_id",
        ) if payload.get(key) is not None),
        None,
    )
    counterparty = next(
        (payload[key] for key in ("counterparty_id", "supplier_id", "customer_id", "contact_id")
         if payload.get(key) is not None),
        None,
    )
    try:
        counterparty_id = int(counterparty) if counterparty is not None else None
    except (TypeError, ValueError):
        counterparty_id = None
    return {
        "amount": amount,
        "currency": str(payload.get("currency") or "ILS").upper(),
        "bank_account": bank_account,
        "counterparty_id": counterparty_id,
        "document_type": payload.get("document_type"),
    }


class PolicyService:
    """Organization-bound policy repository and evaluator."""

    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.organization_id = organization_id

    def _query(self):
        return self.db.query(PolicyGrant).filter(
            PolicyGrant.organization_id == self.organization_id,
        )

    def _effective_role(self, user: User) -> Optional[UserRole]:
        if not user.is_active:
            return None
        if user.role == UserRole.SUPER_ADMIN:
            return UserRole.SUPER_ADMIN
        return membership_service.role_in(self.db, user.id, self.organization_id)

    def _require_policy_admin(self, user: User) -> None:
        if self._effective_role(user) not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
            raise PermissionError("organization admin is required to manage policies")

    def list_grants(self, *, include_inactive: bool = False) -> list[PolicyGrant]:
        query = self._query()
        if not include_inactive:
            query = query.filter(PolicyGrant.is_active.is_(True))
        return query.order_by(PolicyGrant.id.desc()).all()

    def create_grant(
        self,
        *,
        created_by: User,
        action: str,
        effect: str,
        role: UserRole | None = None,
        user_id: int | None = None,
        max_amount: Decimal | None = None,
        daily_limit_amount: Decimal | None = None,
        monthly_limit_amount: Decimal | None = None,
        currency: str = "ILS",
        allowed_bank_accounts: list[str] | None = None,
        allowed_counterparties: list[int] | None = None,
        allowed_document_types: list[str] | None = None,
        allowed_channels: list[str] | None = None,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        requires_step_up: bool = False,
        required_approvals: int = 1,
        separation_of_duties: bool = False,
        requires_reason: bool = False,
    ) -> PolicyGrant:
        self._require_policy_admin(created_by)
        if action not in policy_engine.KNOWN_ACTIONS:
            raise ValueError("unknown policy action")
        if action in policy_engine.SIGNING_ACTIONS:
            raise ValueError("signing authority cannot be granted by policy")
        if effect not in (policy_engine.ALLOW, policy_engine.DENY):
            raise ValueError("effect must be allow or deny")
        if (role is None) == (user_id is None):
            raise ValueError("exactly one of role or user_id is required")
        if role == UserRole.SUPER_ADMIN:
            raise ValueError("SUPER_ADMIN is not an organization policy subject")
        if user_id is not None and not membership_service.is_member(
            self.db, user_id, self.organization_id,
        ):
            raise ValueError("policy user must be an active organization member")
        if valid_from and valid_until and valid_until <= valid_from:
            raise ValueError("valid_until must be after valid_from")
        if required_approvals < 1:
            raise ValueError("required_approvals must be at least 1")
        for value in (max_amount, daily_limit_amount, monthly_limit_amount):
            if value is not None and value <= 0:
                raise ValueError("policy amount limits must be positive")

        row = PolicyGrant(
            organization_id=self.organization_id,
            action=action,
            effect=effect,
            role=role,
            user_id=user_id,
            max_amount=max_amount,
            daily_limit_amount=daily_limit_amount,
            monthly_limit_amount=monthly_limit_amount,
            currency=currency.upper(),
            allowed_bank_accounts=allowed_bank_accounts,
            allowed_counterparties=allowed_counterparties,
            allowed_document_types=allowed_document_types,
            allowed_channels=allowed_channels,
            valid_from=valid_from,
            valid_until=valid_until,
            requires_step_up=requires_step_up,
            required_approvals=required_approvals,
            separation_of_duties=separation_of_duties,
            requires_reason=requires_reason,
            is_active=True,
            created_by_user_id=created_by.id,
        )
        self.db.add(row)
        self.db.flush()
        self.db.add(AuditLog(
            user_id=created_by.id,
            organization_id=self.organization_id,
            action="POLICY_GRANT_CREATE",
            entity_type="PolicyGrant",
            entity_id=row.id,
            details={
                "action": action,
                "effect": effect,
                "subject_type": "user" if user_id is not None else "role",
                "subject": user_id if user_id is not None else role.value,
            },
        ))
        self.db.flush()
        return row

    def revoke_grant(self, grant_id: int, *, revoked_by: User) -> PolicyGrant:
        self._require_policy_admin(revoked_by)
        row = self._query().filter(PolicyGrant.id == grant_id).first()
        if row is None:
            raise ValueError("policy grant not found")
        if row.is_active:
            row.is_active = False
            row.revoked_by_user_id = revoked_by.id
            row.revoked_at = _now()
            self.db.add(AuditLog(
                user_id=revoked_by.id,
                organization_id=self.organization_id,
                action="POLICY_GRANT_REVOKE",
                entity_type="PolicyGrant",
                entity_id=row.id,
                details={"action": row.action},
            ))
            self.db.flush()
        return row

    @staticmethod
    def _as_engine_grant(row: PolicyGrant) -> policy_engine.Grant:
        return policy_engine.Grant(
            action=row.action,
            effect=row.effect,
            organization_id=row.organization_id,
            role=row.role,
            user_id=row.user_id,
            max_amount=row.max_amount,
            daily_limit_amount=row.daily_limit_amount,
            monthly_limit_amount=row.monthly_limit_amount,
            currency=row.currency,
            allowed_bank_accounts=row.allowed_bank_accounts,
            allowed_counterparties=row.allowed_counterparties,
            allowed_document_types=row.allowed_document_types,
            allowed_channels=row.allowed_channels,
            valid_from=row.valid_from,
            valid_until=row.valid_until,
            requires_step_up=row.requires_step_up,
            required_approvals=row.required_approvals,
            separation_of_duties=row.separation_of_duties,
            requires_reason=row.requires_reason,
        )

    def _reserved_spend(
        self,
        *,
        user_id: int,
        policy_action: str,
        period_start: datetime,
        exclude_request_id: int | None,
        exclude_message_id: int | None = None,
    ) -> Optional[Decimal]:
        action_types = [
            action_type for action_type, mapped in ACTION_TYPE_TO_POLICY_ACTION.items()
            if mapped == policy_action
        ]
        query = self.db.query(IrreversibleActionRequest).filter(
            IrreversibleActionRequest.organization_id == self.organization_id,
            IrreversibleActionRequest.proposed_by_user_id == user_id,
            IrreversibleActionRequest.action_type.in_(action_types),
            IrreversibleActionRequest.status.in_(RESERVED_STATUSES),
            IrreversibleActionRequest.proposed_at >= period_start,
        )
        if exclude_request_id is not None:
            query = query.filter(IrreversibleActionRequest.id != exclude_request_id)
        total = Decimal("0")
        for row in query.all():
            amount = _payload_context(row.payload or {}).get("amount")
            if amount is None:
                return None
            total += amount
        chat_query = self.db.query(ChatMessage).filter(
            ChatMessage.organization_id == self.organization_id,
            ChatMessage.user_id == user_id,
            ChatMessage.created_at >= period_start,
            ChatMessage.pending_action.is_not(None),
            or_(
                ChatMessage.action_status.is_(None),
                ChatMessage.action_status.in_(("pending", "executing", "executed", "unknown")),
            ),
        )
        if exclude_message_id is not None:
            chat_query = chat_query.filter(ChatMessage.id != exclude_message_id)
        for message in chat_query.all():
            pending = message.pending_action or {}
            if pending.get("policy_action") != policy_action:
                continue
            amount = _decimal(pending.get("policy_amount"))
            if amount is None:
                return None
            total += amount
        return total

    def evaluate(
        self,
        *,
        user: User,
        action: str,
        amount: Decimal | None = None,
        currency: str = "ILS",
        bank_account: str | None = None,
        counterparty_id: int | None = None,
        document_type: str | None = None,
        channel: str | None = None,
        proposed_by_user_id: int | None = None,
        exclude_request_id: int | None = None,
        exclude_message_id: int | None = None,
    ) -> policy_engine.Decision:
        role = self._effective_role(user)
        if role is None:
            return policy_engine.Decision(
                action=action, allowed=False, reason="no_active_organization_membership",
            )
        rows = self.list_grants()
        grants = [self._as_engine_grant(row) for row in rows]
        relevant = [
            row for row in rows
            if row.action == action and (
                row.user_id == user.id or (row.user_id is None and row.role == role)
            )
        ]
        now = _now()
        spent_today = None
        spent_month = None
        if any(row.daily_limit_amount is not None for row in relevant):
            spent_today = self._reserved_spend(
                user_id=user.id,
                policy_action=action,
                period_start=now.replace(hour=0, minute=0, second=0, microsecond=0),
                exclude_request_id=exclude_request_id,
                exclude_message_id=exclude_message_id,
            )
        if any(row.monthly_limit_amount is not None for row in relevant):
            spent_month = self._reserved_spend(
                user_id=user.id,
                policy_action=action,
                period_start=now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
                exclude_request_id=exclude_request_id,
                exclude_message_id=exclude_message_id,
            )
        return policy_engine.evaluate(
            grants=grants,
            organization_id=self.organization_id,
            user_id=user.id,
            role=role,
            action=action,
            amount=amount,
            currency=currency,
            spent_today=spent_today,
            spent_this_month=spent_month,
            bank_account=bank_account,
            counterparty_id=counterparty_id,
            document_type=document_type,
            channel=channel,
            proposed_by_user_id=proposed_by_user_id,
            at=now,
        )

    def evaluate_irreversible(
        self,
        *,
        user: User,
        action_type: str,
        payload: dict[str, Any],
        channel: str | None = None,
        exclude_request_id: int | None = None,
    ) -> policy_engine.Decision:
        action = ACTION_TYPE_TO_POLICY_ACTION.get(action_type)
        if action is None:
            return policy_engine.Decision(
                action=action_type, allowed=False, reason="unknown_action_type_policy_mapping",
            )
        context = _payload_context(payload)
        return self.evaluate(
            user=user,
            action=action,
            channel=channel,
            exclude_request_id=exclude_request_id,
            **context,
        )

    def tool_context(
        self, *, policy_action: str, tool_input: dict[str, Any],
    ) -> dict[str, Any]:
        """Derive only policy fields that can be proven from tool input/DB."""
        context = _payload_context(tool_input)
        if policy_action == "invoices.issue":
            total = Decimal("0")
            valid = True
            for item in tool_input.get("items") or []:
                quantity = _decimal(item.get("quantity", 1))
                unit_price = _decimal(item.get("unit_price"))
                vat_rate = _decimal(item.get("vat_rate", 0))
                if quantity is None or unit_price is None or vat_rate is None:
                    valid = False
                    break
                if vat_rate > 1:
                    vat_rate = vat_rate / Decimal("100")
                total += quantity * unit_price * (Decimal("1") + vat_rate)
            context["amount"] = total if valid and tool_input.get("items") else None
            context["document_type"] = tool_input.get("document_type")
            customer_id = tool_input.get("customer_id")
            try:
                context["counterparty_id"] = int(customer_id)
            except (TypeError, ValueError):
                context["counterparty_id"] = None
        elif policy_action == "payment_link.create" and "invoice_id" in tool_input:
            # W3 גל 2: הפעולה משרתת שני כלים — create_payment_link (לפי
            # invoice_id, הסכום נגזר מיתרת החשבונית ב-DB) ו-
            # begin_payment_redirect (סכום חופשי שכבר חולץ ע"י
            # _payload_context). הענף רץ רק כשיש invoice_id, אחרת היה
            # דורס את הסכום האמיתי ב-None וגורם דחיות-שווא תחת תקרות.
            invoice_id = tool_input.get("invoice_id")
            invoice = self.db.query(Invoice).filter(
                Invoice.id == invoice_id,
                Invoice.organization_id == self.organization_id,
            ).first()
            context["amount"] = Decimal(str(invoice.balance)) if invoice else None
            context["currency"] = invoice.currency if invoice else "ILS"
            context["counterparty_id"] = invoice.contact_id if invoice else None
        elif policy_action == "expenses.file":
            expense_id = tool_input.get("expense_id")
            expense = self.db.query(Expense).filter(
                Expense.id == expense_id,
                Expense.organization_id == self.organization_id,
            ).first()
            context["amount"] = Decimal(str(expense.total)) if expense else None
            context["counterparty_id"] = expense.supplier_id if expense else None
        return context

    def evaluate_tool(
        self,
        *,
        user: User,
        policy_action: str,
        tool_input: dict[str, Any],
        channel: str,
        exclude_message_id: int | None = None,
    ) -> policy_engine.Decision:
        context = self.tool_context(
            policy_action=policy_action, tool_input=tool_input,
        )
        return self.evaluate(
            user=user,
            action=policy_action,
            channel=channel,
            exclude_message_id=exclude_message_id,
            **context,
        )
