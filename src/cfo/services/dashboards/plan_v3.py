"""Dashboard plan version 3. Stored on the existing plan tables. No provider calls.

The plan is the client dashboard's source of truth for budget lines, status
decisions, custom filing rules, and notes. ``bankDecisions`` are derived and
are rejected rather than stored. Saving projects ``budgetLines`` into the
organization's ``budgets`` rows and creates any missing group/category rows
in the same transaction as the plan revision and its audit row.

Write access reuses the dashboard plan roles: owner (the organization admin),
accountant, and client_editor. Viewers (``client_viewer``) can read.
Unknown and forbidden dashboards are both 404.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_serializer, field_validator
from sqlalchemy.exc import IntegrityError

from ...models import AuditLog, Budget, Category, DashboardPlan, DashboardPlanRevision, User
from ..secret_compare import constant_time_equal
from .budget import REVENUE_KEYS, category_key
from .service import PLAN_LIMIT_BYTES, PLAN_ROLES, READ_ROLES, DashboardError, get_dashboard

SCHEMA_VERSION = 3
_MONTH = re.compile(r"^(?:20\d{2}|2100)-(?:0[1-9]|1[0-2])$")
_MAX_AMOUNT = Decimal("9999999999.99")
_NO_PREVIOUS = "0"


class BudgetLineV3(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    group: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=255)
    month: str = Field(pattern=_MONTH.pattern)
    amount: Decimal

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_amount(cls, value):
        if isinstance(value, str):
            value = value.strip()
        if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
            raise ValueError("amount")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("amount")
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise ValueError("amount")
        if not amount.is_finite() or amount < 0 or amount > _MAX_AMOUNT:
            raise ValueError("amount")
        quantized = amount.quantize(Decimal("0.01"))
        if abs(amount - quantized) > Decimal("0.0000001"):
            raise ValueError("amount")
        return quantized

    @field_serializer("amount")
    def _amount_out(self, value: Decimal) -> str:
        return f"{value.quantize(Decimal('0.01')):f}"


class StatusDecisionV3(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    key: str = Field(min_length=1, max_length=200)
    status: str = Field(min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note", mode="before")
    @classmethod
    def _blank_note(cls, value):
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value


class CustomFilingRuleV3(BaseModel):
    """A stored filing instruction. This module does not apply it."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    match_text: str = Field(min_length=1, max_length=500)
    group: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=255)


class DashboardPlanV3(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    budgetLines: list[BudgetLineV3] = Field(max_length=500)
    statusDecisions: list[StatusDecisionV3] = Field(max_length=2000)
    customFilingRules: list[CustomFilingRuleV3] = Field(max_length=200)
    notes: str = Field(max_length=20000)


def read_plan(db, user: User, dashboard_id: int) -> dict:
    row = get_dashboard(db, user, dashboard_id, allowed=READ_ROLES)
    current = db.get(DashboardPlan, row.id)
    if current is None:
        return _envelope(
            version=_NO_PREVIOUS, schema_version=SCHEMA_VERSION, plan=None,
            updated_at=None, dashboard_id=row.id,
        )
    return _envelope(
        version=current.version,
        schema_version=current.schema_version,
        plan=_stored_plan(current),
        updated_at=_iso(current.updated_at),
        dashboard_id=row.id,
    )


def save_plan(db, user: User, dashboard_id: int, payload: object, if_match: str | None) -> dict:
    token = _match_token(if_match)
    row = get_dashboard(db, user, dashboard_id, allowed=PLAN_ROLES)
    plan = parse_plan(payload)
    current = db.get(DashboardPlan, row.id)
    previous, revision = _claim_revision(db, row.id, current, token)
    stored = plan.model_dump(mode="json")
    try:
        categories_created = _project(db, row.primary_organization_id, plan)
        current = _write_plan(
            db, current, dashboard_id=row.id, user_id=user.id,
            previous=previous, revision=revision, stored=stored,
        )
        db.add(AuditLog(
            user_id=user.id,
            organization_id=row.primary_organization_id,
            action="SAVE_DASHBOARD_PLAN_V3",
            entity_type="DashboardPlan",
            entity_id=row.id,
            details={
                "schema_version": SCHEMA_VERSION,
                "revision": revision,
                "budget_lines": len(plan.budgetLines),
                "categories_created": categories_created,
                "provider_calls": 0,
            },
        ))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _integrity_error(exc) from exc
    db.refresh(current)
    body = _envelope(
        version=current.version,
        schema_version=current.schema_version,
        plan=stored,
        updated_at=_iso(current.updated_at),
        dashboard_id=row.id,
    )
    body["projected"] = {
        "budget_lines": len(plan.budgetLines),
        "categories_created": categories_created,
    }
    return body


def parse_plan(payload: object) -> DashboardPlanV3:
    if not isinstance(payload, dict):
        raise DashboardError(422, "invalid_plan", "התוכנית חייבת להיות אובייקט JSON")
    if "bankDecisions" in payload:
        raise DashboardError(422, "invalid_plan", "החלטות בנק נגזרות ואינן נשמרות בתוכנית")
    try:
        plan = DashboardPlanV3.model_validate(payload)
    except ValidationError as exc:
        raise DashboardError(422, "invalid_plan", _validation_message(exc)) from exc
    _reject_duplicates(plan)
    encoded = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False).encode()
    if len(encoded) > PLAN_LIMIT_BYTES:
        raise DashboardError(413, "plan_too_large", "התוכנית גדולה ממגבלת המגה-בייט")
    return plan


