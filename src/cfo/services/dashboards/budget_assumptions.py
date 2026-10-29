"""One list of the working budget assumptions. No provider calls.

Every row the forecast can use is here: income, payroll, headcount, suppliers,
vehicle, interest, loan repayments, and the opening balance. A missing amount
is ``None`` and labelled ``חסר נכון ל-<date>``. It is never stored as 0.
Source is ``owner`` when the owner typed it, ``bank`` for an opening that came
from the checking snapshot, and ``books`` when a row is marked that way.
"""
from __future__ import annotations

from datetime import date

from .money_screens import BANK_PACK_GATE_HE

KINDS = (
    "income",
    "payroll",
    "headcount",
    "suppliers",
    "vehicle",
    "interest",
    "loan_repayment",
    "opening_balance",
)
LABELS = {
    "income": "הכנסות",
    "payroll": "שכר",
    "headcount": "מצבת עובדים",
    "suppliers": "ספקים",
    "vehicle": "רכב",
    "interest": "ריבית",
    "loan_repayment": "החזרי קרן",
    "opening_balance": "יתרת פתיחה",
}
# Budget-line category that holds each kind. Opening balance is not a P&L line.
CATEGORY = {
    "income": "revenue",
    "payroll": "payroll",
    "headcount": "headcount",
    "suppliers": "suppliers",
    "vehicle": "vehicle",
    "interest": "interest_expense",
    "loan_repayment": "loan_principal",
}
KIND_OF = {
    "revenue": "revenue",
    "payroll": "cost",
    "headcount": "cost",
    "suppliers": "cost",
    "vehicle": "cost",
    "interest_expense": "cost",
    "loan_principal": "financing",
}
CASH_KINDS = frozenset({"payroll", "suppliers", "vehicle", "interest", "loan_repayment"})


def missing_label(as_of: date) -> str:
    return f"חסר נכון ל-{as_of.isoformat()}"


def _lines(plan: dict | None) -> list[dict]:
    raw = (plan or {}).get("budgetLines") if isinstance(plan, dict) else None
    return [line for line in raw or [] if isinstance(line, dict)]


def _cell_amount(line: dict, month: str):
    cell = (line.get("months") or {}).get(month)
    if not isinstance(cell, dict) or cell.get("amount") is None:
        quantity = cell.get("quantity") if isinstance(cell, dict) else None
        rate = cell.get("rate") if isinstance(cell, dict) else None
        if quantity is None or rate is None:
            return None
        return round(float(quantity) * float(rate), 2)
    return round(float(cell["amount"]), 2)


def _find_line(plan: dict, kind: str) -> dict | None:
    category = CATEGORY.get(kind)
    if category is None:
        return None
    for line in _lines(plan):
        if line.get("category") == category or line.get("id") == f"assumption:{kind}":
            return line
    return None


def _line_amount(line: dict, month: str):
    amount = _cell_amount(line, month)
    if amount is None:
        return None
    if line.get("kind") == "revenue" or line.get("category") in {"revenue", "sales", "services", "other_income"}:
        from .budget_fill import looks_like_placeholder
        if looks_like_placeholder(amount):
            return None
    if line.get("category") == "headcount":
        return None
    return amount


def _sum_category(plan: dict, kind: str, month: str):
    """Every line of this assumption, not only the first. A placeholder income line is skipped."""
    category = CATEGORY.get(kind)
    total = None
    for line in _lines(plan):
        if line.get("category") != category and line.get("id") != f"assumption:{kind}":
            continue
        amount = _line_amount(line, month)
        if amount is None:
            continue
        total = round((0 if total is None else total) + amount, 2)
    return total


def _opening(plan: dict | None) -> dict | None:
    evidence = (plan or {}).get("liquidityEvidence") if isinstance(plan, dict) else None
    rows = (evidence or {}).get("openingBalances") if isinstance(evidence, dict) else None
    if not isinstance(rows, list):
        return None
    dated = [row for row in rows if isinstance(row, dict) and row.get("amount") is not None]
    if not dated:
        return None
    return max(dated, key=lambda row: str(row.get("date") or ""))


