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
# A cash-basis month reports actuals by the tool's comparison rows
# (``filing.PNL_ROWS``). Budget categories fold onto the same rows, as in the
# tool's COMPARISON_ROWS, so a salary budget meets the payroll actual.
CASH_ROW_FOR_CATEGORY = {
    "sales": "revenue", "services": "revenue", "other_income": "revenue",
    "interest_income": "revenue", "rent_income": "revenue",
    "salaries": "payroll", "direct_labor": "payroll", "social_insurance_owner": "payroll",
    "cost_of_goods": "suppliers", "materials": "suppliers",
    "vehicle": "vehicles",
    "rent": "overhead", "utilities": "overhead", "marketing": "overhead",
    "insurance": "overhead", "office_supplies": "overhead", "professional_fees": "overhead",
    "travel": "overhead", "hospitality": "overhead", "refreshments": "overhead",
    "taxes": "overhead", "other": "overhead",
    "bank_fees": "bank_fees",
    "interest_expense": "interest",
}


def _fold_for_cash(planned: dict) -> dict:
    """Budget of a cash-basis month keyed by comparison row. Unmapped keys (depreciation) stay."""
    folded: dict = {}
    for (kind, key), amount in planned.items():
        ident = (kind, CASH_ROW_FOR_CATEGORY.get(key, key))
        folded[ident] = round(folded.get(ident, 0.0) + amount, 2)
    return folded


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
    from ..category_labels import hebrew
    return _LABELS.get(key) or hebrew(key)


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
                     pnl_months: list | None = None, reports: FinancialReportsService | None = None) -> dict:
    """Per month and category: budget, actual, variance.

    Each month takes its actual from the source the P&L chose for it
    (``pnl_months[*].source``): the ledger, or classified bank cash ex-VAT.
    A month never mixes sources. Without ``pnl_months`` every month uses the
    ledger, as before. Actual is None when nothing is known for the month.
    """
    budgets = _budget_index(db, organization_id, start, end)
    reports = reports or FinancialReportsService(db, memoize=True)
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
        if source == "cash_basis":
            planned = _fold_for_cash(planned)
        lines = []
        totals = {}
        for kind, total_name in (("revenue", "revenue"), ("cost", "costs")):
            found = actuals[kind]
            keys = set(found or {}) | {key for (k, key) in planned if k == kind}
            kind_lines = []
            for key in keys:
                actual = None if found is None else float(found.get(key, 0.0))
                if source == "cash_basis" and key == "depreciation":
                    actual = None  # not a cash movement; no actual from the bank
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


def _period(year: int, month: int | None, period: str | None, today: date) -> tuple[date, date, str]:
    """The legacy /budget page's period: a month, its quarter, year to date or the year."""
    if month is not None and not 1 <= month <= 12:
        raise ValueError("month must be 1-12")
    if period == "quarter" and month is not None:
        first = (month - 1) // 3 * 3 + 1
        start = date(year, first, 1)
        end = date(year, first + 2, 1)
        name = f"Q{(month - 1) // 3 + 1}/{year}"
    elif month is not None and period in (None, "month"):
        start = end = date(year, month, 1)
        name = f"{year}-{month:02d}"
    elif period == "ytd":
        start, end = date(year, 1, 1), date(year, today.month if year == today.year else 12, 1)
        name = f"{year} עד היום" if year == today.year else str(year)
    else:
        start, end = date(year, 1, 1), date(year, 12, 1)
        name = str(year)
    nxt = date(end.year + 1, 1, 1) if end.month == 12 else date(end.year, end.month + 1, 1)
    return start, date.fromordinal(nxt.toordinal() - 1), name


def _legacy_status(kind: str, budget: float | None, actual: float | None) -> str:
    if budget is None or actual is None:
        return "unknown"
    if kind == "revenue":
        if actual >= budget:
            return "on_track"
        return "warning" if actual >= budget * 0.8 else "under_budget"
    if actual <= budget:
        return "on_track"
    return "warning" if actual <= budget * 1.1 else "over_budget"


