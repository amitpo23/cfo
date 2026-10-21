"""Create and authorize client dashboards. No provider calls."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone

from ...models import (
    AuditLog, ClientDashboard, DashboardEntity, DashboardMember, DashboardPlan,
    DashboardPlanRevision, DashboardShareLink, Organization, User,
    UserRole,
)
from ..membership_service import role_in
from ..office_access import office_manages
from ..secret_compare import constant_time_equal

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,47}$")
PLAN_LIMIT_BYTES = 1_048_576
READ_ROLES = {"owner", "accountant", "client_editor", "client_viewer"}
PLAN_ROLES = {"owner", "accountant", "client_editor"}


class DashboardError(Exception):
    def __init__(self, status: int, code: str, message_he: str):
        self.status = status
        self.code = code
        self.message_he = message_he
        super().__init__(message_he)


def not_found() -> DashboardError:
    return DashboardError(404, "not_found", "הדשבורד לא נמצא")


def create_dashboard(db, user: User, *, organization_id: int, slug: str, title: str,
                     template: str = "generic", access_mode: str = "link",
                     office_organization_id: int | None = None) -> ClientDashboard:
    if not SLUG_RE.fullmatch(slug or ""):
        raise DashboardError(422, "invalid_slug", "הכתובת חייבת להיות באנגלית, 3 עד 48 תווים")
    if template not in {"generic", "restaurant", "services"}:
        raise DashboardError(422, "invalid_template", "תבנית הדשבורד אינה מוכרת")
    if access_mode not in {"members", "link", "public"}:
        raise DashboardError(422, "invalid_access", "מצב הגישה אינו מוכר")
    org = db.get(Organization, organization_id)
    if org is None or not org.is_active or not _can_access_org(
        db, user, organization_id, office_organization_id,
    ):
        raise not_found()
    if db.query(ClientDashboard).filter_by(slug=slug).first():
        raise DashboardError(409, "slug_taken", "הכתובת כבר בשימוש")
    row = ClientDashboard(
        slug=slug, title=title.strip(), primary_organization_id=organization_id,
        office_organization_id=office_organization_id, template=template,
        access_mode=access_mode, status="draft", created_by=user.id,
    )
    db.add(row)
    db.flush()
    db.add(DashboardEntity(
        dashboard_id=row.id, organization_id=organization_id,
        label=org.name, role="primary",
    ))
    db.add(DashboardMember(
        dashboard_id=row.id, user_id=user.id, role="owner", status="active",
    ))
    db.add(AuditLog(
        user_id=user.id, organization_id=organization_id, action="CREATE_DASHBOARD",
        entity_type="ClientDashboard", entity_id=row.id,
        details={"slug": slug, "provider_calls": 0},
    ))
    db.commit()
    db.refresh(row)
    return row


def list_dashboards(db, user: User) -> list[dict]:
    rows = db.query(ClientDashboard).order_by(ClientDashboard.id).all()
    visible = [row for row in rows if role_for(db, user, row) is not None]
    return [_summary(row) for row in visible]


def get_dashboard(db, user: User, dashboard_id: int, *, allowed: set[str]) -> ClientDashboard:
    row = db.get(ClientDashboard, dashboard_id)
    if row is None or role_for(db, user, row) not in allowed:
        raise not_found()
    return row


def update_dashboard(db, user: User, dashboard_id: int, changes: dict) -> ClientDashboard:
    row = get_dashboard(db, user, dashboard_id, allowed={"owner"})
    if "title" in changes and changes["title"]:
        row.title = str(changes["title"]).strip()[:255]
    if "access_mode" in changes:
        if changes["access_mode"] not in {"members", "link", "public"}:
            raise DashboardError(422, "invalid_access", "מצב הגישה אינו מוכר")
        row.access_mode = changes["access_mode"]
    if "status" in changes:
        if changes["status"] not in {"draft", "active", "paused", "archived"}:
            raise DashboardError(422, "invalid_status", "סטטוס הדשבורד אינו מוכר")
        row.status = changes["status"]
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def role_for(db, user: User | None, row: ClientDashboard) -> str | None:
    if user is None:
        return None
    if _can_access_org(db, user, row.primary_organization_id, row.office_organization_id):
        return "owner"
    member = (
        db.query(DashboardMember)
        .filter_by(dashboard_id=row.id, user_id=user.id, status="active")
        .first()
    )
    if member is None:
        return None
    if member.expires_at and member.expires_at < datetime.utcnow():
        return None
    return member.role if member.role in READ_ROLES else None


def create_share_link(db, user: User, dashboard_id: int, *, label: str | None = None,
                      expires_at: datetime | None = None) -> dict:
    row = get_dashboard(db, user, dashboard_id, allowed={"owner"})
    token = secrets.token_urlsafe(32)
    link = DashboardShareLink(
        dashboard_id=row.id,
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        label=label,
        created_by=user.id,
        expires_at=expires_at,
    )
    db.add(link)
    db.flush()
    db.add(AuditLog(
        user_id=user.id, organization_id=row.primary_organization_id,
        action="CREATE_DASHBOARD_SHARE_LINK", entity_type="DashboardShareLink",
        entity_id=link.id, details={"provider_calls": 0},
    ))
    db.commit()
    return {"id": link.id, "token": token, "label": link.label}


def list_share_links(db, user: User, dashboard_id: int) -> list[dict]:
    row = get_dashboard(db, user, dashboard_id, allowed={"owner"})
    links = db.query(DashboardShareLink).filter_by(dashboard_id=row.id).order_by(DashboardShareLink.id).all()
    return [{
        "id": link.id, "label": link.label, "revoked_at": _iso(link.revoked_at),
        "expires_at": _iso(link.expires_at), "use_count": link.use_count,
    } for link in links]


def revoke_share_link(db, user: User, dashboard_id: int, link_id: int) -> None:
    row = get_dashboard(db, user, dashboard_id, allowed={"owner"})
    link = db.get(DashboardShareLink, link_id)
    if link is None or link.dashboard_id != row.id:
        raise not_found()
    link.revoked_at = datetime.utcnow()
    db.add(AuditLog(
        user_id=user.id, organization_id=row.primary_organization_id,
        action="REVOKE_DASHBOARD_SHARE_LINK", entity_type="DashboardShareLink",
        entity_id=link.id, details={"provider_calls": 0},
    ))
    db.commit()


def resolve_share_token(db, slug: str, token: str) -> tuple[ClientDashboard, DashboardShareLink]:
    row = _public_dashboard(db, slug)
    digest = hashlib.sha256(str(token or "").encode()).hexdigest()
    link = (
        db.query(DashboardShareLink)
        .filter_by(dashboard_id=row.id, token_sha256=digest)
        .first()
    )
    # Compare even when the row is missing so the branch is not a pure lookup miss.
    if not constant_time_equal(digest, link.token_sha256 if link else digest + "x"):
        raise not_found()
    if link is None or link.revoked_at is not None:
        raise not_found()
    if link.expires_at and link.expires_at < datetime.utcnow():
        raise not_found()
    return row, link


def mark_link_used(db, link: DashboardShareLink) -> None:
    link.use_count = (link.use_count or 0) + 1
    link.last_used_at = datetime.utcnow()
    db.commit()


def public_dashboard(db, slug: str) -> ClientDashboard:
    return _public_dashboard(db, slug)


MAX_DECISIONS = 1000
MAX_RULES = 200
MAX_PLAN_AMOUNT = 1e9
_RULE_FIELDS = {"description", "counterparty", "any"}
_RULE_DIRECTIONS = {"in", "out", "both"}


def _invalid_plan(message_he: str) -> DashboardError:
    return DashboardError(422, "invalid_plan", message_he)


def validate_filing_payload(payload: dict) -> None:
    """Check the filing parts of a plan: statusDecisions, statusRules, booksClosedMonths.

    Same limits as the Eliav tool's validatePlanData. Other keys are kept as sent.
    """
    from .filing import DECISION_CATEGORIES

    decisions = payload.get("statusDecisions")
    if decisions is not None:
        if not isinstance(decisions, dict):
            raise _invalid_plan("החלטות הסיווג חייבות להיות אובייקט")
        if len(decisions) > MAX_DECISIONS:
            raise _invalid_plan(f"אפשר לשמור עד {MAX_DECISIONS} החלטות סיווג")
        for key, item in decisions.items():
            if not str(key).isdigit() or not isinstance(item, dict):
                raise _invalid_plan("החלטת סיווג לא תקינה")
            if item.get("category") not in DECISION_CATEGORIES:
                raise _invalid_plan("קטגוריית ההחלטה אינה מוכרת")
            amount = item.get("amount")
            if isinstance(amount, bool) or not isinstance(amount, (int, float)) or abs(amount) > MAX_PLAN_AMOUNT:
                raise _invalid_plan("סכום ההחלטה לא תקין")
            if not isinstance(item.get("organizationId"), int) or not isinstance(item.get("date"), str):
                raise _invalid_plan("להחלטה חסרים ארגון או תאריך")
    rules = payload.get("statusRules")
    if rules is not None:
        if not isinstance(rules, list):
            raise _invalid_plan("כללי התיוק חייבים להיות רשימה")
        if len(rules) > MAX_RULES:
            raise _invalid_plan(f"אפשר לשמור עד {MAX_RULES} כללי תיוק")
        for rule in rules:
            if not isinstance(rule, dict):
                raise _invalid_plan("כלל תיוק לא תקין")
            contains = rule.get("contains")
            if not isinstance(contains, str) or not contains.strip() or len(contains) > 120:
                raise _invalid_plan("לכלל תיוק חסר טקסט לחיפוש")
            if rule.get("category") not in DECISION_CATEGORIES:
                raise _invalid_plan("קטגוריית הכלל אינה מוכרת")
            if rule.get("field", "description") not in _RULE_FIELDS:
                raise _invalid_plan("שדה הכלל אינו מוכר")
            if rule.get("direction", "both") not in _RULE_DIRECTIONS:
                raise _invalid_plan("כיוון הכלל אינו מוכר")
    closed = payload.get("booksClosedMonths")
    if closed is not None:
        if not isinstance(closed, list) or not all(
            isinstance(m, str) and re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", m) for m in closed
        ):
            raise _invalid_plan("רשימת החודשים הסגורים לא תקינה")


def save_plan(db, user: User, dashboard_id: int, payload: dict, if_match: str | None) -> dict:
    if if_match is None:
        raise DashboardError(412, "if_match_required", "חסרה כותרת If-Match")
    if not isinstance(payload, dict):
        raise DashboardError(415, "invalid_plan", "התוכנית חייבת להיות אובייקט JSON")
    _validate_managed_plan(payload)
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded.encode()) > PLAN_LIMIT_BYTES:
        raise DashboardError(413, "plan_too_large", "התוכנית גדולה ממגבלת המגה-בייט")
    validate_filing_payload(payload)
    row = get_dashboard(db, user, dashboard_id, allowed=PLAN_ROLES)
    current = db.get(DashboardPlan, row.id)
    expected = if_match.strip().strip('"')
    if current is None:
        if expected not in {"null", "*"}:
            raise DashboardError(409, "plan_conflict", "התוכנית השתנתה")
        version = secrets.token_hex(16)
        current = DashboardPlan(
            dashboard_id=row.id, version=version, schema_version=2,
            payload=payload, updated_at=datetime.utcnow(), updated_by=user.id,
        )
        db.add(current)
        db.add(DashboardPlanRevision(
            version=version, dashboard_id=row.id, previous_version=None,
            payload=payload, changed_at=datetime.utcnow(), changed_by=user.id,
        ))
    else:
        if not constant_time_equal(expected, current.version):
            raise DashboardError(409, "plan_conflict", "התוכנית השתנתה")
        version = secrets.token_hex(16)
        previous = current.version
        current.version = version
        current.payload = payload
        current.updated_at = datetime.utcnow()
        current.updated_by = user.id
        db.add(DashboardPlanRevision(
            version=version, dashboard_id=row.id, previous_version=previous,
            payload=payload, changed_at=datetime.utcnow(), changed_by=user.id,
        ))
    projected = _project_plan_budget(db, row.primary_organization_id, current.version, payload)
    db.add(AuditLog(
        user_id=user.id, organization_id=row.primary_organization_id,
        action="SAVE_DASHBOARD_PLAN", entity_type="DashboardPlan", entity_id=row.id,
        details={
            "version": current.version,
            "projected_budget_rows": projected,
            "provider_calls": 0,
        },
    ))
    db.commit()
    db.refresh(current)
    return {"version": current.version, "payload": current.payload, "updated_at": _iso(current.updated_at)}


def _validate_managed_plan(payload: dict) -> None:
    from .plan_budget import PlanBudgetError, validate_budget_lines
    try:
        validate_budget_lines(payload)
    except PlanBudgetError as exc:
        raise DashboardError(422, "invalid_plan", exc.message_he)


def _project_plan_budget(db, organization_id: int, version: str, payload: dict) -> int:
    from .plan_budget import PlanBudgetError, project_budget_lines, validate_budget_lines
    try:
        lines = validate_budget_lines(payload)
        if lines is None:
            return 0
        return project_budget_lines(db, organization_id, version, lines)
    except PlanBudgetError as exc:
        db.rollback()
        raise DashboardError(422, "invalid_plan", exc.message_he)


def dashboard_by_slug(db, user: User, slug: str) -> dict:
    row = db.query(ClientDashboard).filter_by(slug=slug).first()
    role = role_for(db, user, row) if row is not None else None
    if role not in READ_ROLES:
        raise not_found()
    return {
        "id": row.id, "slug": row.slug, "title": row.title, "status": row.status,
        "role": role, "can_edit": role in PLAN_ROLES, "provider_calls": 0,
    }


def read_filing(db, user: User, dashboard_id: int, *, page: int, page_size: int) -> dict:
    if page < 1 or page_size < 1 or page_size > 200:
        raise DashboardError(422, "invalid_page", "עמוד או גודל עמוד לא תקינים")
    row = get_dashboard(db, user, dashboard_id, allowed=READ_ROLES)
    from ...models import BankTransaction, Invoice
    from ..bank_status import card_account_ids, counts_in_cash_flow
    from .filing_report import build_filing_report
    from .plan_budget import budget_catalog
    current = db.get(DashboardPlan, row.id)
    payload = current.payload if current is not None and isinstance(current.payload, dict) else {}
    org_id = row.primary_organization_id
    card_ids = card_account_ids(db, org_id)
    bank_rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.organization_id == org_id,
            BankTransaction.superseded_by_id.is_(None),
        )
        .order_by(BankTransaction.transaction_date.desc(), BankTransaction.id.desc())
        .all()
    )
    visible = [bank for bank in bank_rows if counts_in_cash_flow(bank, card_ids)]
    invoices = [
        {
            "organization_id": invoice.organization_id,
            "number": invoice.invoice_number,
            "date": invoice.issue_date.isoformat(),
            "total": float(invoice.total or 0),
        }
        for invoice in db.query(Invoice).filter(Invoice.organization_id == org_id).all()
        if invoice.issue_date is not None
    ]
    report = build_filing_report(
        visible, payload, page=page, page_size=page_size, invoices=invoices,
    )
    role = role_for(db, user, row)
    report["role"] = role
    report["can_edit"] = role in PLAN_ROLES
    report["budget_categories"] = budget_catalog()
    report["provider_calls"] = 0
    return report


def read_plan(db, user: User, dashboard_id: int) -> dict:
    row = get_dashboard(db, user, dashboard_id, allowed=READ_ROLES)
    current = db.get(DashboardPlan, row.id)
    if current is None:
        return {"version": None, "payload": None, "updated_at": None}
    return {"version": current.version, "payload": current.payload, "updated_at": _iso(current.updated_at)}


def _public_dashboard(db, slug: str) -> ClientDashboard:
    row = db.query(ClientDashboard).filter_by(slug=slug).first()
    if row is None or row.status != "active":
        raise not_found()
    if row.access_mode == "members":
        raise not_found()
    return row


def _can_access_org(db, user: User, organization_id: int, office_organization_id: int | None) -> bool:
    """Active ADMIN membership, or platform SUPER_ADMIN.

    ``User.role`` and ``User.organization_id`` are not an authorization
    source. An office id is accepted only when that office manages the
    primary organization and the user is an active admin of the office.
    """
    if office_organization_id is not None and not _office_manages(
        db, office_organization_id, organization_id,
    ):
        return False
    if user.role == UserRole.SUPER_ADMIN:
        return True
    if role_in(db, user.id, organization_id) == UserRole.ADMIN:
        if office_organization_id is None:
            return True
        return role_in(db, user.id, office_organization_id) == UserRole.ADMIN
    if office_organization_id is None:
        return False
    return role_in(db, user.id, office_organization_id) == UserRole.ADMIN


def _office_manages(db, office_organization_id: int, organization_id: int) -> bool:
    return office_manages(db, office_organization_id, organization_id)


def _summary(row: ClientDashboard) -> dict:
    return {
        "id": row.id, "slug": row.slug, "title": row.title, "status": row.status,
        "access_mode": row.access_mode, "template": row.template,
        "primary_organization_id": row.primary_organization_id,
        "current_snapshot_id": row.current_snapshot_id,
    }


def _iso(value):
    return value.isoformat() if value else None


def failure_window_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    minute = (now.minute // 15) * 15
    return now.replace(minute=minute, second=0, microsecond=0)


def link_cookie_lifetime() -> timedelta:
    return timedelta(days=30)