def list_assumptions(plan: dict | None, months: list[str], *, as_of: date, bank_balance=None, bank_as_of: str | None = None) -> list[dict]:
    """Every working assumption for the months, including the ones still missing."""
    plan = plan if isinstance(plan, dict) else {}
    rows = []
    for month in months:
        for kind in KINDS:
            if kind == "opening_balance":
                continue
            line = _find_line(plan, kind)
            amount = _sum_category(plan, kind, month)
            source = None
            status = "missing"
            if amount is not None:
                source = (line or {}).get("source") or "owner"
                status = "confirmed" if source in {"bank", "books"} else "assumption"
            rows.append({
                "id": f"{kind}:{month}",
                "kind": kind,
                "label_he": LABELS[kind],
                "month": month,
                "amount": amount,
                "quantity": _quantity(line, month) if kind == "headcount" and line else (_quantity(line, month) if kind == "payroll" and line else None),
                "source": source,
                "status": status,
                "missing_label": None if amount is not None else missing_label(as_of),
                "as_of": as_of.isoformat(),
            })
    opening = _opening(plan)
    if opening is not None:
        compared = compare_opening(
            opening.get("amount"), opening.get("date"), opening.get("note"), opening.get("override") is True,
            bank_balance, bank_as_of, as_of,
        )
        rows.append({
            "id": "opening_balance",
            "kind": "opening_balance",
            "label_he": LABELS["opening_balance"],
            "month": opening.get("date"),
            "amount": compared["owner_amount"],
            "quantity": None,
            "source": "owner",
            "status": "assumption",
            "missing_label": None,
            "as_of": as_of.isoformat(),
            "note": compared["note"],
            "override": compared["override"],
            "bank_amount": compared["bank_amount"],
            "bank_as_of": compared["bank_as_of"],
            "bank_fresh": compared["bank_fresh"],
            "differs": compared["differs"],
            "used": compared["used"],
        })
    elif bank_balance is not None:
        compared = compare_opening(None, None, None, False, bank_balance, bank_as_of, as_of)
        rows.append({
            "id": "opening_balance",
            "kind": "opening_balance",
            "label_he": LABELS["opening_balance"],
            "month": bank_as_of,
            "amount": compared["bank_amount"],
            "quantity": None,
            "source": "bank",
            "status": "confirmed",
            "missing_label": None,
            "as_of": bank_as_of or as_of.isoformat(),
            "note": None,
            "override": False,
            "bank_amount": compared["bank_amount"],
            "bank_as_of": compared["bank_as_of"],
            "bank_fresh": compared["bank_fresh"],
            "differs": False,
            "used": compared["used"],
        })
    else:
        rows.append({
            "id": "opening_balance",
            "kind": "opening_balance",
            "label_he": LABELS["opening_balance"],
            "month": None,
            "amount": None,
            "quantity": None,
            "source": None,
            "status": "missing",
            "missing_label": missing_label(as_of),
            "as_of": as_of.isoformat(),
            "note": None,
            "override": False,
            "bank_amount": None,
            "bank_as_of": None,
            "bank_fresh": False,
            "differs": False,
            "used": "missing",
        })
    for month in months:
        for line in _lines(plan):
            if not line.get("custom"):
                continue
            amount = _line_amount(line, month)
            side = "revenue" if line.get("kind") == "revenue" else "cost"
            rows.append({
                "id": f"{line.get('id')}:{month}",
                "kind": "driver",
                "side": side,
                "label_he": line.get("label") or line.get("id"),
                "division": line.get("division"),
                "month": month,
                "amount": amount,
                "quantity": _quantity(line, month),
                "rate": ((line.get("months") or {}).get(month) or {}).get("rate") if isinstance((line.get("months") or {}).get(month), dict) else None,
                "source": line.get("source") or "owner",
                "status": "missing" if amount is None else ((line.get("months") or {}).get(month) or {}).get("status") or "assumption",
                "missing_label": None if amount is not None else missing_label(as_of),
                "as_of": as_of.isoformat(),
                "driver_formula": line.get("driver_formula"),
            })
    return rows


def _quantity(line: dict | None, month: str):
    if line is None:
        return None
    cell = (line.get("months") or {}).get(month)
    if not isinstance(cell, dict):
        return None
    return cell.get("quantity")


