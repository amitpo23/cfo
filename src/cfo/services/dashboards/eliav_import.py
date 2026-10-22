"""One-time import of an Eliav-tool plan into ``dashboard_plans`` and ``budgets``.

The tool export keeps quantity × rate on each budget line. The import writes
those lines in the one canonical plan format, the one the dashboard editor saves
through ``PUT /plan``::

    {"id", "label", "category", "kind", "months": {"YYYY-MM": {"quantity", "rate"}}}

``category`` is a P&L category key (``plan_budget.budget_catalog``), chosen from
the line's Eliav group (``GROUPS``) unless the line names one itself. Only the
active scenario (``statusParameters.scenario``, default ``base``) becomes
``months``. Cells of any other scenario are kept, not projected, under
``eliavImport.otherScenarios[scenario][line_id]``. The ``budgets`` table receives
the same projection ``PUT /plan`` writes (``plan_budget.project_budget_lines``).
The finished payload goes through the same validators as ``PUT /plan``, so the
editor can save over an imported plan.

Dry-run is the default. Nothing here calls SUMIT, Financy, or Open Finance, and
nothing is written to the books tables.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation

from ...models import (
    AuditLog, BankTransaction, Budget, ClientDashboard, DashboardEntity,
    DashboardPlan, DashboardPlanRevision,
)
from .budget import category_key, category_label
from .filing import DECISION_CATEGORIES
from .plan_budget import (
    FINANCING_CATEGORIES, PLAN_NOTE_PREFIX, PlanBudgetError, budget_catalog,
    project_budget_lines, validate_budget_lines,
)
from .service import PLAN_LIMIT_BYTES, DashboardError, validate_filing_payload

MAX_DECISIONS = 1000
MAX_RULES = 200
MAX_AMOUNT = Decimal("1000000000")
MATCH_TOLERANCE = Decimal("0.005")
MONEY = Decimal("0.01")
DEFAULT_TOLERANCE = Decimal("1")

ENVELOPE_KEYS = {"version", "exportedAt", "data"}
DATA_KEYS = {
    "budgets", "customLines", "lines", "budgetLines", "statusDecisions",
    "statusRules", "statusParameters", "manual", "openingBalance", "forecast",
    "facilities", "balanceAnchors", "rateAssumptions", "incomingAllocations",
    "invoiceDecisions", "discountInvoiceLinks", "payroll", "bankDecisions",
}
PASSTHROUGH = (
    "manual", "openingBalance", "forecast", "facilities", "balanceAnchors",
    "rateAssumptions", "incomingAllocations", "invoiceDecisions",
    "discountInvoiceLinks",
)
LINE_KEYS = {"id", "label", "group", "kind", "activity", "unit", "custom", "category", "defaults"}
CELL_KEYS = {"quantity", "rate"}
DECISION_KEYS = {
    "category", "action", "ruleCategory", "organizationId", "date", "amount",
    "source", "note", "updatedAt", "previous",
}
DECISION_REQUIRED = {"category", "note", "organizationId", "date", "amount"}
RULE_KEYS = {
    "id", "contains", "field", "direction", "organizationId", "category", "updatedAt",
}
RULE_REQUIRED = RULE_KEYS - {"updatedAt"}
PARAMETER_KEYS = {
    "scenario", "horizon", "growth", "vat",
    # the tool's own names (lib/budget-model.js DEFAULT_PARAMETERS)
    "horizonMonths", "revenueGrowthPct", "costGrowthPct", "vatRate",
}
PAYROLL_KEYS = {"id", "label", "monthly", "group"}
# Same field and direction values as the filing rules (filing._custom_match).
RULE_FIELDS = {"description", "counterparty", "any"}
RULE_DIRECTIONS = {"in", "out", "both"}
# Eliav line kind -> plan_budget kind. Principal, CAPEX and funding are cash, not P&L.
LINE_KINDS = {
    "revenue": "revenue", "expense": "cost", "interest": "cost", "depreciation": "cost",
    "principal": "financing", "capex": "financing", "funding": "financing",
}
# A kind that fixes the category whatever the group is.
KIND_CATEGORY = {
    "interest": "interest_expense",
    "depreciation": "depreciation",
    "principal": "loan_principal",
    "capex": "capex",
    "funding": "funding",
}
# Seed lines whose category is not their group's (the tool's COMPARISON_ROWS).
SEED_CATEGORY = {"overhead_bank_fees": "bank_fees"}
SEED_SCENARIO = "בסיס"
# Eliav group -> default P&L category key. A line may name its own ``category``.
GROUPS = {
    "הכנסות": "sales",
    "כוח אדם": "salaries",
    "רכבים": "vehicle",
    "ספקים": "cost_of_goods",
    "הנהלה וכלליות": "other",
    "השקעות ומימון": "interest_expense",
}
CATALOG = {row["key"]: row["kind"] for row in budget_catalog()}
BUDGET_KEY = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])\|([^|\s]{1,40})$")
DATE_KEY = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
MONTH_KEY = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class ImportRejected(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _reject(code: str, message: str):
    raise ImportRejected(code, message)


def canonical_hash(document: dict) -> str:
    encoded = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _as_decimal(value, *, label: str, allow_negative: bool) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        _reject("invalid_amount", f"{label} אינו מספר")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _reject("invalid_amount", f"{label} אינו מספר")
    if not amount.is_finite():
        _reject("invalid_amount", f"{label} אינו מספר")
    if not allow_negative and amount < 0:
        _reject("invalid_amount", f"{label} לא יכול להיות שלילי")
    if abs(amount) > MAX_AMOUNT:
        _reject("invalid_amount", f"{label} גדול מהמותר")
    return amount


def unwrap(document: dict) -> tuple[str | None, dict]:
    if not isinstance(document, dict):
        _reject("invalid_plan", "התוכנית חייבת להיות אובייקט JSON")
    if "data" in document:
        unknown = set(document) - ENVELOPE_KEYS
        if unknown:
            _reject("unknown_field", f"שדה לא מוכר: {sorted(unknown)[0]}")
        data = document["data"]
        if not isinstance(data, dict):
            _reject("invalid_plan", "data חייב להיות אובייקט")
        version = document.get("version")
        if version is not None and not isinstance(version, str):
            _reject("invalid_plan", "version חייב להיות טקסט")
        exported = document.get("exportedAt")
        if exported is not None and not isinstance(exported, str):
            _reject("invalid_plan", "exportedAt חייב להיות טקסט")
        return version, data
    unknown = set(document) - DATA_KEYS
    if unknown:
        _reject("unknown_field", f"שדה לא מוכר: {sorted(unknown)[0]}")
    return None, document


def _parameters(data: dict) -> dict:
    raw = data.get("statusParameters")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        _reject("invalid_plan", "statusParameters חייב להיות אובייקט")
    unknown = set(raw) - PARAMETER_KEYS
    if unknown:
        _reject("unknown_field", f"שדה לא מוכר: statusParameters.{sorted(unknown)[0]}")
    return raw


def _line(raw: dict, *, custom: bool) -> dict:
    if not isinstance(raw, dict):
        _reject("invalid_plan", "שורת תקציב חייבת להיות אובייקט")
    unknown = set(raw) - LINE_KEYS
    if unknown:
        _reject("unknown_field", f"שדה לא מוכר בשורה: {sorted(unknown)[0]}")
    line_id = raw.get("id")
    label = raw.get("label")
    group = raw.get("group")
    kind = raw.get("kind")
    if not isinstance(line_id, str) or not line_id.strip():
        _reject("invalid_plan", "חסר מזהה שורה")
    if not isinstance(label, str) or not label.strip():
        _reject("invalid_plan", f"חסרה תווית לשורה {line_id}")
    if group not in GROUPS:
        _reject("unknown_group", f"קבוצה לא מוכרת: {group}")
    if kind not in LINE_KINDS:
        _reject("invalid_plan", f"סוג שורה לא מוכר: {kind}")
    category = raw.get("category")
    if category is None:
        category = KIND_CATEGORY.get(kind) or GROUPS[group]
    if not isinstance(category, str) or category_key(category) not in CATALOG:
        _reject("unknown_category", f"קטגוריית תקציב לא מוכרת בשורה {line_id}")
    category = category_key(category)
    if CATALOG[category] != LINE_KINDS[kind]:
        _reject("invalid_plan", f"סוג השורה {line_id} לא תואם לקטגוריה {category}")
    activity = raw.get("activity") or "operating"
    unit = raw.get("unit") or "יחידה"
    if not isinstance(activity, str) or not isinstance(unit, str):
        _reject("invalid_plan", "activity ו-unit חייבים להיות טקסט")
    defaults = raw.get("defaults")
    if defaults is not None:
        if not isinstance(defaults, dict) or set(defaults) - CELL_KEYS:
            _reject("unknown_field", f"ברירת מחדל לא תקינה בשורה {line_id}")
        for value in defaults.values():
            if value is not None:
                _as_decimal(value, label="defaults", allow_negative=False)
    out = {
        "id": line_id.strip(),
        "label": label.strip(),
        "group": group,
        "kind": kind,
        "activity": activity,
        "unit": unit,
        "custom": bool(custom or raw.get("custom")),
        "category": category,
        "cells": {},
    }
    if defaults is not None:
        out["defaults"] = dict(defaults)
    return out


def _apply_cell(line: dict, key: str, cell) -> None:
    if not BUDGET_KEY.fullmatch(str(key)):
        _reject("invalid_plan", f"מפתח תקציב לא תקין: {key}")
    if not isinstance(cell, dict) or set(cell) - CELL_KEYS:
        _reject("unknown_field", "תא תקציב חייב להכיל quantity ו-rate בלבד")
    if "quantity" not in cell or "rate" not in cell:
        _reject("invalid_plan", "בתא תקציב חסרים quantity או rate")
    quantity = _as_decimal(cell["quantity"], label="quantity", allow_negative=False)
    rate = _as_decimal(cell["rate"], label="rate", allow_negative=False)
    if quantity * rate > MAX_AMOUNT:
        _reject("invalid_amount", "quantity×rate גדול מהמותר")
    line["cells"][str(key)] = {"quantity": cell["quantity"], "rate": cell["rate"]}


def _catalog(data: dict) -> dict[str, dict]:
    if data.get("budgets") and data.get("budgetLines"):
        _reject("invalid_plan", "לא מייבאים budgets ו-budgetLines באותו קובץ")
    catalog: dict[str, dict] = {}
    for source, custom in (("lines", False), ("customLines", True)):
        raw_lines = data.get(source) or []
        if not isinstance(raw_lines, list):
            _reject("invalid_plan", f"{source} חייב להיות רשימה")
        for raw in raw_lines:
            line = _line(raw, custom=custom)
            if line["id"] in catalog:
                _reject("invalid_plan", f"שורה כפולה: {line['id']}")
            catalog[line["id"]] = line
    mapped = data.get("budgetLines") or []
    if not isinstance(mapped, list):
        _reject("invalid_plan", "budgetLines חייב להיות רשימה")
    for raw in mapped:
        if not isinstance(raw, dict):
            _reject("invalid_plan", "שורת budgetLines חייבת להיות אובייקט")
        unknown = set(raw) - (LINE_KEYS | {"cells"})
        if unknown:
            _reject("unknown_field", f"שדה לא מוכר בשורה: {sorted(unknown)[0]}")
        line = _line(raw, custom=bool(raw.get("custom")))
        if line["id"] in catalog:
            _reject("invalid_plan", f"שורה כפולה: {line['id']}")
        cells = raw.get("cells") or {}
        if not isinstance(cells, dict):
            _reject("invalid_plan", "cells חייב להיות אובייקט")
        for key, cell in cells.items():
            _apply_cell(line, key, cell)
        catalog[line["id"]] = line
    budgets = data.get("budgets") or {}
    if budgets is None:
        budgets = {}
    if not isinstance(budgets, dict):
        _reject("invalid_plan", "budgets חייב להיות אובייקט")
    for key, lines in budgets.items():
        if not isinstance(lines, dict):
            _reject("invalid_plan", "תקציב לחודש חייב להיות אובייקט")
        for line_id, cell in lines.items():
            line = catalog.get(line_id)
            if line is None:
                _reject("unknown_line", f"שורת תקציב לא מוכרת: {line_id}")
            _apply_cell(line, str(key), cell)
    return catalog


def _scenario_months(catalog: dict[str, dict], scenario: str) -> list[str]:
    months = set()
    for line in catalog.values():
        for key in line["cells"]:
            month, _, cell_scenario = key.partition("|")
            if cell_scenario == scenario:
                months.add(month)
    return sorted(months)


def _payroll(catalog: dict[str, dict], data: dict, scenario: str, months: list[str]) -> None:
    payroll = data.get("payroll")
    if payroll is None:
        return
    if not isinstance(payroll, list):
        _reject("invalid_plan", "payroll חייב להיות רשימה")
    for raw in payroll:
        if not isinstance(raw, dict) or set(raw) - PAYROLL_KEYS:
            _reject("unknown_field", "שורת שכר מכילה שדה לא מוכר")
        if not {"id", "label", "monthly"} <= set(raw):
            _reject("invalid_plan", "שורת שכר חסרה")
        group = raw.get("group") or "כוח אדם"
        line = catalog.get(raw["id"])
        if line is None:
            line = _line({
                "id": raw["id"],
                "label": raw["label"],
                "group": group,
                "kind": "expense",
                "activity": "payroll",
                "unit": "חודש",
            }, custom=False)
            catalog[line["id"]] = line
        elif line["group"] != group:
            _reject("invalid_plan", f"שורת השכר {line['id']} בקבוצה אחרת")
        _as_decimal(raw["monthly"], label="payroll", allow_negative=False)
        for month in months:
            cell_key = f"{month}|{scenario}"
            if cell_key in line["cells"]:
                continue
            line["cells"][cell_key] = {"quantity": 1, "rate": raw["monthly"]}


def _decisions(data: dict) -> dict:
    raw = data.get("statusDecisions") or {}
    if not isinstance(raw, dict):
        _reject("invalid_plan", "statusDecisions חייב להיות אובייקט")
    if len(raw) > MAX_DECISIONS:
        _reject("too_many", "יותר מ-1000 החלטות")
    clean = {}
    for key, value in raw.items():
        if not str(key).isdigit():
            _reject("invalid_plan", "מזהה החלטה חייב להיות מזהה תנועת בנק")
        if not isinstance(value, dict) or set(value) - DECISION_KEYS:
            _reject("unknown_field", "החלטה מכילה שדה לא מוכר")
        missing = DECISION_REQUIRED - set(value)
        if missing:
            _reject("invalid_plan", f"החלטה חסרה שדה: {sorted(missing)[0]}")
        if not isinstance(value.get("category"), str) or not value["category"].strip():
            _reject("invalid_plan", "קטגוריית החלטה חסרה")
        if not isinstance(value.get("note"), str):
            _reject("invalid_plan", "הערת החלטה חייבת להיות טקסט")
        org_id = value.get("organizationId")
        if isinstance(org_id, bool) or not isinstance(org_id, int):
            _reject("invalid_plan", "organizationId חייב להיות מספר")
        if not DATE_KEY.fullmatch(str(value.get("date"))):
            _reject("invalid_plan", "תאריך החלטה לא תקין")
        _as_decimal(value.get("amount"), label="amount", allow_negative=True)
        previous = value.get("previous", None)
        if "previous" in value and previous is not None:
            if not isinstance(previous, dict) or set(previous) - (DECISION_KEYS - {"previous"}):
                _reject("unknown_field", "previous מכיל שדה לא מוכר")
        clean[str(int(key))] = dict(value)
    return clean


def _rules(data: dict) -> list:
    raw = data.get("statusRules") or []
    if not isinstance(raw, list):
        _reject("invalid_plan", "statusRules חייב להיות רשימה")
    if len(raw) > MAX_RULES:
        _reject("too_many", "יותר מ-200 כללים")
    clean = []
    for rule in raw:
        if not isinstance(rule, dict) or set(rule) - RULE_KEYS:
            _reject("unknown_field", "כלל מכיל שדה לא מוכר")
        missing = RULE_REQUIRED - set(rule)
        if missing:
            _reject("invalid_plan", f"כלל חסר שדה: {sorted(missing)[0]}")
        if rule.get("field") not in RULE_FIELDS:
            _reject("invalid_plan", "שדה הכלל אינו מוכר")
        if rule.get("direction") not in RULE_DIRECTIONS:
            _reject("invalid_plan", "כיוון הכלל אינו מוכר")
        if isinstance(rule.get("organizationId"), bool) or not isinstance(rule.get("organizationId"), int):
            _reject("invalid_plan", "organizationId בכלל חייב להיות מספר")
        if not isinstance(rule.get("contains"), str) or not rule["contains"]:
            _reject("invalid_plan", "כלל בלי טקסט לחיפוש")
        if rule.get("category") not in DECISION_CATEGORIES:
            _reject("unknown_category", f"קטגוריית הכלל אינה מוכרת: {rule.get('category')}")
        clean.append(dict(rule))
    return clean


def monthly_totals(lines: list[dict]) -> list[dict]:
    """Sum quantity × rate per category per month over canonical plan lines."""
    totals: dict[tuple[str, str], Decimal] = {}
    for line in lines:
        key = category_key(str(line.get("category") or ""))
        if key in FINANCING_CATEGORIES:
            continue  # not projected to ``budgets``
        for month, cell in (line.get("months") or {}).items():
            amount = (
                _as_decimal(cell["quantity"], label="quantity", allow_negative=False)
                * _as_decimal(cell["rate"], label="rate", allow_negative=False)
            )
            totals[(str(month), key)] = totals.get((str(month), key), Decimal("0")) + amount
    return [
        {
            "month": month,
            "category": key,
            "category_he": category_label(key),
            "amount": f"{amount.quantize(MONEY):.2f}",
        }
        for (month, key), amount in sorted(totals.items())
    ]


def _canonical_lines(catalog: dict[str, dict], scenario: str) -> tuple[list[dict], dict, dict]:
    """Split each line into the canonical line, its Eliav detail, and other-scenario cells."""
    lines, detail, others = [], {}, {}
    for line in sorted(catalog.values(), key=lambda row: row["id"]):
        months = {}
        for key, cell in sorted(line["cells"].items()):
            month, _, cell_scenario = key.partition("|")
            if cell_scenario == scenario:
                months[month] = cell
            else:
                others.setdefault(cell_scenario, {}).setdefault(line["id"], {})[month] = cell
        lines.append({
            "id": line["id"],
            "label": line["label"],
            "category": line["category"],
            "kind": CATALOG[line["category"]],
            "months": months,
            # display only; PUT /plan ignores them and the editor keeps them
            "group": line["group"],
            "unit": line["unit"],
        })
        detail[line["id"]] = {
            "group": line["group"],
            "kind": line["kind"],
            "activity": line["activity"],
            "unit": line["unit"],
            "custom": line["custom"],
        }
        if "defaults" in line:
            detail[line["id"]]["defaults"] = line["defaults"]
    return lines, detail, others


def _entity_org_ids(db, dashboard: ClientDashboard) -> set[int]:
    rows = db.query(DashboardEntity).filter_by(dashboard_id=dashboard.id).all()
    org_ids = {row.organization_id for row in rows}
    org_ids.add(dashboard.primary_organization_id)
    return org_ids


def _match_decisions(db, org_ids: set[int], decisions: dict) -> tuple[dict, list]:
    applied = {}
    rejected = []
    for key, decision in decisions.items():
        if decision["category"] not in DECISION_CATEGORIES:
            reason = "unknown_category"
        else:
            reason = _mismatch(db.get(BankTransaction, int(key)), decision, org_ids)
        if reason is None:
            applied[key] = decision
            continue
        rejected.append({
            "transaction_id": key,
            "reason": reason,
            "category": decision.get("category"),
            "note": decision.get("note"),
        })
    return applied, rejected


def _mismatch(transaction, decision: dict, org_ids: set[int]) -> str | None:
    if transaction is None:
        return "not_found"
    if decision["organizationId"] not in org_ids or transaction.organization_id not in org_ids:
        return "organization_mismatch"
    if transaction.organization_id != decision["organizationId"]:
        return "organization_mismatch"
    if transaction.transaction_date.isoformat() != decision["date"]:
        return "date_mismatch"
    delta = abs(Decimal(str(transaction.amount)) - Decimal(str(decision["amount"])))
    if delta > MATCH_TOLERANCE:
        return "amount_mismatch"
    return None


def _build_payload(data: dict, *, source_version: str | None, applied: dict, rejected: list, rules: list) -> tuple[dict, str]:
    _check_known(data)
    parameters = _parameters(data)
    scenario = parameters.get("scenario") or "base"
    if not isinstance(scenario, str) or not scenario:
        _reject("invalid_plan", "תרחיש לא תקין")
    catalog = _catalog(data)
    months = _scenario_months(catalog, scenario)
    _payroll(catalog, data, scenario, months)
    lines, detail, others = _canonical_lines(catalog, scenario)
    payload = {
        "source": "eliav-tool",
        "sourceVersion": source_version,
        "budgetLines": lines,
        "statusDecisions": applied,
        "statusDecisionExceptions": rejected,
        "statusRules": rules,
        "statusParameters": parameters,
        "eliavImport": {
            "scenario": scenario,
            "groups": dict(GROUPS),
            "lines": detail,
            "otherScenarios": others,
        },
    }
    for key in PASSTHROUGH:
        if key in data:
            payload[key] = data[key]
    if "payroll" in data:
        payload["payroll"] = data["payroll"]
    encoded = json.dumps(payload, ensure_ascii=False, default=str)
    if len(encoded.encode()) > 1_048_576:
        _reject("plan_too_large", "התוכנית גדולה ממגבלת המגה-בייט")
    return payload, scenario


def _editor_accepts(payload: dict) -> list[dict]:
    """The checks ``PUT /plan`` runs. An import the editor could not save is refused."""
    if len(json.dumps(payload, ensure_ascii=False, default=str).encode()) > PLAN_LIMIT_BYTES:
        _reject("plan_too_large", "התוכנית גדולה ממגבלת המגה-בייט")
    try:
        validate_filing_payload(payload)
        lines = validate_budget_lines(payload)
    except DashboardError as exc:
        _reject("invalid_plan", exc.message_he)
    except PlanBudgetError as exc:
        _reject("invalid_plan", exc.message_he)
    return lines or []


def _check_known(data: dict) -> None:
    unknown = set(data) - DATA_KEYS
    if unknown:
        _reject("unknown_field", f"שדה לא מוכר: {sorted(unknown)[0]}")


def _money_map(rows: list[dict]) -> dict[tuple[str, str], Decimal]:
    return {
        (row["month"], row["category"]): Decimal(row["amount"])
        for row in rows
    }


def _stored_budget_map(db, organization_id: int) -> dict[tuple[str, str], Decimal]:
    """Plan-owned ``budgets`` rows, keyed by month and category key."""
    found = {}
    for budget in db.query(Budget).filter(
        Budget.organization_id == organization_id,
        Budget.notes.like(f"{PLAN_NOTE_PREFIX}%"),
    ).all():
        key = (f"{budget.year:04d}-{budget.month:02d}", category_key(budget.category_name or ""))
        found[key] = found.get(key, Decimal("0")) + Decimal(str(budget.budgeted_amount)).quantize(MONEY)
    return found


def _diff(before: dict, after: list[dict]) -> list[dict]:
    after_map = _money_map(after)
    rows = []
    for key in sorted(set(before) | set(after_map)):
        previous = before.get(key)
        nxt = after_map.get(key)
        if previous == nxt:
            continue
        month, category = key
        rows.append({
            "month": month,
            "category": category,
            "before": None if previous is None else f"{previous:.2f}",
            "after": None if nxt is None else f"{nxt:.2f}",
        })
    return rows


def _current_revision(db, current: DashboardPlan | None):
    if current is None:
        return None
    return db.get(DashboardPlanRevision, current.version)


def _same_hash(revision, digest: str) -> bool:
    if revision is None or not revision.change_summary:
        return False
    return f"sha256:{digest}" in revision.change_summary


# With ``budget_only`` the import owns only these keys; filing decisions and
# rules already saved in Rezef are kept.
BUDGET_ONLY_KEYS = ("source", "sourceVersion", "budgetLines", "eliavImport")


def prepare_import(db, dashboard_id: int, document: dict, *, budget_only: bool = False) -> dict:
    """Validate and diff. Does not write."""
    dashboard = db.get(ClientDashboard, dashboard_id)
    if dashboard is None:
        _reject("dashboard_not_found", "הדשבורד לא נמצא")
    source_version, data = unwrap(document)
    _check_known(data)
    decisions = _decisions(data)
    rules = _rules(data)
    applied, rejected = _match_decisions(db, _entity_org_ids(db, dashboard), decisions)
    payload, scenario = _build_payload(
        data, source_version=source_version, applied=applied, rejected=rejected, rules=rules,
    )
    current = db.get(DashboardPlan, dashboard.id)
    existing = current.payload if current is not None and isinstance(current.payload, dict) else {}
    if budget_only:
        owned = {key: payload[key] for key in BUDGET_ONLY_KEYS if key in payload}
        parameters = existing.get("statusParameters")
        if isinstance(parameters, dict) or payload.get("statusParameters"):
            owned["statusParameters"] = {
                **(parameters if isinstance(parameters, dict) else {}),
                **(payload.get("statusParameters") or {}),
            }
        payload = owned
    if existing:
        # Keys the import does not own (booksClosedMonths, dedupePairs, ...) stay.
        payload = {**existing, **payload}
        payload.pop("schemaVersion", None)
    lines = _editor_accepts(payload)
    totals = monthly_totals(payload["budgetLines"])
    digest = canonical_hash(document)
    revision = _current_revision(db, current)
    idempotent = _same_hash(revision, digest)
    before = {} if idempotent else _stored_budget_map(db, dashboard.primary_organization_id)
    return {
        "dashboard": dashboard,
        "payload": payload,
        "scenario": scenario,
        "lines": lines,
        "totals": totals,
        "digest": digest,
        "source_version": source_version,
        "idempotent": idempotent,
        "current": current,
        "applied": applied,
        "rejected": rejected,
        "rules": rules,
        "budget_diff": [] if idempotent else _diff(before, totals),
        "budget_only": budget_only,
    }


def _result(prepared: dict, *, applied: bool) -> dict:
    return {
        "dashboard_id": prepared["dashboard"].id,
        "input_sha256": prepared["digest"],
        "source_version": prepared["source_version"],
        "idempotent": prepared["idempotent"],
        "applied": applied and not prepared["idempotent"],
        "budget_lines": len(prepared["payload"]["budgetLines"]),
        "scenario": prepared["scenario"],
        "other_scenarios": sorted(prepared["payload"]["eliavImport"]["otherScenarios"]),
        "budget_only": prepared.get("budget_only", False),
        "decisions_applied": len(prepared["applied"]),
        "decisions_rejected": len(prepared["rejected"]),
        "rules": len(prepared["rules"]),
        "rejected": prepared["rejected"],
        "monthly_totals": prepared["totals"],
        "budget_diff": prepared["budget_diff"],
        "provider_calls": 0,
    }


def import_plan(db, dashboard_id: int, document: dict, *, apply: bool,
                budget_only: bool = False) -> dict:
    prepared = prepare_import(db, dashboard_id, document, budget_only=budget_only)
    if not apply or prepared["idempotent"]:
        return _result(prepared, applied=False)
    _write(db, prepared)
    db.commit()
    return _result(prepared, applied=True)


def _write(db, prepared: dict) -> None:
    dashboard = prepared["dashboard"]
    version = secrets.token_hex(16)
    summary = (
        f"import from eliav tool {prepared['source_version'] or 'unknown'} "
        f"sha256:{prepared['digest']}"
    )
    now = datetime.utcnow()
    current = prepared["current"]
    if current is None:
        current = DashboardPlan(
            dashboard_id=dashboard.id,
            version=version,
            schema_version=2,
            payload=prepared["payload"],
            updated_at=now,
            updated_by=None,
        )
        db.add(current)
        previous = None
    else:
        previous = current.version
        current.version = version
        current.schema_version = 2
        current.payload = prepared["payload"]
        current.updated_at = now
        current.updated_by = None
    db.add(DashboardPlanRevision(
        version=version,
        dashboard_id=dashboard.id,
        previous_version=previous,
        payload=prepared["payload"],
        changed_at=now,
        changed_by=None,
        change_summary=summary,
    ))
    budget_rows = project_budget_lines(db, dashboard.primary_organization_id, version, prepared["lines"])
    db.add(AuditLog(
        user_id=None,
        organization_id=dashboard.primary_organization_id,
        action="IMPORT_DASHBOARD_PLAN",
        entity_type="DashboardPlan",
        entity_id=dashboard.id,
        details={
            "version": version,
            "input_sha256": prepared["digest"],
            "decisions_applied": len(prepared["applied"]),
            "decisions_rejected": len(prepared["rejected"]),
            "budget_rows": budget_rows,
            "provider_calls": 0,
        },
    ))


def computed_monthly_totals(db, dashboard_id: int) -> list[dict]:
    """Monthly category totals from the stored plan, quantity × rate."""
    plan = db.get(DashboardPlan, dashboard_id)
    if plan is None or not isinstance(plan.payload, dict):
        return []
    return monthly_totals(plan.payload.get("budgetLines") or [])


def _baseline_key(name: str) -> str:
    """A baseline category may be an Eliav group, a category key, or its Hebrew label."""
    return GROUPS.get(name) or category_key(name)


def reconcile(db, dashboard_id: int, baseline: dict, *, tolerance: Decimal = DEFAULT_TOLERANCE) -> dict:
    """Compare stored plan totals and the budgets table with a baseline.

    A row matches when the absolute gap is at most ``tolerance`` shekels
    (default ₪1) and the budgets table carries the same projection.
    A missing side stays missing — it is not treated as zero.
    """
    if not isinstance(baseline, dict) or set(baseline) - {"months"}:
        _reject("invalid_baseline", "הבסיס חייב להיות אובייקט עם months")
    months = baseline.get("months")
    if not isinstance(months, dict):
        _reject("invalid_baseline", "months חייב להיות אובייקט")
    expected: dict[tuple[str, str], Decimal] = {}
    for month, categories in months.items():
        if not MONTH_KEY.fullmatch(str(month)) or not isinstance(categories, dict):
            _reject("invalid_baseline", f"חודש לא תקין: {month}")
        for category, amount in categories.items():
            expected[(str(month), _baseline_key(str(category)))] = _as_decimal(
                amount, label=str(category), allow_negative=False,
            ).quantize(MONEY)
    dashboard = db.get(ClientDashboard, dashboard_id)
    if dashboard is None:
        _reject("dashboard_not_found", "הדשבורד לא נמצא")
    plan = db.get(DashboardPlan, dashboard_id)
    computed_rows = computed_monthly_totals(db, dashboard_id)
    computed = _money_map(computed_rows)
    table = _stored_budget_map(db, dashboard.primary_organization_id)
    rows = []
    ok = plan is not None
    for key in sorted(set(computed) | set(expected)):
        got = computed.get(key)
        base = expected.get(key)
        stored = table.get(key)
        delta = None if got is None or base is None else (got - base).quantize(MONEY)
        if got is None or base is None:
            status = "missing"
            ok = False
        elif abs(delta) > tolerance:
            status = "diff"
            ok = False
        elif stored is None or abs(stored - got) > MONEY:
            status = "projection_mismatch"
            ok = False
        else:
            status = "ok"
        month, category = key
        rows.append({
            "month": month,
            "category": category,
            "category_he": category_label(category),
            "computed": None if got is None else f"{got:.2f}",
            "baseline": None if base is None else f"{base:.2f}",
            "budgets_table": None if stored is None else f"{stored:.2f}",
            "delta": None if delta is None else f"{delta:.2f}",
            "status": status,
        })
    if plan is None:
        ok = False
    return {
        "ok": ok,
        "dashboard_id": dashboard_id,
        "tolerance": f"{tolerance.quantize(MONEY):.2f}",
        "rows": rows,
        "message": None if plan is not None else "אין תוכנית שמורה בדשבורד — אין סכום לחשב.",
        "provider_calls": 0,
    }


_STATUS_HE = {
    "ok": "תקין",
    "diff": "הפרש",
    "missing": "חסר",
    "projection_mismatch": "הטבלה לא תואמת את התוכנית",
}


def render_report(report: dict) -> str:
    lines = [f"התאמת תקציב חודשי (טולרנס {report['tolerance']} ₪)"]
    if report.get("message"):
        lines.append(report["message"])
    for row in report["rows"]:
        lines.append(
            f"{row['month']}  {row['category_he']}  "
            f"רצף {row['computed'] if row['computed'] is not None else '—'}  "
            f"בסיס {row['baseline'] if row['baseline'] is not None else '—'}  "
            f"הפרש {row['delta'] if row['delta'] is not None else '—'}  "
            f"{_STATUS_HE.get(row['status'], row['status'])}"
        )
    lines.append("תוצאה: תקין" if report["ok"] else "תוצאה: לא תואם")
    return "\n".join(lines)


SEED_DROPPED_KEYS = {"source", "note", "vehicle", "declaredMarketValue", "paymentTerms"}


def seed_export(seed: list, months: list[str], *, scenario: str = SEED_SCENARIO,
                version: str | None = None) -> dict:
    """An import document from the tool's ``lib/budget-seed.json``.

    Every seed line becomes a canonical line. A line with both a default
    quantity and a default rate gets that cell in every month of ``months``
    (the tool applies seed defaults to any month). Lines with a missing
    quantity or rate get no cells: the tool shows them as "no budget" too.
    Their partial defaults are kept under ``eliavImport.lines[id].defaults``.
    Seed-only fields (vehicle details, notes, payment terms) are not plan data
    and are dropped; the seed file stays the archive.
    """
    if not isinstance(seed, list):
        _reject("invalid_plan", "קובץ ה-seed חייב להיות רשימה")
    for month in months:
        if not MONTH_KEY.fullmatch(str(month)):
            _reject("invalid_plan", f"חודש לא תקין: {month}")
    lines, budgets = [], {}
    for raw in seed:
        if not isinstance(raw, dict):
            _reject("invalid_plan", "שורת seed חייבת להיות אובייקט")
        unknown = set(raw) - LINE_KEYS - CELL_KEYS - SEED_DROPPED_KEYS
        if unknown:
            _reject("unknown_field", f"שדה לא מוכר ב-seed: {sorted(unknown)[0]}")
        line = {key: raw[key] for key in ("id", "label", "group", "kind", "activity", "unit") if key in raw}
        if raw.get("id") in SEED_CATEGORY:
            line["category"] = SEED_CATEGORY[raw["id"]]
        quantity, rate = raw.get("quantity"), raw.get("rate")
        if quantity is not None and rate is not None:
            for month in months:
                budgets.setdefault(f"{month}|{scenario}", {})[raw["id"]] = {
                    "quantity": quantity, "rate": rate,
                }
        elif quantity is not None or rate is not None:
            line["defaults"] = {"quantity": quantity, "rate": rate}
        lines.append(line)
    digest = hashlib.sha256(
        json.dumps(seed, sort_keys=True, ensure_ascii=False).encode(),
    ).hexdigest()[:12]
    return {
        "version": version or f"budget-seed-{digest}",
        "data": {
            "lines": lines,
            "budgets": budgets,
            "statusParameters": {"scenario": scenario},
        },
    }