def _reject_duplicates(plan: DashboardPlanV3) -> None:
    lines: set[tuple[str, str]] = set()
    for line in plan.budgetLines:
        ident = (category_key(line.category), line.month)
        if ident in lines:
            raise DashboardError(422, "invalid_plan", "אותה קטגוריה ואותו חודש מופיעים פעמיים")
        lines.add(ident)
    decisions: set[str] = set()
    for decision in plan.statusDecisions:
        if decision.key in decisions:
            raise DashboardError(422, "invalid_plan", "החלטת סטטוס כפולה")
        decisions.add(decision.key)
    rules: set[str] = set()
    for rule in plan.customFilingRules:
        if rule.name in rules:
            raise DashboardError(422, "invalid_plan", "כלל תיוק כפול")
        rules.add(rule.name)


def _validation_message(exc: ValidationError) -> str:
    errors = exc.errors()
    for err in errors:
        if "bankDecisions" in tuple(err.get("loc") or ()):
            return "החלטות בנק נגזרות ואינן נשמרות בתוכנית"
    err = errors[0]
    loc = tuple(err.get("loc") or ())
    if err.get("type") == "extra_forbidden":
        return "התוכנית כוללת שדה לא מוכר"
    if err.get("type") == "missing":
        return "חסר שדה בתוכנית"
    if loc and loc[-1] == "amount":
        return "סכום התקציב אינו תקין"
    if loc and loc[-1] == "month":
        return "החודש חייב להיות בפורמט YYYY-MM"
    return "התוכנית אינה תקינה"


def _match_token(if_match: str | None) -> str:
    if if_match is None or not str(if_match).strip():
        raise DashboardError(412, "if_match_required", "חסרה כותרת If-Match")
    text = str(if_match).strip()
    if text[:2].upper() == "W/":
        text = text[2:].strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    if not text or len(text) > 36:
        raise DashboardError(412, "if_match_required", "כותרת If-Match אינה תקינה")
    return text


def _claim_revision(db, dashboard_id: int, current: DashboardPlan | None, token: str) -> tuple[str, int]:
    """Return the previous version token and the next revision number.

    ``dashboard_plan_revisions.version`` is a global primary key, so the stored
    token is ``{dashboard_id}-{revision}``. If-Match may be that token or the
    revision number. A missing plan accepts only ``0``.
    """
    if current is None:
        if not constant_time_equal(token, _NO_PREVIOUS):
            raise DashboardError(409, "plan_conflict", "התוכנית השתנתה")
        return _NO_PREVIOUS, 1
    revision = _parse_revision(current.version, dashboard_id)
    matches_token = constant_time_equal(token, current.version)
    matches_number = revision is not None and constant_time_equal(token, str(revision))
    if not matches_token and not matches_number:
        raise DashboardError(409, "plan_conflict", "התוכנית השתנתה")
    return current.version, _next_revision(db, dashboard_id, revision)


def _version_token(dashboard_id: int, revision: int) -> str:
    token = f"{dashboard_id}-{revision}"
    if len(token) > 36:
        raise DashboardError(422, "invalid_plan", "מספר הגרסה ארוך מדי")
    return token


def _parse_revision(version: str, dashboard_id: int | None) -> int | None:
    if version == _NO_PREVIOUS:
        return 0
    if dashboard_id is not None:
        prefix = f"{dashboard_id}-"
        suffix = version[len(prefix):] if version.startswith(prefix) else ""
        if suffix.isdigit():
            return int(suffix)
    if str(version).isdigit():
        return int(version)
    return None


def _next_revision(db, dashboard_id: int, current_revision: int | None) -> int:
    if current_revision is not None:
        return current_revision + 1
    versions = db.query(DashboardPlanRevision.version).filter_by(dashboard_id=dashboard_id).all()
    numbers = [
        number for row in versions
        if (number := _parse_revision(str(row[0]), dashboard_id)) is not None
    ]
    return max(numbers, default=0) + 1


