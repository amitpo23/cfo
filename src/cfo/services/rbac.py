"""RBAC — פורט Python של Medici (v0-bookinengine/lib/rbac/config.ts + permissions.ts).

אותו מבנה ואותם שמות מפתחות כמו ב-Medici, כדי ש-Medici יוכל בעתיד לנהל
את ההרשאות של רצף:

    ROLE_CONFIG[role] = {description, scopes, capabilities, constraints}
    ENDPOINT_CAPABILITIES[key] = {description, method, path,
                                  required_scopes_any, audit}
    SCOPES_CATALOG[scope] = תיאור

מה הותאם (ולמה) — ראו docs/AUTH_MEDICI_PORT.md:
- התפקידים הם ערכי ``UserRole`` של רצף + תפקידי דשבורד. ``admin`` של
  Medici (גישה מלאה, ``endpoints:*``) ממופה ל-``super_admin``; ``booker``
  (הרשאה נמוכה) ממופה ל-``viewer``. ``MEDICI_ROLE_ALIASES`` מתעד זאת.
- תפקיד בארגון נגזר מ-``OrganizationMembership`` (``role_in``), לעולם לא
  מ-``User.role``. רק ``super_admin`` הוא תפקיד פלטפורמה.
- אין משתמשי דמה, טוקני דמה או store בזיכרון — ראו ``api/rbac.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

ALL_ENDPOINTS = "endpoints:*"

SCOPES_CATALOG: dict[str, str] = {
    "org:read": "קריאת נתוני הארגון (דשבורד, דוחות).",
    "org:write": "פעולות כתיבה שגרתיות בתיק הארגון.",
    "org:admin": "ניהול הארגון: חברים, הגדרות, אינטגרציות.",
    "dashboard:read": "צפייה בדשבורד לקוח (/d/<slug>).",
    "dashboard:write": "עריכת תוכנית/פרסום דשבורד.",
    "access:read": "צפייה ברשימת ההרשאות לפי מייל.",
    "access:grant": "הענקה וביטול של גישה לפי מייל לארגון/דשבורד.",
    "audit:read": "קריאת יומן ביקורת (Medici: admin only by default).",
    "audit:write": "כתיבת יומן ביקורת (מערכת).",
    "tools:list": "רשימת הכלים הזמינים לתפקיד (Medici).",
    ALL_ENDPOINTS: "גישה מלאה לכל ה-endpoints (Medici admin).",
}

_ORG_ADMIN_SCOPES = [
    "org:read", "org:write", "org:admin", "dashboard:read", "dashboard:write",
    "access:read", "access:grant", "audit:read", "tools:list",
]

ROLE_CONFIG: dict[str, dict] = {
    "super_admin": {
        "description": "מפעיל פלטפורמה — המקבילה ל-admin של Medici. כל ה-endpoints, כל הארגונים.",
        "scopes": [*_ORG_ADMIN_SCOPES, "audit:write", ALL_ENDPOINTS],
        "capabilities": [
            "CAP_ENDPOINTS_ALL", "CAP_AUDIT_VIEW", "CAP_AUDIT_EXPORT", "CAP_TOOLS_LIST",
            "CAP_ACCESS_GRANT", "CAP_ACCESS_IMPORT", "CAP_ORG_ADMIN", "CAP_DASHBOARD_READ",
        ],
        "constraints": {
            "org_scope": "all_organizations",
            "endpoints": {"access": "allow_all", "deny_list": []},
        },
    },
    "admin": {
        "description": "מנהל ארגון — ניהול מלא בתוך הארגונים שבהם יש לו חברות ADMIN פעילה בלבד.",
        "scopes": list(_ORG_ADMIN_SCOPES),
        "capabilities": [
            "CAP_AUDIT_VIEW", "CAP_TOOLS_LIST", "CAP_ACCESS_GRANT", "CAP_ORG_ADMIN",
            "CAP_DASHBOARD_READ",
        ],
        "constraints": {
            "org_scope": "own_memberships",
            "grantable_roles": ["admin", "accountant", "manager", "user", "viewer"],
            "endpoints": {"access": "allow_all", "deny_list": ["ADMIN.ACCESS.IMPORT"]},
        },
    },
    "accountant": {
        "description": "רואה/ת חשבון — קריאה וכתיבה בתיק, בלי ניהול הרשאות.",
        "scopes": ["org:read", "org:write", "dashboard:read", "dashboard:write", "tools:list"],
        "capabilities": ["CAP_TOOLS_LIST", "CAP_DASHBOARD_READ"],
        "constraints": {"org_scope": "own_memberships",
                        "endpoints": {"access": "allow_all", "deny_list": []}},
    },
    "manager": {
        "description": "מנהל/ת — קריאה וכתיבה שגרתית.",
        "scopes": ["org:read", "org:write", "dashboard:read", "tools:list"],
        "capabilities": ["CAP_TOOLS_LIST", "CAP_DASHBOARD_READ"],
        "constraints": {"org_scope": "own_memberships",
                        "endpoints": {"access": "allow_all", "deny_list": []}},
    },
    "user": {
        "description": "משתמש/ת רגיל/ה בארגון.",
        "scopes": ["org:read", "org:write", "dashboard:read"],
        "capabilities": ["CAP_DASHBOARD_READ"],
        "constraints": {"org_scope": "own_memberships",
                        "endpoints": {"access": "allow_all", "deny_list": []}},
    },
    "viewer": {
        "description": "צפייה בלבד — המקבילה ל-booker (הרשאה נמוכה) של Medici.",
        "scopes": ["org:read", "dashboard:read"],
        "capabilities": ["CAP_DASHBOARD_READ"],
        "constraints": {"org_scope": "own_memberships", "read_only": True,
                        "endpoints": {"access": "allow_list_only",
                                      "allow_list": ["DASHBOARD.READ", "ORG.READ"]}},
    },
    # תפקידי דשבורד (DashboardMember / DashboardAccessGrant) — היקף: דשבורד אחד.
    "client_viewer": {
        "description": "צפייה בדשבורד לקוח אחד בלבד.",
        "scopes": ["dashboard:read"],
        "capabilities": ["CAP_DASHBOARD_READ"],
        "constraints": {"dashboard_scope": "granted_dashboards", "read_only": True,
                        "endpoints": {"access": "allow_list_only", "allow_list": ["DASHBOARD.READ"]}},
    },
    "client_editor": {
        "description": "צפייה ועריכת תוכנית בדשבורד לקוח אחד.",
        "scopes": ["dashboard:read", "dashboard:write"],
        "capabilities": ["CAP_DASHBOARD_READ"],
        "constraints": {"dashboard_scope": "granted_dashboards",
                        "endpoints": {"access": "allow_list_only", "allow_list": ["DASHBOARD.READ"]}},
    },
}

# תאימות ל-Medici: שם תפקיד שם → תפקיד מקביל כאן.
MEDICI_ROLE_ALIASES: dict[str, str] = {"admin": "super_admin", "booker": "viewer"}

ORG_GRANT_ROLES = ("admin", "accountant", "manager", "user", "viewer")
DASHBOARD_GRANT_ROLES = ("client_viewer", "client_editor")

ENDPOINT_CAPABILITIES: dict[str, dict] = {
    "ORG.READ": {
        "description": "קריאת נתוני ארגון",
        "method": "GET", "path": "/api/*",
        "required_scopes_any": ["org:read", ALL_ENDPOINTS], "audit": False,
    },
    "DASHBOARD.READ": {
        "description": "צפייה בדשבורד לקוח",
        "method": "GET", "path": "/api/public/d/{slug}",
        "required_scopes_any": ["dashboard:read", ALL_ENDPOINTS], "audit": False,
    },
    "ADMIN.ACCESS.LIST": {
        "description": "רשימת הרשאות לפי מייל לארגון/דשבורד",
        "method": "GET", "path": "/api/admin/access/grants",
        "required_scopes_any": ["access:read", ALL_ENDPOINTS], "audit": False,
    },
    "ADMIN.ACCESS.GRANT": {
        "description": "הענקת גישה לפי מייל (הזמנה)",
        "method": "POST", "path": "/api/admin/access/grants",
        "required_scopes_any": ["access:grant", ALL_ENDPOINTS], "audit": True,
    },
    "ADMIN.ACCESS.REVOKE": {
        "description": "ביטול גישה לפי מייל",
        "method": "POST", "path": "/api/admin/access/grants/revoke",
        "required_scopes_any": ["access:grant", ALL_ENDPOINTS], "audit": True,
    },
    "ADMIN.ACCESS.EXPORT": {
        "description": "ייצוא JSON של ההרשאות (לניהול מ-Medici)",
        "method": "GET", "path": "/api/admin/access/export",
        "required_scopes_any": ["access:read", ALL_ENDPOINTS], "audit": True,
    },
    "ADMIN.ACCESS.IMPORT": {
        "description": "ייבוא JSON של הרשאות (מנהל-על בלבד)",
        "method": "POST", "path": "/api/admin/access/import",
        "required_scopes_any": [ALL_ENDPOINTS], "audit": True,
    },
    "ADMIN.AUDIT.READ": {
        "description": "קריאת יומן ביקורת",
        "method": "GET", "path": "/api/admin/audit-logs",
        "required_scopes_any": ["audit:read", ALL_ENDPOINTS], "audit": True,
    },
    "ADMIN.TOOLS.LIST": {
        "description": "מפת התפקידים/scopes/endpoints (מסך /admin/access)",
        "method": "GET", "path": "/api/admin/access/rbac",
        "required_scopes_any": ["tools:list", ALL_ENDPOINTS], "audit": False,
    },
}


@dataclass
class PermissionCheckResult:
    allowed: bool
    reason: Optional[str] = None
    missing_scopes: list[str] = field(default_factory=list)


class PermissionChecker:
    """מקביל 1:1 ל-PermissionChecker של Medici (permissions.ts)."""

    @staticmethod
    def has_any_scope(user_scopes: Iterable[str], required: Iterable[str]) -> bool:
        owned = set(user_scopes)
        return any(scope in owned for scope in required)

    @staticmethod
    def has_all_scopes(user_scopes: Iterable[str], required: Iterable[str]) -> bool:
        owned = set(user_scopes)
        return all(scope in owned for scope in required)

    @staticmethod
    def scopes_for_role(role: Optional[str]) -> list[str]:
        return list(ROLE_CONFIG.get(role or "", {}).get("scopes", []))

    @staticmethod
    def capabilities_for_role(role: Optional[str]) -> list[str]:
        return list(ROLE_CONFIG.get(role or "", {}).get("capabilities", []))

    @staticmethod
    def has_capability(role: Optional[str], capability: str) -> bool:
        return capability in PermissionChecker.capabilities_for_role(role)

    @staticmethod
    def can_access_endpoint(role: Optional[str], endpoint_key: str) -> PermissionCheckResult:
        endpoint = ENDPOINT_CAPABILITIES.get(endpoint_key)
        if endpoint is None:
            return PermissionCheckResult(False, f"Endpoint {endpoint_key} not found in capabilities")
        config = ROLE_CONFIG.get(role or "")
        if config is None:
            return PermissionCheckResult(
                False, "no_role_in_target", list(endpoint["required_scopes_any"]),
            )
        scopes = config["scopes"]
        if not PermissionChecker.has_any_scope(scopes, endpoint["required_scopes_any"]):
            return PermissionCheckResult(
                False, "Missing required scopes",
                [s for s in endpoint["required_scopes_any"] if s not in scopes],
            )
        constraints = config.get("constraints", {}).get("endpoints", {})
        if constraints.get("access") == "allow_list_only" and endpoint_key not in constraints.get("allow_list", []):
            return PermissionCheckResult(False, f"Endpoint {endpoint_key} not in allow list for role {role}")
        if endpoint_key in constraints.get("deny_list", []):
            return PermissionCheckResult(False, f"Endpoint {endpoint_key} is in deny list for role {role}")
        return PermissionCheckResult(True)

    @staticmethod
    def accessible_endpoints(role: Optional[str]) -> list[str]:
        return [k for k in ENDPOINT_CAPABILITIES if PermissionChecker.can_access_endpoint(role, k).allowed]


def rbac_export() -> dict:
    """אותו מבנה כמו config.ts של Medici — למסך הניהול ולסנכרון עתידי."""
    return {
        "version": 1,
        "roles": ROLE_CONFIG,
        "endpoints": ENDPOINT_CAPABILITIES,
        "scopes": SCOPES_CATALOG,
        "medici_role_aliases": MEDICI_ROLE_ALIASES,
    }
