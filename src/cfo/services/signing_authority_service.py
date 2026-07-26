"""Organization owner/signatory policy, deliberately separate from RBAC."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import AuditLog, OrganizationSigningAuthority, User, UserRole
from .irreversible_action_service import (
    ActionAuthorizationError,
    ActionConflictError,
    ActionStateError,
    ActionValidationError,
    SUPPORTED_ACTION_TYPES,
)


AUTHORITY_TYPES = frozenset({"owner", "authorized_signer"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_scopes(action_types: list[str]) -> list[str]:
    scopes = list(dict.fromkeys(action_types))
    if not scopes:
        raise ActionValidationError("at least one action type is required")
    if "*" in scopes and len(scopes) != 1:
        raise ActionValidationError("'*' must be the only action type")
    unsupported = set(scopes) - SUPPORTED_ACTION_TYPES - {"*"}
    if unsupported:
        raise ActionValidationError(
            f"unsupported action types: {sorted(unsupported)}",
        )
    return scopes


class SigningAuthorityService:
    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.organization_id = organization_id

    def _query(self):
        return self.db.query(OrganizationSigningAuthority).filter(
            OrganizationSigningAuthority.organization_id
            == self.organization_id,
        )

    def list(self, *, include_inactive: bool = False):
        query = self._query()
        if not include_inactive:
            query = query.filter(
                OrganizationSigningAuthority.is_active.is_(True),
            )
        return query.order_by(OrganizationSigningAuthority.id.asc()).all()

    def authority_for(
        self,
        user: User,
        action_type: str,
    ) -> OrganizationSigningAuthority | None:
        if (
            not user.is_active
            or user.organization_id != self.organization_id
        ):
            return None
        rows = self._query().filter(
            OrganizationSigningAuthority.user_id == user.id,
            OrganizationSigningAuthority.is_active.is_(True),
        ).all()
        return next(
            (
                row for row in rows
                if "*" in (row.action_types or [])
                or action_type in (row.action_types or [])
            ),
            None,
        )

    def _require_owner(
        self,
        user: User,
    ) -> OrganizationSigningAuthority:
        if (
            not user.is_active
            or user.organization_id != self.organization_id
        ):
            raise ActionAuthorizationError(
                "active organization owner authority is required",
            )
        row = self._query().filter(
            OrganizationSigningAuthority.user_id == user.id,
            OrganizationSigningAuthority.authority_type == "owner",
            OrganizationSigningAuthority.is_active.is_(True),
        ).first()
        if row is None:
            raise ActionAuthorizationError(
                "active organization owner authority is required",
            )
        return row

    def bootstrap_owner(
        self,
        *,
        user: User,
        confirmation: str,
    ) -> OrganizationSigningAuthority:
        """One-time explicit owner claim for organizations predating this policy."""
        if confirmation != "I_AM_AUTHORIZED_OWNER":
            raise ActionValidationError(
                "exact owner confirmation is required",
            )
        if (
            not user.is_active
            or user.organization_id != self.organization_id
            or user.role != UserRole.ADMIN
        ):
            raise ActionAuthorizationError(
                "an active organization admin must bootstrap owner authority",
            )
        if self._query().count() != 0:
            raise ActionConflictError(
                "signing authority policy is already initialized",
            )

        row = OrganizationSigningAuthority(
            organization_id=self.organization_id,
            user_id=user.id,
            authority_type="owner",
            action_types=["*"],
            is_active=True,
            granted_by_user_id=user.id,
        )
        self.db.add(row)
        self.db.flush()
        self.db.add(AuditLog(
            user_id=user.id,
            organization_id=self.organization_id,
            action="BOOTSTRAP_OWNER_AUTHORITY",
            entity_type="OrganizationSigningAuthority",
            entity_id=row.id,
            details={"confirmation": confirmation},
        ))
        self.db.commit()
        self.db.refresh(row)
        return row

    def grant(
        self,
        *,
        granted_by: User,
        user_id: int,
        authority_type: str,
        action_types: list[str],
    ) -> OrganizationSigningAuthority:
        self._require_owner(granted_by)
        if authority_type not in AUTHORITY_TYPES:
            raise ActionValidationError(
                f"unsupported authority_type: {authority_type}",
            )
        scopes = _normalize_scopes(action_types)
        target = self.db.query(User).filter(
            User.id == user_id,
            User.organization_id == self.organization_id,
            User.is_active.is_(True),
        ).first()
        if target is None:
            raise ActionStateError("target user not found in organization")

        row = self._query().filter(
            OrganizationSigningAuthority.user_id == user_id,
        ).first()
        if row is None:
            row = OrganizationSigningAuthority(
                organization_id=self.organization_id,
                user_id=user_id,
                granted_by_user_id=granted_by.id,
            )
            self.db.add(row)
        row.authority_type = authority_type
        row.action_types = scopes
        row.is_active = True
        row.granted_by_user_id = granted_by.id
        row.revoked_by_user_id = None
        row.revoked_at = None
        self.db.flush()
        self.db.add(AuditLog(
            user_id=granted_by.id,
            organization_id=self.organization_id,
            action="GRANT_SIGNING_AUTHORITY",
            entity_type="OrganizationSigningAuthority",
            entity_id=row.id,
            details={
                "target_user_id": user_id,
                "authority_type": authority_type,
                "action_types": scopes,
            },
        ))
        self.db.commit()
        self.db.refresh(row)
        return row

    def revoke(
        self,
        authority_id: int,
        *,
        revoked_by: User,
    ) -> OrganizationSigningAuthority:
        self._require_owner(revoked_by)
        row = self._query().filter(
            OrganizationSigningAuthority.id == authority_id,
            OrganizationSigningAuthority.is_active.is_(True),
        ).first()
        if row is None:
            raise ActionStateError(
                f"signing authority {authority_id} not found",
            )
        if row.authority_type == "owner":
            owner_count = self._query().filter(
                OrganizationSigningAuthority.authority_type == "owner",
                OrganizationSigningAuthority.is_active.is_(True),
            ).count()
            if owner_count <= 1:
                raise ActionConflictError(
                    "last owner authority cannot be revoked",
                )

        row.is_active = False
        row.revoked_by_user_id = revoked_by.id
        row.revoked_at = _utc_now()
        self.db.add(AuditLog(
            user_id=revoked_by.id,
            organization_id=self.organization_id,
            action="REVOKE_SIGNING_AUTHORITY",
            entity_type="OrganizationSigningAuthority",
            entity_id=row.id,
            details={"target_user_id": row.user_id},
        ))
        self.db.commit()
        self.db.refresh(row)
        return row
