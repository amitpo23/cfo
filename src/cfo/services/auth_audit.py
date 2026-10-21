"""AuditLogger — פורט של Medici lib/rbac/audit.ts אל AuditLog של רצף (DB).

Medici שמר ביקורת במערך בזיכרון (10K רשומות, נמחק בכל cold start). כאן
כל רשומה היא שורת ``audit_logs``. שדות Medici (action, resource, method,
path, status, error) נשמרים ב-``details``; ip ו-user_agent בעמודות הקיימות.

לעולם לא נרשם טוקן, קוד או סיסמה — רק ``reason`` קצר.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from ..models import AuditLog


def client_ip(request: Optional[Request]) -> Optional[str]:
    """אותה מדיניות אמון כמו client_dashboards._client_address: כותרות
    forwarding נאמנות רק על Vercel, שם הפלטפורמה דורסת אותן."""
    if request is None:
        return None
    if os.getenv("VERCEL") or os.getenv("VERCEL_ENV"):
        for header in ("x-vercel-forwarded-for", "x-real-ip", "x-forwarded-for"):
            value = (request.headers.get(header) or "").split(",")[0].strip()
            if value:
                return value
    if request.client and request.client.host:
        return request.client.host
    return None


def record(
    db: Session,
    *,
    action: str,
    resource: str,
    status: int,
    request: Optional[Request] = None,
    user_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    error: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
    commit: bool = True,
) -> None:
    details: dict[str, Any] = {"resource": resource, "status": status}
    if request is not None:
        details["method"] = request.method
        details["path"] = request.url.path
    if error:
        details["error"] = error
    if extra:
        details.update(extra)
    user_agent = request.headers.get("user-agent") if request is not None else None
    db.add(AuditLog(
        user_id=user_id,
        organization_id=organization_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        ip_address=client_ip(request),
        user_agent=(user_agent or "")[:512] or None,
    ))
    if commit:
        db.commit()
