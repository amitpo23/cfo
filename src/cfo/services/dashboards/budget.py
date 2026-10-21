"""Budget entry and budget-vs-actual for client dashboards. No provider calls.

Budgets are the existing ``budgets`` rows of the dashboard's primary
organization, one per category per month. Actuals come from the same ledger
helpers the P&L uses, one call per month, so the monthly totals add up to the
P&L section of the same view. A month without a budget row has budget ``None``
("אין תקציב"), never 0.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from ...models import AuditLog, Budget, Category, User
from ..financial_reports_service import FinancialReportsService
from .filing import BLOCKABLE, PNL_ROWS
from .service import PLAN_ROLES, READ_ROLES, DashboardError, get_dashboard

UNCATEGORIZED = "other"
UNCATEGORIZED_HE = "לא מסווג"
NO_BUDGET_HE = "אין תקציב"
REVENUE_KEYS = {"sales", "services", "other_income", "interest_income", "rent_income"}
MAX_ROWS = 500
# budgets.budgeted_amount is Numeric(12, 2).
MAX_AMOUNT = Decimal("9999999999.99")
_LABELS = FinancialReportsService.CATEGORY_HEBREW
_PUBLIC_LINE_KEYS = (
    "kind", "category", "category_he", "budget", "actual", "variance", "variance_pct",
)
_PUBLIC_TOTAL_KEYS = ("budget", "actual", "variance", "variance_pct")


def category_key(name: str) -> str:
    """The P&L category code for a code or a Hebrew label. Unknown names stay as typed."""
    text = (name or "").strip()
    if text == UNCATEGORIZED_HE:
        return UNCATEGORIZED
    if text.casefold() in _LABELS:
        return text.casefold()
    for code, label in _LABELS.items():
        if label == text:
            return code
    return text


def category_label(key: str) -> str:
    if key == UNCATEGORIZED:
        return UNCATEGORIZED_HE
    return _LABELS.get(key, key)


def _kind(row: Budget) -> str:
    category = row.category
    if category is not None and category.category_type == "revenue":
        return "revenue"
    return "revenue" if category_key(row.category_name or "") in REVENUE_KEYS else "cost"


def _row_out(row: Budget) -> dict:
    key = category_key(row.category_name or "")
    return {
        "year": row.year,
        "month": row.month,
        "category": key,
        "category_he": category_label(key),
        "category_id": row.category_id,
        "kind": _kind(row),
        "budgeted_amount": float(row.budgeted_amount or 0),
        "notes": row.notes,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _latest_first(rows: list[Budget]) -> list[Budget]:
    """Older budget code could write two rows for one category; the newest wins."""
    return sorted(rows, key=lambda r: (r.updated_at or datetime.min, r.id), reverse=True)


def read_budget(db, user: User, dashboard_id: int, *, year: int | None = None) -> dict:
    row = get_dashboard(db, user, dashboard_id, allowed=READ_ROLES)
    query = db.query(Budget).filter(Budget.organization_id == row.primary_organization_id)
    if year is not None:
        query = query.filter(Budget.year == year)
    seen: set[tuple] = set()
    rows = []
    for budget in _latest_first(query.all()):
        ident = (budget.year, budget.month, category_key(budget.category_name or ""), budget.category_id)
        if ident in seen:
            continue
        seen.add(ident)
        rows.append(_row_out(budget))
    rows.sort(key=lambda r: (r["year"], r["month"], r["kind"], r["category_he"]))
    return {"rows": rows, "provider_calls": 0}


def _invalid(message_he: str) -> DashboardError:
    return DashboardError(422, "invalid_budget", message_he)


def _amount(value) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise _invalid("סכום התקציב חייב להיות מספר")
    if not amount.is_finite() or (isinstance(value, float) and not math.isfinite(value)):
        raise _invalid("סכום התקציב חייב להיות מספר")
    if amount < 0:
        raise _invalid("סכום התקציב לא יכול להיות שלילי")
    if amount > MAX_AMOUNT:
        raise _invalid("סכום התקציב גדול מדי")
    return amount.quantize(Decimal("0.01"))


def _validated(db, organization_id: int, rows: list[dict]) -> list[dict]:
    if not rows:
        raise _invalid("לא נשלחו שורות תקציב")
    if len(rows) > MAX_ROWS:
        raise _invalid(f"אפשר לשמור עד {MAX_ROWS} שורות בבקשה אחת")
    clean = []
    seen: set[tuple] = set()
    for raw in rows:
        year, month = raw.get("year"), raw.get("month")
        if not isinstance(year, int) or isinstance(year, bool) or not 2000 <= year <= 2100:
            raise _invalid("שנה לא תקינה")
        if not isinstance(month, int) or isinstance(month, bool) or not 1 <= month <= 12:
            raise _invalid("החודש חייב להיות בין 1 ל-12")
        category_id = raw.get("category_id")
        name = (raw.get("category") or "").strip()
        category = None
        if category_id is not None:
            category = db.get(Category, category_id)
            if category is None or category.organization_id != organization_id:
                raise _invalid("הקטגוריה לא נמצאה")
            name = category.name.strip()
        if not name:
            raise _invalid("חסרה קטגוריה")
        key = category_key(name)
        ident = (year, month, category_id if category_id is not None else key)
        if ident in seen:
            raise _invalid("אותה קטגוריה ואותו חודש מופיעים פעמיים")
        seen.add(ident)
        notes = raw.get("notes")
        clean.append({
            "year": year, "month": month, "key": key, "category_id": category_id,
            "category_name": name if category is not None else key,
            "amount": _amount(raw.get("budgeted_amount")),
            "notes": notes.strip() if isinstance(notes, str) and notes.strip() else None,
        })
    return clean


def upsert_budget(db, user: User, dashboard_id: int, rows: list[dict]) -> dict:
    """Validate every row first, then write all of them and one audit row in one commit."""
    dashboard = get_dashboard(db, user, dashboard_id, allowed=PLAN_ROLES)
    organization_id = dashboard.primary_organization_id
    clean = _validated(db, organization_id, rows)
    saved = []
    for item in clean:
        existing = db.query(Budget).filter(
            Budget.organization_id == organization_id,
            Budget.year == item["year"],
            Budget.month == item["month"],
        )
        if item["category_id"] is not None:
            matches = existing.filter(Budget.category_id == item["category_id"]).all()
        else:
            # The unique constraint includes category_id; NULL never conflicts,
            # so name rows are matched here by their category code.
            matches = [
                b for b in existing.filter(Budget.category_id.is_(None)).all()
                if category_key(b.category_name or "") == item["key"]
            ]
        target = _latest_first(matches)[0] if matches else None
        if target is None:
            target = Budget(
                organization_id=organization_id, category_id=item["category_id"],
                year=item["year"], month=item["month"],
            )
            db.add(target)
        target.category_name = item["category_name"]
        target.budgeted_amount = item["amount"]
        target.notes = item["notes"]
        target.updated_at = datetime.utcnow()
        saved.append(target)
    db.flush()
    db.add(AuditLog(
        user_id=user.id, organization_id=organization_id, action="UPSERT_DASHBOARD_BUDGET",
        entity_type="ClientDashboard", entity_id=dashboard.id,
        details={
            "rows": len(saved),
            "periods": sorted({f"{i['year']}-{i['month']:02d}" for i in clean}),
            "provider_calls": 0,
        },
    ))
    db.commit()
    return {"saved": len(saved), "rows": [_row_out(b) for b in saved], "provider_calls": 0}


def _months(start: date, end: date):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        first = date(year, month, 1)
        nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        last = date.fromordinal(nxt.toordinal() - 1)
        yield year, month, max(first, start), min(last, end)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _budget_index(db, organization_id: int, start: date, end: date) -> dict:
    """{(year, month): {(kind, key): float}} with the newest row per category."""
    rows = db.query(Budget).filter(
        Budget.organization_id == organization_id,
        Budget.year >= start.year,
        Budget.year <= end.year,
    ).all()
    index: dict = {}
    for row in _latest_first(rows):
        if not (start.year, start.month) <= (row.year, row.month) <= (end.year, end.month):
            continue
        slot = index.setdefault((row.year, row.month), {})
        ident = (_kind(row), category_key(row.category_name or ""))
        if ident not in slot:
            slot[ident] = float(row.budgeted_amount or 0)
    return index


def _compare(budget: float | None, actual: float | None) -> dict:
    variance = None
    variance_pct = None
    if budget is not None and actual is not None:
        variance = round(actual - budget, 2)
        if budget > 0:
            variance_pct = round(variance / budget * 100, 1)
    return {
        "budget": None if budget is None else round(budget, 2),
        "actual": None if actual is None else round(actual, 2),
        "variance": variance,
        "variance_pct": variance_pct,
    }


def _sort_key(line: dict):
    return (line["category"] == UNCATEGORIZED, line["category_he"])


def _cash_actuals(month: dict) -> dict:
    """Actuals of a cash-basis month, keyed by the tool's comparison rows."""
    revenue, cost = {}, {}
    for line in month.get("lines") or []:
        (revenue if line.get("side") == "revenue" else cost)[line["id"]] = float(line.get("amount") or 0)
    return {"revenue": revenue, "cost": cost}