def dashboard_window(year: int, today: date) -> tuple[date, date]:
    """The window the dashboard's /view reads by default: 1 January to today."""
    if year == today.year:
        return date(year, 1, 1), today
    return date(year, 1, 1), date(year, 12, 31)


def dashboard_summary(db, user: User | None, dashboard, year: int, month: int | None = None, *,
                      period: str | None = None, scope: str | None = None,
                      today: date | None = None) -> dict:
    """Budget vs actual of a dashboard organization in the legacy /budget page's shape.

    The figures are the dashboard's own "תקציב מול ביצוע" tab: the same call
    (``multi_entity.build_dashboard_view``) over the same window (1 January to
    today, as /view), and the same section: the consolidated one (every entity of
    the dashboard) when the dashboard has more than one entity and the user may
    read it, else the primary organization's. ``scope`` asks for one of them.
    Each month's actual comes from the source its P&L chose (books or classified
    bank cash, ex-VAT); revenue and costs are totalled apart. Unknown actual stays
    ``None``. ``variance`` keeps the legacy sign: budget minus actual.
    """
    from . import multi_entity, view_model
    from .service import role_for
    today = today or date.today()
    start, end, name = _period(year, month, period, today)
    window_start, window_end = dashboard_window(year, today)
    plan = view_model.plan_payload(db, dashboard.id)
    if window_start <= window_end:
        view = multi_entity.build_dashboard_view(db, dashboard, window_start, window_end, plan=plan)
        entities = view.get("entities") or []
    else:  # a future year: budget only
        view, entities = None, []
    labels = [section.get("label") or "" for section in entities]
    can_combine = len(entities) > 1 and role_for(db, user, dashboard) in READ_ROLES
    chosen = "combined" if can_combine and scope in (None, "combined") else "primary"
    if view is None:
        section = {"status": "unknown", "months": [], "message": None}
    elif chosen == "combined":
        section = view["combined"]["budget_vs_actual"]
    else:
        section = view["budget_vs_actual"]
    org_ids = (
        [entity["organization_id"] for entity in entities] if chosen == "combined"
        else [dashboard.primary_organization_id]
    )
    primary_label = next((s.get("label") for s in entities if s.get("role") == "primary"), None) or dashboard.title
    summary = _period_summary(db, org_ids, section, start, end, name, today)
    summary.update({
        "scope": chosen,
        "scope_label": (
            "מאוחד: " + " + ".join(labels) if chosen == "combined" else f"{primary_label} בלבד"
        ),
        "scopes": ["combined", "primary"] if can_combine else ["primary"],
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
    })
    return summary