def _ensure_line(plan: dict, kind: str) -> dict:
    found = _find_line(plan, kind)
    if found is not None:
        return found
    line = {
        "id": f"assumption:{kind}",
        "label": LABELS[kind],
        "category": CATEGORY[kind],
        "kind": KIND_OF[CATEGORY[kind]],
        "source": "owner",
        "months": {},
    }
    plan.setdefault("budgetLines", []).append(line)
    return line


def compare_opening(owner_amount, owner_date, note, override, bank_amount, bank_as_of, today: date) -> dict:
    """Bank snapshot wins while it is at most 2 days old, unless the owner overrides."""
    fresh = False
    if bank_as_of:
        try:
            fresh = (today - date.fromisoformat(str(bank_as_of)[:10])).days <= 2
        except ValueError:
            fresh = False
    differs = (
        owner_amount is not None and bank_amount is not None
        and abs(float(owner_amount) - float(bank_amount)) >= 0.01
    )
    if override and owner_amount is not None:
        used = "owner"
    elif fresh and bank_amount is not None:
        used = "bank"
    elif owner_amount is not None:
        used = "owner"
    else:
        used = "missing"
    return {
        "owner_amount": None if owner_amount is None else round(float(owner_amount), 2),
        "owner_date": owner_date,
        "note": note or None,
        "override": bool(override),
        "bank_amount": None if bank_amount is None else round(float(bank_amount), 2),
        "bank_as_of": str(bank_as_of)[:10] if bank_as_of else None,
        "bank_fresh": fresh,
        "differs": differs,
        "used": used,
    }


def upsert_assumption(plan: dict | None, *, kind: str, month: str | None, amount, quantity=None, as_of: date, organization_id: int | None = None, note: str | None = None, override: bool = False) -> dict:
    """Add or change one assumption. ``amount is None`` deletes that month."""
    if kind not in KINDS:
        raise ValueError("סוג הנחה אינו מוכר")
    plan = dict(plan or {})
    plan["budgetLines"] = [dict(line) for line in _lines(plan)]
    if kind == "opening_balance":
        evidence = dict(plan.get("liquidityEvidence") or {})
        rows = [row for row in (evidence.get("openingBalances") or []) if isinstance(row, dict)]
        if amount is None:
            evidence["openingBalances"] = []
        else:
            when = month or as_of.isoformat()
            text = note.strip()[:300] if isinstance(note, str) else ""
            row = {
                "date": when, "amount": round(float(amount), 2), "source": "assumption by owner",
                "override": bool(override),
            }
            if text:
                row["note"] = text
            if organization_id is not None:
                row["organizationId"] = int(organization_id)
            evidence["openingBalances"] = [row]
        plan["liquidityEvidence"] = evidence
        return plan
    if not isinstance(month, str) or len(month) != 7:
        raise ValueError("חסר חודש")
    line = _ensure_line(plan, kind)
    months = dict(line.get("months") or {})
    if amount is None and quantity is None:
        months.pop(month, None)
    else:
        rate = float(amount) if amount is not None else None
        qty = float(quantity) if quantity is not None else 1
        if kind == "headcount":
            qty = float(amount if amount is not None else quantity or 0)
            rate = 1
        if rate is None:
            months.pop(month, None)
        else:
            months[month] = {"quantity": qty, "rate": rate, "amount": round(qty * rate, 2)}
    line["months"] = months
    line["source"] = "owner"
    return plan


def delete_assumption(plan: dict | None, *, kind: str, month: str | None, as_of: date) -> dict:
    return upsert_assumption(plan, kind=kind, month=month, amount=None, as_of=as_of)


def comparison_allowed(plan: dict | None, actual_scope: str) -> tuple[bool, str | None]:
    """A primary-only budget is not compared with consolidated actuals."""
    declared = (plan or {}).get("budgetScope") if isinstance(plan, dict) else None
    if declared == "primary" and actual_scope == "combined":
        return False, "תקציב של ישות אחת לא מושווה לביצוע מאוחד"
    return True, None