def budget_vs_actual(db, organization_id: int, start: date, end: date, *, books_known: bool,
                     pnl_months: list | None = None) -> dict:
    """Per month and category: budget, actual, variance.

    Each month takes its actual from the source the P&L chose for it
    (``pnl_months[*].source``): the ledger, or classified bank cash ex-VAT.
    A month never mixes sources. Without ``pnl_months`` every month uses the
    ledger, as before. Actual is None when nothing is known for the month.
    """
    budgets = _budget_index(db, organization_id, start, end)
    reports = FinancialReportsService(db)
    by_month = {m.get("month"): m for m in pnl_months or [] if isinstance(m, dict)}
    months = []
    any_known = False
    for year, month, lo, hi in _months(start, end):
        key_month = f"{year}-{month:02d}"
        info = by_month.get(key_month)
        source = info.get("source") if info is not None else ("ledger" if books_known else None)
        actuals = {"revenue": None, "cost": None}
        blocked = bool(info.get("blocked")) if info is not None else False
        if source == "ledger":
            actuals["revenue"] = {
                item.category: item.amount
                for item in reports._ledger_revenue_items(organization_id, lo, hi, lo, hi, False)
            }
            actuals["cost"] = {
                item.category: item.amount
                for item in reports._ledger_expense_items(organization_id, lo, hi, lo, hi, False)
            }
        elif source == "cash_basis":
            actuals = _cash_actuals(info)
        any_known = any_known or source is not None
        planned = budgets.get((year, month), {})
        lines = []
        totals = {}
        for kind, total_name in (("revenue", "revenue"), ("cost", "costs")):
            found = actuals[kind]
            keys = set(found or {}) | {key for (k, key) in planned if k == kind}
            kind_lines = []
            for key in keys:
                actual = None if found is None else float(found.get(key, 0.0))
                line = {"kind": kind, "category": key, "category_he": _cash_label(key)}
                line.update(_compare(planned.get((kind, key)), actual))
                if source == "cash_basis" and blocked and key in BLOCKABLE:
                    line["variance"] = None
                    line["variance_pct"] = None
                    line["blocked"] = True
                kind_lines.append(line)
            kind_lines.sort(key=_sort_key)
            lines.extend(kind_lines)
            kind_budgets = [amount for (k, _), amount in planned.items() if k == kind]
            totals[total_name] = _compare(
                sum(kind_budgets) if kind_budgets else None,
                None if found is None else float(sum(found.values())),
            )
        months.append({
            "month": key_month,
            "period_start": lo.isoformat(),
            "period_end": hi.isoformat(),
            "source": source,
            "source_label": (info or {}).get("source_label") if info else (
                "ספרים (הנהלת חשבונות)" if source == "ledger" else "לא ידוע"),
            "blocked": blocked,
            "categories": lines,
            "totals": totals,
        })
    known = any_known if pnl_months is not None else books_known
    return {
        "status": "ready" if known else "unknown",
        "has_budget": bool(budgets),
        "months": months,
        "no_budget_label": NO_BUDGET_HE,
        "message": (
            "כל חודש מחושב ממקור אחד: ספרי הנהלת החשבונות (נטו, ללא מע\"מ) כשהם מלאים, "
            "אחרת בסיס מזומן מתנועות בנק מסווגות (BOOKED בלבד, ללא מע\"מ)."
            if known else
            "אין מסמכי הכנסה או הוצאה בתקופה — הביצוע לא ידוע."
        ),
    }


