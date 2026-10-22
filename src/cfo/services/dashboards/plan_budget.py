"""Quantity × rate budget lines stored on the dashboard plan, projected to ``budgets``.

The plan keeps the lines. ``budgets`` receives one sum per category per month,
``Σ(quantity × rate)``, so the existing budget-vs-actual section can read it.
Rows this projection owns are marked ``notes = plan:<version>``. A later save
drops plan-owned cells that the lines no longer contain. Rows that were never
projected are left in place until a line claims that category and month.

Financing lines (``FINANCING_CATEGORIES``: loan principal, CAPEX, funding
received) are not P&L. They stay on the plan for the forecast and the
liquidity tab and are never projected to ``budgets``.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from ...models import Budget, Category
from ..financial_reports_service import FinancialReportsService
from .budget import MAX_AMOUNT, REVENUE_KEYS, category_key

MAX_LINES = 300
MAX_MONTHS_PER_LINE = 36
PLAN_NOTE_PREFIX = "plan:"
_LABELS = FinancialReportsService.CATEGORY_HEBREW
FINANCING = "financing"
# Eliav tool kinds principal / capex / funding: cash, not P&L.
FINANCING_CATEGORIES = {
    "loan_principal": "החזרי קרן — הלוואות וליסינג",
    "capex": "השקעות הוניות (CAPEX)",
    "funding": "מימון שהתקבל",
}


class PlanBudgetError(ValueError):
    def __init__(self, message_he: str):
        self.message_he = message_he
        super().__init__(message_he)


def _invalid(message_he: str) -> PlanBudgetError:
    return PlanBudgetError(message_he)


def _known_key(name: str) -> str:
    key = category_key(name)
    if key in FINANCING_CATEGORIES:
        return key
    for code, label in FINANCING_CATEGORIES.items():
        if label == name:
            return code
    if key not in _LABELS:
        raise _invalid("קטגוריית התקציב אינה מוכרת")
    return key


def _kind_for(key: str) -> str:
    if key in FINANCING_CATEGORIES:
        return FINANCING
    return "revenue" if key in REVENUE_KEYS else "cost"


def validate_budget_lines(payload: dict) -> list[dict] | None:
    """``None`` when the plan does not carry lines. An empty list clears the projection."""
    if not isinstance(payload, dict) or "budgetLines" not in payload:
        return None
    raw = payload.get("budgetLines")
    if not isinstance(raw, list):
        raise _invalid("שורות התקציב חייבות להיות רשימה")
    if len(raw) > MAX_LINES:
        raise _invalid(f"אפשר לשמור עד {MAX_LINES} שורות תקציב")
    lines: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise _invalid("שורת תקציב חייבת להיות אובייקט")
        line_id = item.get("id")
        label = item.get("label")
        if not isinstance(line_id, str) or not line_id.strip() or len(line_id) > 64:
            raise _invalid("לשורת תקציב חסר מזהה")
        line_id = line_id.strip()
        if line_id in seen:
            raise _invalid("מזהה שורת התקציב כבר בשימוש")
        seen.add(line_id)
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 80:
            raise _invalid("לשורת תקציב חסרה כותרת")
        key = _known_key((item.get("category") or "").strip() if isinstance(item.get("category"), str) else "")
        kind = item.get("kind")
        if kind is not None and kind != _kind_for(key):
            raise _invalid("סוג השורה לא תואם לקטגוריה")
        months_raw = item.get("months") or {}
        if not isinstance(months_raw, dict):
            raise _invalid("חודשי השורה חייבים להיות אובייקט")
        if len(months_raw) > MAX_MONTHS_PER_LINE:
            raise _invalid("יותר מדי חודשים בשורת תקציב")
        months: dict[str, dict] = {}
        for month_key, cell in months_raw.items():
            parsed = _month(month_key)
            if not isinstance(cell, dict):
                raise _invalid("תא תקציב חייב להיות אובייקט")
            quantity = _non_negative(cell.get("quantity"), what="כמות")
            rate = _non_negative(cell.get("rate"), what="תעריף")
            amount = (quantity * rate).quantize(Decimal("0.01"))
            if amount > MAX_AMOUNT:
                raise _invalid("סכום התקציב גדול מדי")
            months[parsed] = {"quantity": quantity, "rate": rate, "amount": amount}
        lines.append({
            "id": line_id,
            "label": label.strip(),
            "category": key,
            "kind": _kind_for(key),
            "months": months,
        })
    return lines


def _month(value) -> str:
    if not isinstance(value, str) or len(value) != 7 or value[4] != "-":
        raise _invalid("חודש התקציב חייב להיות בצורת YYYY-MM")
    year_text, month_text = value[:4], value[5:]
    if not year_text.isdigit() or not month_text.isdigit():
        raise _invalid("חודש התקציב חייב להיות בצורת YYYY-MM")
    year, month = int(year_text), int(month_text)
    if not 2000 <= year <= 2100 or not 1 <= month <= 12:
        raise _invalid("חודש התקציב אינו בטווח")
    return f"{year:04d}-{month:02d}"


def _non_negative(value, *, what: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise _invalid(f"{what} חייבת להיות מספר")
    if isinstance(value, bool) or not number.is_finite() or number < 0:
        raise _invalid(f"{what} חייבת להיות מספר שאינו שלילי")
    if number > MAX_AMOUNT:
        raise _invalid(f"{what} גדולה מדי")
    return number


def _sums(lines: list[dict]) -> dict[tuple[int, int, str], Decimal]:
    totals: dict[tuple[int, int, str], Decimal] = {}
    for line in lines:
        if line["kind"] == FINANCING:
            continue
        for month_key, cell in line["months"].items():
            year, month = int(month_key[:4]), int(month_key[5:])
            ident = (year, month, line["category"])
            totals[ident] = totals.get(ident, Decimal("0")) + cell["amount"]
            if totals[ident] > MAX_AMOUNT:
                raise _invalid("סכום התקציב גדול מדי")
    return totals


def _category_row(db, organization_id: int, key: str) -> Category | None:
    rows = db.query(Category).filter(Category.organization_id == organization_id).all()
    for row in rows:
        if row.external_id == f"eliav:group:{key}":
            return row
        if category_key(row.name or "") == key:
            return row
    return None


def project_budget_lines(db, organization_id: int, version: str, lines: list[dict]) -> int:
    """Write the sums and delete plan-owned cells the lines no longer include."""
    desired = _sums(lines)
    categories = {key: _category_row(db, organization_id, key) for _, _, key in desired}
    existing = db.query(Budget).filter(Budget.organization_id == organization_id).all()
    by_cell: dict[tuple[int, int, str], list[Budget]] = {}
    for row in existing:
        key = category_key(row.category_name or "")
        by_cell.setdefault((row.year, row.month, key), []).append(row)
    note = f"{PLAN_NOTE_PREFIX}{version}"
    written = 0
    for ident, amount in desired.items():
        year, month, key = ident
        matches = sorted(
            by_cell.get(ident, []),
            key=lambda row: (row.updated_at or datetime.min, row.id or 0),
            reverse=True,
        )
        target = matches[0] if matches else Budget(
            organization_id=organization_id, year=year, month=month,
        )
        category = categories.get(key)
        if target.id is None:
            db.add(target)
        target.category_id = category.id if category is not None else None
        target.category_name = key
        target.budgeted_amount = amount.quantize(Decimal("0.01"))
        target.notes = note
        target.updated_at = datetime.utcnow()
        written += 1
        for extra in matches[1:]:
            if isinstance(extra.notes, str) and extra.notes.startswith(PLAN_NOTE_PREFIX):
                db.delete(extra)
    for row in existing:
        if not isinstance(row.notes, str) or not row.notes.startswith(PLAN_NOTE_PREFIX):
            continue
        ident = (row.year, row.month, category_key(row.category_name or ""))
        if ident not in desired:
            db.delete(row)
    return written


def budget_catalog() -> list[dict]:
    """Operating categories the editor offers. Kind follows the budget report."""
    keys = (
        "sales", "services", "other_income", "interest_income", "rent_income",
        "cost_of_goods", "materials", "direct_labor", "salaries", "rent",
        "utilities", "marketing", "insurance", "office_supplies", "professional_fees",
        "travel", "vehicle", "hospitality", "refreshments", "depreciation",
        "interest_expense", "bank_fees", "taxes", "other",
    )
    return [
        {"key": key, "label_he": _LABELS[key], "kind": _kind_for(key)}
        for key in keys
    ] + [
        {"key": key, "label_he": label, "kind": FINANCING}
        for key, label in FINANCING_CATEGORIES.items()
    ]


def category_label_he(key: str) -> str:
    from ..category_labels import hebrew
    return FINANCING_CATEGORIES.get(key) or _LABELS.get(key) or hebrew(key)


def monthly_line_sums(lines: list[dict] | None) -> dict[str, dict[str, float]]:
    """{"YYYY-MM": {kind: Σ quantity×rate}} of validated lines. Depreciation is not cash."""
    out: dict[str, dict[str, float]] = {}
    for line in lines or []:
        if line["category"] == "depreciation":
            continue
        for month_key, cell in line["months"].items():
            slot = out.setdefault(month_key, {})
            slot[line["kind"]] = round(slot.get(line["kind"], 0.0) + float(cell["amount"]), 2)
    return out