def bank_pack(view: dict, assumptions: list[dict], *, as_of: date) -> dict:
    """P&L, forecast and budget-vs-actual for a bank, with the assumptions listed.

    Missing figures stay null and carry ``חסר נכון ל-<date>``. Nothing here
    is replaced with 0.
    """
    forecast = (view or {}).get("cash_forecast") or {}
    pnl = (view or {}).get("pnl") or {}
    budget = (view or {}).get("budget_vs_actual") or {}

    labels = {"books": "ספרים", "bank": "בנק", "owner": "בעלים"}

    def marked(amount, source, figure_as_of: str | None = None):
        day = figure_as_of or as_of.isoformat()
        label = labels.get(source, source)
        if amount is None:
            return {"amount": None, "missing_label": missing_label(as_of), "source": label, "as_of": day}
        return {"amount": amount, "missing_label": None, "source": label, "as_of": day}

    raw_opening = forecast.get("opening")
    opening = raw_opening if isinstance(raw_opening, dict) else {}
    opening_amount = opening.get("amount") if opening else raw_opening
    opening_as_of = opening.get("as_of") if isinstance(opening.get("as_of"), str) else None
    settings = ((view or {}).get("cashflow_source") or {}).get("settings") or {}
    supplier_terms = settings.get("supplierTermsMode") or "end_of_next_month"
    weeks = []
    for week in forecast.get("weeks") or []:
        if not isinstance(week, dict):
            continue
        copied = dict(week)
        for key in ("in", "out", "net", "closing", "headroom"):
            if copied.get(key) is None:
                copied[f"{key}_missing"] = missing_label(as_of)
        weeks.append(copied)
    from_lines: dict[str, dict] = {}
    for row in assumptions or []:
        month_key = row.get("month")
        if not isinstance(month_key, str) or len(month_key) != 7 or row.get("amount") is None:
            continue
        slot = from_lines.setdefault(month_key, {"revenue": None, "costs": None})
        if row.get("kind") == "income":
            slot["revenue"] = row["amount"]
        elif row.get("kind") == "driver" and row.get("side") == "cost":
            slot["costs"] = round((slot["costs"] or 0) + float(row["amount"]), 2)
    months_out = []
    seen = set()
    for month in budget.get("months") or []:
        if not isinstance(month, dict):
            continue
        totals = month.get("totals") if isinstance(month.get("totals"), dict) else {}
        revenue_budget = (totals.get("revenue") or {}).get("budget") if isinstance(totals.get("revenue"), dict) else None
        cost_budget = (totals.get("costs") or {}).get("budget") if isinstance(totals.get("costs"), dict) else None
        lined = from_lines.get(month.get("month")) or {}
        if revenue_budget is None:
            revenue_budget = lined.get("revenue")
        if cost_budget is None:
            cost_budget = lined.get("costs")
        seen.add(month.get("month"))
        months_out.append({
            "month": month.get("month"),
            "revenue_budget": revenue_budget,
            "cost_budget": cost_budget,
            "budget": revenue_budget if revenue_budget is not None else cost_budget,
            "actual": (totals.get("revenue") or {}).get("actual") if isinstance(totals.get("revenue"), dict) else None,
            "source_label": month.get("source_label") or ("plan.budgetLines" if lined else None),
        })
    for month_key, slot in sorted(from_lines.items()):
        if month_key in seen or (slot["revenue"] is None and slot["costs"] is None):
            continue
        months_out.append({
            "month": month_key,
            "revenue_budget": slot["revenue"],
            "cost_budget": slot["costs"],
            "budget": slot["revenue"] if slot["revenue"] is not None else slot["costs"],
            "actual": None,
            "source_label": "plan.budgetLines",
        })
    budget = dict(budget)
    budget["months"] = months_out or budget.get("months")
    return {
        "as_of": as_of.isoformat(),
        "title_he": "חבילה לבנק",
        "pnl": {
            "revenue": marked(pnl.get("total_revenue"), "books"),
            "expenses": marked(pnl.get("total_expenses"), "books"),
        },
        "forecast": {
            "opening": marked(opening_amount, "bank", opening_as_of),
            "weeks": weeks,
            "engine": forecast.get("engine"),
            "supplier_terms": supplier_terms,
        },
        "budget_vs_actual": budget,
        "liquidity_today": (view or {}).get("liquidity_today"),
        "assumptions": assumptions,
        "product_gate_he": BANK_PACK_GATE_HE,
        "provider_calls": 0,
    }