def _cash_label(key: str) -> str:
    for row in PNL_ROWS:
        if row["id"] == key:
            return row["label"]
    return category_label(key)


def _public_line(line: dict) -> dict:
    out = {key: line.get(key) for key in _PUBLIC_LINE_KEYS}
    if line.get("blocked") is True:
        out["blocked"] = True
    return out


def redact_public(section):
    """Keep only the published fields. No ids, notes or staff identity."""
    if not isinstance(section, dict):
        return None
    months = []
    for month in section.get("months") or []:
        if not isinstance(month, dict):
            continue
        totals = month.get("totals") if isinstance(month.get("totals"), dict) else {}
        months.append({
            "month": month.get("month"),
            "period_start": month.get("period_start"),
            "period_end": month.get("period_end"),
            "source": month.get("source"),
            "source_label": month.get("source_label"),
            "blocked": bool(month.get("blocked")),
            "categories": [
                _public_line(line)
                for line in month.get("categories") or [] if isinstance(line, dict)
            ],
            "totals": {
                name: {key: (totals.get(name) or {}).get(key) for key in _PUBLIC_TOTAL_KEYS}
                for name in ("revenue", "costs")
            },
        })
    return {
        "status": section.get("status"),
        "has_budget": bool(section.get("has_budget")),
        "months": months,
        "no_budget_label": section.get("no_budget_label") or NO_BUDGET_HE,
        "message": section.get("message"),
    }
