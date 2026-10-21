"""withRBAC של Medici (lib/rbac/middleware.ts) כ-dependency של FastAPI.

ב-Medici ``getUserFromRequest`` היה mock (טוקני דמה קבועים) והתפקיד היה
גלובלי. כאן:
- הזהות מגיעה מ-``get_current_user`` האמיתי (JWT + token_version + jti).
- התפקיד נקבע **בארגון היעד** (``OrganizationMembership``), חוץ מ-
  ``super_admin`` שהוא תפקיד פלטפורמה מה-DB. ``User.role=admin`` לבדו אינו
  מקנה דבר בארגון שבו אין לאדם חברות.
- סירוב נרשם ל-AuditLog (ACCESS_DENIED) ו-commit לפני ה-403; גישה
  מוצלחת נרשמת (ACCESS_GRANTED) כשה-endpoint מסומן ``audit``.

שימוש::

    guard: RBACGuard = Depends(require_rbac("ADMIN.ACCESS.GRANT"))
    guard.authorize(organization_id)          # ארגון היעד מגוף הבקשה
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db_session
from ..models import User
from ..services import auth_audit
from ..services.access_grants import actor_role_in, is_super_admin
from ..services.rbac import ENDPOINT_CAPABILITIES, PermissionChecker
from .dependencies import get_current_user


@dataclass
class RBACGuard:
    endpoint_key: str
    user: User
    request: Request
    db: Session

    def _deny(self, reason: str, organization_id: Optional[int], missing: list[str]) -> HTTPException:
        auth_audit.record(
            self.db, action="ACCESS_DENIED", resource=self.endpoint_key, status=403,
            request=self.request, user_id=self.user.id, organization_id=organization_id,
            error=reason, extra={"missing_scopes": missing} if missing else None,
        )
        return HTTPException(
            status_code=403,
            detail={"error": "Forbidden", "message_he": "אין לך הרשאה לפעולה הזו",
                    "reason": reason, "missing_scopes": missing},
        )

    def _granted(self, organization_id: Optional[int], role: str) -> None:
        if ENDPOINT_CAPABILITIES.get(self.endpoint_key, {}).get("audit"):
            auth_audit.record(
                self.db, action="ACCESS_GRANTED", resource=self.endpoint_key, status=200,
                request=self.request, user_id=self.user.id, organization_id=organization_id,
                extra={"role": role}, commit=False,
            )

    def authorize(self, organization_id: int) -> str:
        """בדיקה מול התפקיד בארגון היעד. מחזיר את מפתח התפקיד."""
        role = actor_role_in(self.db, self.user, organization_id)
        result = PermissionChecker.can_access_endpoint(role, self.endpoint_key)
        if not result.allowed:
            raise self._deny(result.reason or "denied", organization_id, result.missing_scopes)
        self._granted(organization_id, role or "")
        return role or ""

    def authorize_platform(self) -> str:
        """פעולה חוצת-ארגונים — רק תפקיד פלטפורמה (super_admin)."""
        role = "super_admin" if is_super_admin(self.user) else None
        result = PermissionChecker.can_access_endpoint(role, self.endpoint_key)
        if not result.allowed:
            raise self._deny(result.reason or "platform_role_required", None, result.missing_scopes)
        self._granted(None, role or "")
        return role or ""


def require_rbac(endpoint_key: str):
    if endpoint_key not in ENDPOINT_CAPABILITIES:
        raise KeyError(f"unknown RBAC endpoint key: {endpoint_key}")

    async def dependency(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db_session),
    ) -> RBACGuard:
        return RBACGuard(endpoint_key=endpoint_key, user=user, request=request, db=db)

    return dependency