def _period_summary(db, org_ids: list[int], section: dict, start: date, end: date, name: str,
                    today: date) -> dict:
    in_period = [
        m for m in section.get("months") or []
        if start.isoformat()[:7] <= str(m.get("month")) <= end.isoformat()[:7]
    ]
    seen = {m.get("month") for m in in_period}
    # Months of the period the section does not carry: after today (budget, no
    # actual yet), or a consolidated section that is unknown. Their budget counts.
    budget_only: dict = {}
    for org_id in org_ids:
        for (year, mon), planned in _budget_index(db, org_id, start, end).items():
            key = f"{year}-{mon:02d}"
            if key in seen:
                continue
            slot = budget_only.setdefault(key, {})
            for ident, amount in planned.items():
                slot[ident] = round(slot.get(ident, 0.0) + amount, 2)
    current = today.isoformat()[:7]
    unknown_month = any(m.get("source") is None for m in in_period) or any(
        key <= current for key in budget_only
    )
    fold = any(m.get("source") in ("cash_basis", "mixed") for m in in_period)
    rows: dict[tuple[str, str], dict] = {}

    def slot(kind: str, key: str) -> dict:
        ident = (kind, CASH_ROW_FOR_CATEGORY.get(key, key) if fold else key)
        return rows.setdefault(ident, {"budget": None, "actual": None, "actual_known": True})

    for item in in_period:
        for line in item.get("categories") or []:
            target = slot(line["kind"], line["category"])
            if line.get("budget") is not None:
                target["budget"] = round((target["budget"] or 0.0) + line["budget"], 2)
            if line.get("actual") is None:
                target["actual_known"] = False
            else:
                target["actual"] = round((target["actual"] or 0.0) + line["actual"], 2)
    for planned in budget_only.values():
        for (kind, key), amount in planned.items():
            target = slot(kind, key)
            target["budget"] = round((target["budget"] or 0.0) + amount, 2)
    if unknown_month:
        # A month with no books and no bank rows: the period's actual is not known.
        for target in rows.values():
            target["actual_known"] = False
    categories = []
    totals = {"revenue": [0.0, 0.0, True, False], "cost": [0.0, 0.0, True, False]}
    for (kind, key), value in sorted(rows.items(), key=lambda item: (item[0][0] != "revenue", item[0][1])):
        budget = value["budget"]
        actual = value["actual"] if value["actual_known"] else None
        if actual is None and value["actual_known"]:
            actual = 0.0
        if budget is None and not actual:
            continue
        variance = None if budget is None or actual is None else round(budget - actual, 2)
        categories.append({
            "category_id": key,
            "category_name": key,
            "category_hebrew": _cash_label(key),
            "kind": kind,
            "budget_amount": budget,
            "actual_amount": actual,
            "variance": variance,
            "variance_percentage": round(variance / budget * 100, 1) if variance is not None and budget else None,
            "percentage_used": round(actual / budget * 100, 1) if actual is not None and budget else None,
            "status": _legacy_status(kind, budget, actual),
        })
        total = totals[kind]
        total[0] += budget or 0.0
        total[3] = total[3] or budget is not None
        if actual is None:
            total[2] = False
        else:
            total[1] += actual
    by_kind = {
        name_out: {
            "budget": round(totals[kind][0], 2) if totals[kind][3] else None,
            "actual": round(totals[kind][1], 2) if totals[kind][2] else None,
        }
        for kind, name_out in (("revenue", "revenue"), ("cost", "costs"))
    }
    actual_known = totals["revenue"][2] and totals["cost"][2]
    total_budget = round(totals["revenue"][0] + totals["cost"][0], 2)
    # Legacy fields: revenue and costs added together. The page shows ``totals``.
    total_actual = round(totals["revenue"][1] + totals["cost"][1], 2) if actual_known else None
    total_variance = None if total_actual is None else round(total_budget - total_actual, 2)
    return {
        "period": name,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "totals": by_kind,
        "total_budget": total_budget,
        "total_actual": total_actual,
        "total_variance": total_variance,
        "variance_percentage": round(total_variance / total_budget * 100, 1) if total_variance is not None and total_budget else None,
        "status": "unknown" if total_actual is None else "ready",
        "categories": categories,
        "alerts": [],
        "source": "dashboard",
        "months": [
            {"month": m["month"], "source": m.get("source"), "source_label": m.get("source_label")}
            for m in in_period
        ],
        "message": section.get("message"),
        "provider_calls": 0,
    }


def summary_alerts(summary: dict, threshold_pct: float) -> list[dict]:
    """Budget alerts from the same figures as the page: a cost line that used
    ``threshold_pct`` of its budget or more. Unknown actual raises no alert."""
    alerts = []
    for line in summary.get("categories") or []:
        used = line.get("percentage_used")
        if line.get("kind") != "cost" or used is None or used < threshold_pct:
            continue
        over = used > 100
        label = line["category_hebrew"]
        alerts.append({
            "alert_id": f"{line['category_id']}_{summary['period']}",
            "category": line["category_id"],
            "category_hebrew": label,
            "alert_type": "over_budget" if over else "warning",
            "severity": "critical" if used >= 130 else ("high" if over else "medium"),
            "message": (
                f"חריגה ב{label}: ₪{line['actual_amount'] - line['budget_amount']:,.0f} מעל התקציב ({used:.0f}% מהתקציב)"
                if over else f"{label}: נוצלו {used:.0f}% מהתקציב"
            ),
            "budget_amount": line["budget_amount"],
            "actual_amount": line["actual_amount"],
            "variance_percentage": line["variance_percentage"],
            "percentage_used": used,
            "period": summary["period"],
            "scope_label": summary.get("scope_label"),
        })
    return sorted(alerts, key=lambda alert: alert["percentage_used"], reverse=True)