def _write_plan(db, current, *, dashboard_id: int, user_id: int, previous: str,
                revision: int, stored: dict) -> DashboardPlan:
    now = datetime.utcnow()
    version = _version_token(dashboard_id, revision)
    if current is None:
        current = DashboardPlan(
            dashboard_id=dashboard_id, version=version, schema_version=SCHEMA_VERSION,
            payload=stored, updated_at=now, updated_by=user_id,
        )
        db.add(current)
    else:
        current.version = version
        current.schema_version = SCHEMA_VERSION
        current.payload = stored
        current.updated_at = now
        current.updated_by = user_id
    db.add(DashboardPlanRevision(
        version=version, dashboard_id=dashboard_id, previous_version=previous,
        payload=stored, changed_at=now, changed_by=user_id,
        change_summary=f"v3 revision {revision}",
    ))
    return current


def _project(db, organization_id: int, plan: DashboardPlanV3) -> int:
    created = 0
    groups: dict[str, Category] = {}
    for line in plan.budgetLines:
        if line.group not in groups:
            groups[line.group], was_new = _ensure_group(db, organization_id, line.group)
            created += int(was_new)
        leaf, was_new = _ensure_leaf(db, organization_id, groups[line.group], line.category)
        created += int(was_new)
        _upsert_budget(db, organization_id, leaf, line)
    return created


def _category_type(name: str) -> str:
    return "revenue" if category_key(name) in REVENUE_KEYS else "expense"


def _ensure_group(db, organization_id: int, name: str) -> tuple[Category, bool]:
    found = (
        db.query(Category)
        .filter(
            Category.organization_id == organization_id,
            Category.parent_id.is_(None),
            Category.name == name,
        )
        .order_by(Category.id)
        .first()
    )
    if found is not None:
        return found, False
    row = Category(
        organization_id=organization_id, name=name, parent_id=None,
        category_type=_category_type(name),
    )
    db.add(row)
    db.flush()
    return row, True


def _ensure_leaf(db, organization_id: int, parent: Category, name: str) -> tuple[Category, bool]:
    key = category_key(name)
    children = (
        db.query(Category)
        .filter(Category.organization_id == organization_id, Category.parent_id == parent.id)
        .order_by(Category.id)
        .all()
    )
    for child in children:
        if child.name == name or category_key(child.name) == key:
            return child, False
    row = Category(
        organization_id=organization_id, name=name, parent_id=parent.id,
        category_type=_category_type(name),
    )
    db.add(row)
    db.flush()
    return row, True


def _upsert_budget(db, organization_id: int, leaf: Category, line: BudgetLineV3) -> None:
    year_text, month_text = line.month.split("-")
    year, month = int(year_text), int(month_text)
    key = category_key(line.category)
    rows = db.query(Budget).filter(
        Budget.organization_id == organization_id,
        Budget.year == year,
        Budget.month == month,
    ).all()
    matches = [
        row for row in rows
        if row.category_id == leaf.id or (
            row.category_id is None and category_key(row.category_name or "") == key
        )
    ]
    target = _latest(matches)
    if target is None:
        target = Budget(
            organization_id=organization_id, year=year, month=month,
            category_id=leaf.id,
        )
        db.add(target)
    target.category_id = leaf.id
    target.category_name = key
    target.budgeted_amount = line.amount
    target.updated_at = datetime.utcnow()
    db.flush()


def _latest(rows: list[Budget]) -> Budget | None:
    if not rows:
        return None
    return sorted(rows, key=lambda row: (row.updated_at or datetime.min, row.id or 0), reverse=True)[0]


def _stored_plan(current: DashboardPlan):
    if current.schema_version != SCHEMA_VERSION:
        return None
    try:
        return DashboardPlanV3.model_validate(current.payload).model_dump(mode="json")
    except ValidationError:
        return None


def _envelope(*, version: str, schema_version: int, plan, updated_at, dashboard_id: int | None = None) -> dict:
    revision = _parse_revision(version, dashboard_id)
    return {
        "revision": revision,
        "version": version,
        "schema_version": schema_version,
        "plan": plan,
        "updated_at": updated_at,
        "provider_calls": 0,
    }


def _iso(value):
    return value.isoformat() if value else None


def _integrity_error(exc: IntegrityError) -> DashboardError:
    text = str(getattr(exc, "orig", exc)).lower()
    if "dashboard_plan" in text:
        return DashboardError(409, "plan_conflict", "התוכנית השתנתה")
    return DashboardError(422, "invalid_plan", "לא ניתן להקרין את שורות התקציב")
