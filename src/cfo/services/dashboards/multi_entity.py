"""Per-entity and combined views for a dashboard that covers more than one organization.

``build_view`` stays the single-organization reader. This module calls it once
per ``dashboard_entities`` row and adds the pieces together. A viewer still has
to be allowed onto the dashboard by the route. Every entity on a multi-entity
dashboard must belong to the same office. No provider calls.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from ...models import BankTransaction, ClientDashboard, DashboardEntity, DashboardEntityAccount
from .. import bank_status
from ..office_access import classifying_office_id, office_manages
from .service import DashboardError
from . import view_model

_MARKER = ("intercompany", "בין-חברתי", "בין חברתי")
_PAIR_TOLERANCE = Decimal("0.005")
_PNL_FIELDS = ("total_revenue", "total_expenses", "net_income_before_tax")


def assert_same_office(db, dashboard: ClientDashboard, entities: list) -> int | None:
    """The office shared by every entity. One entity is always the same office."""
    if len(entities) <= 1:
        return dashboard.office_organization_id
    office_id = dashboard.office_organization_id
    if office_id is None:
        inferred = [classifying_office_id(db, entity.organization_id) for entity in entities]
        if any(item is None for item in inferred) or len(set(inferred)) != 1:
            raise DashboardError(
                422, "entity_office_mismatch", "ישות בדשבורד אינה שייכת לאותו משרד",
            )
        return inferred[0]
    for entity in entities:
        if entity.organization_id == office_id:
            continue
        if not office_manages(db, office_id, entity.organization_id):
            raise DashboardError(
                422, "entity_office_mismatch", "ישות בדשבורד אינה שייכת לאותו משרד",
            )
    return office_id


def build_dashboard_view(db, dashboard: ClientDashboard, start: date, end: date,
                         *, plan: dict | None = None) -> dict:
    """Every entity reads the dashboard plan. Filing decisions and rules carry their
    own ``organizationId``. ``booksClosedMonths`` has no organization, so only the
    primary organization treats those months as closed."""
    entities = (
        db.query(DashboardEntity)
        .filter_by(dashboard_id=dashboard.id)
        .order_by(DashboardEntity.id)
        .all()
    )
    if not entities:
        entities = [_Primary(dashboard)]
    office_id = assert_same_office(db, dashboard, entities)
    ordered = sorted(entities, key=lambda entity: (entity.role != "primary", entity.id or 0))
    sections = []
    for entity in ordered:
        sections.append({
            "organization_id": entity.organization_id,
            "label": entity.label,
            "role": entity.role,
            "accounts": _accounts(db, entity),
            "view": view_model.build_view(
                db, entity.organization_id, start, end,
                plan=_plan_for(plan, entity.organization_id == dashboard.primary_organization_id),
            ),
        })
    primary = next(
        (section["view"] for section in sections if section["role"] == "primary"),
        sections[0]["view"],
    )
    combined = _combine(db, sections, start, end)
    view = dict(primary)
    view["entities"] = sections
    view["combined"] = combined
    view["office_organization_id"] = office_id
    view["provider_calls"] = 0
    return view


def _plan_for(plan: dict | None, primary: bool) -> dict | None:
    if primary or not isinstance(plan, dict):
        return plan
    return {key: value for key, value in plan.items() if key != "booksClosedMonths"}


class _Primary:
    def __init__(self, dashboard: ClientDashboard):
        self.id = 0
        self.organization_id = dashboard.primary_organization_id
        self.label = dashboard.title
        self.role = "primary"


def _accounts(db, entity) -> list[dict]:
    if not getattr(entity, "id", None):
        return []
    rows = db.query(DashboardEntityAccount).filter_by(entity_id=entity.id).all()
    return [
        {"account_id": row.account_id, "display_label": row.display_label}
        for row in rows
    ]


def _combine(db, sections: list[dict], start: date, end: date) -> dict:
    views = [section["view"] for section in sections]
    org_ids = [section["organization_id"] for section in sections]
    removed = _intercompany(db, org_ids, start, end)
    return {
        "pnl": _combine_pnl(views),
        "cashflow": _combine_cashflow(views, removed),
        "budget_vs_actual": _combine_budget(views),
        "intercompany_removed": removed["summary"],
        "provider_calls": 0,
    }


def _combine_pnl(views: list[dict]) -> dict:
    parts = [view.get("pnl") or {} for view in views]
    unknown = {
        "status": "unknown",
        "basis": "unknown",
        "total_revenue": None,
        "total_expenses": None,
        "net_income_before_tax": None,
        "tax_expense": None,
        "message": "רווח והפסד משולב לא ידוע — לא לכל ישות יש ספרים בתקופה.",
    }
    if any(part.get("status") != "ready" for part in parts):
        return unknown
    totals = {}
    for field in _PNL_FIELDS:
        values = [part.get(field) for part in parts]
        if any(value is None for value in values):
            return unknown
        totals[field] = round(sum(float(value) for value in values), 2)
    bases = {part.get("basis") for part in parts}
    totals.update({
        "status": "ready",
        "basis": bases.pop() if len(bases) == 1 else "mixed",
        "tax_expense": None,
        "message": "סכום הרווח וההפסד של ישויות הדשבורד (כל ישות לפי המקור שלה בכל חודש). מס לא חושב.",
    })
    return totals


def _combine_cashflow(views: list[dict], removed: dict) -> dict:
    slots: dict[str, dict] = {}
    reported = 0
    for view in views:
        months = (view.get("cashflow") or {}).get("months") or []
        if not months:
            continue
        reported += 1
        for month in months:
            slot = slots.setdefault(month["month"], {"inflows": 0.0, "outflows": 0.0})
            slot["inflows"] += float(month.get("inflows") or 0)
            slot["outflows"] += float(month.get("outflows") or 0)
    if reported == 0:
        return {
            "status": "unknown",
            "months": [],
            "message": "אין תנועות בנק בישויות הדשבורד בחלון הזה.",
        }
    cumulative = 0.0
    months_out = []
    for month in sorted(slots):
        cut = removed["by_month"].get(month, {"inflows": 0.0, "outflows": 0.0})
        inflows = round(slots[month]["inflows"] - cut["inflows"], 2)
        outflows = round(slots[month]["outflows"] - cut["outflows"], 2)
        if inflows < -0.001 or outflows < -0.001:
            return {
                "status": "unknown",
                "months": [],
                "message": "קיזוז בין-חברתי חרג מסכום התזרים — המשולב לא מוצג.",
            }
        net = round(inflows - outflows, 2)
        cumulative = round(cumulative + net, 2)
        months_out.append({
            "month": month,
            "inflows": inflows,
            "outflows": outflows,
            "net_flow": net,
            "cumulative": cumulative,
        })
    return {"status": "ready", "months": months_out, "message": None}


def _combine_budget(views: list[dict]) -> dict:
    sections = [view.get("budget_vs_actual") or {} for view in views]
    if any(section.get("status") != "ready" for section in sections):
        return {
            "status": "unknown",
            "has_budget": any(bool(section.get("has_budget")) for section in sections),
            "months": [],
            "message": "ביצוע משולב לא ידוע — לא לכל ישות יש ספרים בתקופה.",
        }
    index: dict[str, dict] = {}
    meta: dict[str, dict] = {}
    for section in sections:
        for month in section.get("months") or []:
            key = month.get("month")
            meta.setdefault(key, {
                "period_start": month.get("period_start"),
                "period_end": month.get("period_end"),
            })
            bucket = index.setdefault(key, {})
            for line in month.get("categories") or []:
                ident = (line.get("kind"), line.get("category"))
                slot = bucket.setdefault(ident, {
                    "kind": line.get("kind"),
                    "category": line.get("category"),
                    "category_he": line.get("category_he"),
                    "budgets": [],
                    "actuals": [],
                })
                if line.get("budget") is not None:
                    slot["budgets"].append(float(line["budget"]))
                if line.get("actual") is not None:
                    slot["actuals"].append(float(line["actual"]))
    months = []
    for month in sorted(index):
        lines = []
        for ident in sorted(index[month]):
            slot = index[month][ident]
            budget = round(sum(slot["budgets"]), 2) if slot["budgets"] else None
            actual = round(sum(slot["actuals"]), 2) if slot["actuals"] else None
            variance = None if budget is None or actual is None else round(actual - budget, 2)
            variance_pct = None
            if variance is not None and budget:
                variance_pct = round(variance / budget * 100, 1)
            lines.append({
                "kind": slot["kind"],
                "category": slot["category"],
                "category_he": slot["category_he"],
                "budget": budget,
                "actual": actual,
                "variance": variance,
                "variance_pct": variance_pct,
            })
        months.append({
            "month": month,
            "period_start": meta[month]["period_start"],
            "period_end": meta[month]["period_end"],
            "categories": lines,
        })
    return {
        "status": "ready",
        "has_budget": any(bool(section.get("has_budget")) for section in sections),
        "months": months,
        "message": "סכום התקציב והביצוע של ישויות הדשבורד.",
    }


def _marked(description: str | None) -> bool:
    text = (description or "").casefold()
    return any(marker.casefold() in text for marker in _MARKER)


def _intercompany(db, org_ids: list[int], start: date, end: date) -> dict:
    empty = {"summary": {"pairs": 0, "inflows": 0.0, "outflows": 0.0}, "by_month": {}}
    if len(org_ids) < 2:
        return empty
    rows = db.query(BankTransaction).filter(
        BankTransaction.organization_id.in_(org_ids),
        BankTransaction.transaction_date >= start,
        BankTransaction.transaction_date <= end,
    ).all()
    # Same basis as the per-entity cash flow: BOOKED, not superseded, no card rows.
    card_ids: set[int] = set()
    for org_id in set(org_ids):
        card_ids |= bank_status.card_account_ids(db, org_id)
    marked = [
        row for row in rows
        if _marked(row.description) and bank_status.counts_in_cash_flow(row, card_ids)
    ]
    used: set[int] = set()
    by_month: dict[str, dict] = {}
    pairs = 0
    inflows = 0.0
    outflows = 0.0
    for index, left in enumerate(marked):
        if left.id in used:
            continue
        for right in marked[index + 1:]:
            if right.id in used or left.organization_id == right.organization_id:
                continue
            if left.transaction_date != right.transaction_date:
                continue
            left_amount = Decimal(str(left.amount))
            right_amount = Decimal(str(right.amount))
            if left_amount * right_amount >= 0:
                continue
            if abs(abs(left_amount) - abs(right_amount)) > _PAIR_TOLERANCE:
                continue
            used.add(left.id)
            used.add(right.id)
            pairs += 1
            month = left.transaction_date.strftime("%Y-%m")
            slot = by_month.setdefault(month, {"inflows": 0.0, "outflows": 0.0})
            positive = left_amount if left_amount > 0 else right_amount
            negative = right_amount if right_amount < 0 else left_amount
            slot["inflows"] = round(slot["inflows"] + float(positive), 2)
            slot["outflows"] = round(slot["outflows"] + float(abs(negative)), 2)
            inflows = round(inflows + float(positive), 2)
            outflows = round(outflows + float(abs(negative)), 2)
            break
    return {
        "summary": {"pairs": pairs, "inflows": inflows, "outflows": outflows},
        "by_month": by_month,
    }
