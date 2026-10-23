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
from ..read_memo import read_memo
from .service import DashboardError
from . import cash_statement, filing, forecast, liquidity, view_model

_MARKER = ("intercompany", "בין-חברתי", "בין חברתי")
# The explicit intercompany rule (see ``_intercompany``).
IC_CATEGORIES = frozenset({"intercompany", "transfers_out", "other_in", "bank_journal"})
IC_TOLERANCE = Decimal("0.01")
IC_WINDOW_DAYS = 4
IC_MAX_WINDOW_DAYS = 10
IC_MAX_ITEMS = 200
IC_RULE_HE = (
    "קיזוז בין-חברתי: יציאה בישות אחת מול כניסה בישות אחרת, באותו סכום (±0.01 ₪), "
    "עד {days} ימים זה מזה. שתי התנועות מתויקות כהעברה (בין-חברתי, העברה יוצאת, תקבול לבירור, "
    "זיכוי יומן) ולא כמכירה, ספק או עמלה. כל תנועה מקוזזת פעם אחת."
)
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
    primary organization treats those months as closed.

    The build only reads, so the bank rows, card accounts and coverage each entity's
    sections share are read once (``read_memo``)."""
    with read_memo(db):
        return _build_dashboard_view(db, dashboard, start, end, plan=plan)


def _build_dashboard_view(db, dashboard: ClientDashboard, start: date, end: date,
                          *, plan: dict | None = None) -> dict:
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
                entity_id=getattr(entity, "id", None) or None,
                with_budget=entity.organization_id == dashboard.primary_organization_id,
            ),
        })
    primary = next(
        (section["view"] for section in sections if section["role"] == "primary"),
        sections[0]["view"],
    )
    combined = _combine(db, sections, start, end, plan=plan)
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


def _combine(db, sections: list[dict], start: date, end: date, *, plan: dict | None = None) -> dict:
    views = [section["view"] for section in sections]
    org_ids = [section["organization_id"] for section in sections]
    labels = {section["organization_id"]: section["label"] for section in sections}
    removed = _intercompany(db, org_ids, start, end, plan=plan, labels=labels)
    removed["summary"]["rule"] = IC_RULE_HE.format(days=removed["summary"]["window_days"])
    position = liquidity.combine([
        {"label": section["label"], "liquidity": section["view"].get("liquidity")} for section in sections
    ])
    # The plan budget is the group's budget, so the combined forecast uses all of it.
    outlook = forecast.build_forecast(
        forecast.combined_pnl_months(sections), as_of=end, plan=plan,
        debt_service=position["debt_service"], budget_sums=view_model.plan_budget_sums(plan),
        opening_balance=position["balance"],
    )
    return {
        "pnl": _combine_pnl(views),
        "cashflow": _combine_cashflow(sections, removed),
        "budget_vs_actual": _combine_budget(views),
        "liquidity": position,
        "forecast": outlook,
        "cash_statement": cash_statement.combine(sections, outlook, removed["by_month"]),
        "intercompany_removed": removed["summary"],
        "sources": _combine_sources(sections),
        "provider_calls": 0,
    }


def _combine_sources(sections: list[dict]) -> dict:
    """Every entity's sources in one table, each row naming its entity."""
    items = []
    rule = None
    for section in sections:
        own = (section["view"] or {}).get("sources") or {}
        rule = rule or own.get("rule")
        items.extend({**item, "entity": section["label"]} for item in own.get("items") or [])
    return {
        "status": "ready" if items else "unknown",
        "items": items,
        "stale_count": sum(1 for item in items if item.get("status") == "stale"),
        "aging_count": sum(1 for item in items if item.get("status") == "aging"),
        "rule": rule,
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


def _combine_cashflow(sections: list[dict], removed: dict) -> dict:
    """Each month labels which entities it sums (``scope_label``): a month only the chef
    has bank rows in is the chef's alone, and a month no entity has rows in is unknown,
    not the zeros a single entity's cash flow fills in."""
    views = [section["view"] for section in sections]
    labels = [section["label"] for section in sections]
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
    known_by = cash_statement.known_entities(sections, sorted(slots))
    scope = cash_statement.scope_of(known_by, labels)
    with_statement = any((view.get("cash_statement") or {}).get("months") for view in views)
    cumulative = 0.0
    months_out = []
    for month in sorted(slots):
        if with_statement and not known_by[month]:
            months_out.append({
                "month": month, "inflows": None, "outflows": None, "net_flow": None,
                "cumulative": cumulative, "scope_label": "אין תנועות בנק",
            })
            continue
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
            "scope_label": scope[month]["label"] if month in scope else None,
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
            slot_meta = meta.setdefault(key, {
                "period_start": month.get("period_start"),
                "period_end": month.get("period_end"),
                "sources": set(),
                "labels": [],
                "blocked": False,
            })
            if month.get("source"):
                slot_meta["sources"].add(month["source"])
            if month.get("source_label") and month["source_label"] not in slot_meta["labels"]:
                slot_meta["labels"].append(month["source_label"])
            slot_meta["blocked"] = slot_meta["blocked"] or bool(month.get("blocked"))
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
    for month in sorted(index | meta):
        lines = []
        for ident in sorted(index.get(month, {}), key=lambda ident: tuple(str(part) for part in ident)):
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
        sources = meta[month]["sources"]
        months.append({
            "month": month,
            "period_start": meta[month]["period_start"],
            "period_end": meta[month]["period_end"],
            "source": (next(iter(sources)) if len(sources) == 1 else "mixed") if sources else None,
            "source_label": " / ".join(meta[month]["labels"]) or None,
            "blocked": meta[month]["blocked"],
            "categories": lines,
            # The totals of the combined month, the same shape as one entity's month.
            "totals": {
                "revenue": _total(lines, "revenue"),
                "costs": _total(lines, "cost"),
            },
        })
    return {
        "status": "ready",
        "has_budget": any(bool(section.get("has_budget")) for section in sections),
        "months": months,
        "message": "סכום התקציב והביצוע של ישויות הדשבורד.",
    }


def _total(lines: list[dict], kind: str) -> dict:
    rows = [line for line in lines if line["kind"] == kind]
    budgets = [line["budget"] for line in rows if line["budget"] is not None]
    actuals = [line["actual"] for line in rows if line["actual"] is not None]
    budget = round(sum(budgets), 2) if budgets else None
    actual = round(sum(actuals), 2) if actuals else None
    variance = None if budget is None or actual is None else round(actual - budget, 2)
    return {
        "budget": budget,
        "actual": actual,
        "variance": variance,
        "variance_pct": round(variance / budget * 100, 1) if variance is not None and budget else None,
    }


def _marked(description: str | None) -> bool:
    text = (description or "").casefold()
    return any(marker.casefold() in text for marker in _MARKER)


def intercompany_settings(plan: dict | None) -> dict:
    """``plan.intercompany``: ``windowDays`` (0–10, default 4) and ``accountIds``."""
    raw = (plan or {}).get("intercompany") if isinstance(plan, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    window = raw.get("windowDays", IC_WINDOW_DAYS)
    if isinstance(window, bool) or not isinstance(window, int) or not 0 <= window <= IC_MAX_WINDOW_DAYS:
        window = IC_WINDOW_DAYS
    accounts = raw.get("accountIds")
    accounts = {a for a in accounts if isinstance(a, int) and not isinstance(a, bool)} if isinstance(accounts, list) else set()
    return {"window_days": window, "account_ids": accounts}


def _candidates(db, org_ids: list[int], start: date, end: date, plan: dict | None, account_ids: set[int]):
    """The rows each entity's cash flow sums, filed, and limited to the configured accounts."""
    from ..bank_coverage import cashflow_row_objects
    from .activity_quality import confirmed_drop_ids
    plan = plan if isinstance(plan, dict) else {}
    decisions = plan.get("statusDecisions") if isinstance(plan.get("statusDecisions"), dict) else None
    rules = plan.get("statusRules") if isinstance(plan.get("statusRules"), list) else None
    out = []
    for org_id in dict.fromkeys(org_ids):
        rows = cashflow_row_objects(db, org_id, start, end)
        dropped = confirmed_drop_ids(rows, plan)
        rows = [row for row in rows if row.id not in dropped]
        # An organization none of whose accounts is configured keeps all its accounts.
        if account_ids and any(row.account_id in account_ids for row in rows):
            rows = [row for row in rows if row.account_id in account_ids]
        for row in rows:
            txn = filing.txn_from_row(row)
            category = filing.classify(txn, decisions=decisions, custom_rules=rules).category
            if category in IC_CATEGORIES or _marked(row.description):
                out.append((row, Decimal(str(row.amount)), category))
    return out


def _intercompany(db, org_ids: list[int], start: date, end: date, plan: dict | None = None,
                  labels: dict | None = None) -> dict:
    """Intercompany netting of the combined cash flow, an explicit rule:

    1. rows: what each entity's cash flow sums (BOOKED, not superseded, no card rows,
       confirmed duplicates dropped), on ``plan.intercompany.accountIds`` when the
       entity has rows on those accounts;
    2. eligible: the row is filed as a transfer (``IC_CATEGORIES``: intercompany,
       transfers_out, other_in, bank_journal), not as sales, supplier, fee, ...; or
       its description carries an intercompany marker;
    3. a pair: two entities, opposite signs, the same absolute amount (±0.01), dates at
       most ``windowDays`` apart (default 4, the tool's match);
    4. deterministic: outflows in (date, id) order each take the free inflow with the
       smallest date gap, then the lowest id. A row is used once.

    Each side is removed from its own month (an outflow on 31.8 paired with an
    inflow on 2.9 removes 31.8 from August's outflows and 2.9 from September's inflows).
    """
    settings = intercompany_settings(plan)
    empty = {
        "summary": {"pairs": 0, "inflows": 0.0, "outflows": 0.0, "amount": 0.0,
                    "window_days": settings["window_days"], "rule": IC_RULE_HE, "items": [],
                    "by_month": {}},
        "by_month": {},
    }
    if len(set(org_ids)) < 2:
        return empty
    labels = labels or {}
    rows = _candidates(db, org_ids, start, end, plan, settings["account_ids"])
    outs = sorted((item for item in rows if item[1] < 0), key=lambda item: (item[0].transaction_date, item[0].id))
    ins = [item for item in rows if item[1] > 0]
    used: set[int] = set()
    by_month: dict[str, dict] = {}
    items = []
    total = Decimal(0)
    for out_row, out_amount, out_category in outs:
        best = None
        for in_row, in_amount, in_category in ins:
            if in_row.id in used or in_row.organization_id == out_row.organization_id:
                continue
            if abs(abs(out_amount) - in_amount) > IC_TOLERANCE:
                continue
            gap = abs((in_row.transaction_date - out_row.transaction_date).days)
            if gap > settings["window_days"]:
                continue
            key = (gap, in_row.id)
            if best is None or key < best[0]:
                best = (key, in_row, in_amount)
        if best is None:
            continue
        _, in_row, in_amount = best
        used.add(in_row.id)
        out_month = out_row.transaction_date.strftime("%Y-%m")
        in_month = in_row.transaction_date.strftime("%Y-%m")
        by_month.setdefault(in_month, {"inflows": 0.0, "outflows": 0.0})["inflows"] += float(in_amount)
        by_month.setdefault(out_month, {"inflows": 0.0, "outflows": 0.0})["outflows"] += float(-out_amount)
        total += in_amount
        if len(items) < IC_MAX_ITEMS:
            items.append({
                "from": labels.get(out_row.organization_id),
                "to": labels.get(in_row.organization_id),
                "out_date": out_row.transaction_date.isoformat(),
                "in_date": in_row.transaction_date.isoformat(),
                "amount": float(in_amount),
                "days_apart": abs((in_row.transaction_date - out_row.transaction_date).days),
            })
    for slot in by_month.values():
        slot["inflows"] = round(slot["inflows"], 2)
        slot["outflows"] = round(slot["outflows"], 2)
    pairs = len(used)
    summary = dict(empty["summary"])
    summary.update({
        "pairs": pairs,
        "inflows": round(float(total), 2),
        "outflows": round(float(total), 2),
        "amount": round(float(total), 2),
        "items": items,
        "by_month": {month: dict(by_month[month]) for month in sorted(by_month)},
    })
    return {"summary": summary, "by_month": by_month}
