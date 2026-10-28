"""One list of the working budget assumptions. No provider calls.

Every row the forecast can use is here: income, payroll, headcount, suppliers,
vehicle, interest, loan repayments, and the opening balance. A missing amount
is ``None`` and labelled ``חסר נכון ל-<date>``. It is never stored as 0.
Source is ``owner`` when the owner typed it, ``bank`` for an opening that came
from the checking snapshot, and ``books`` when a row is marked that way.
"""
from __future__ import annotations

from datetime import date

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
            amount = _cell_amount(line, month) if line else None
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
        rows.append({
            "id": "opening_balance",
            "kind": "opening_balance",
            "label_he": LABELS["opening_balance"],
            "month": opening.get("date"),
            "amount": round(float(opening["amount"]), 2),
            "quantity": None,
            "source": "owner",
            "status": "assumption",
            "missing_label": None,
            "as_of": as_of.isoformat(),
        })
    elif bank_balance is not None:
        rows.append({
            "id": "opening_balance",
            "kind": "opening_balance",
            "label_he": LABELS["opening_balance"],
            "month": bank_as_of,
            "amount": round(float(bank_balance), 2),
            "quantity": None,
            "source": "bank",
            "status": "confirmed",
            "missing_label": None,
            "as_of": bank_as_of or as_of.isoformat(),
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


def upsert_assumption(plan: dict | None, *, kind: str, month: str | None, amount, quantity=None, as_of: date, organization_id: int | None = None) -> dict:
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
            row = {"date": when, "amount": round(float(amount), 2), "source": "assumption by owner"}
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

    def marked(amount, source):
        if amount is None:
            return {"amount": None, "missing_label": missing_label(as_of), "source": source}
        return {"amount": amount, "missing_label": None, "source": source}

    return {
        "as_of": as_of.isoformat(),
        "pnl": {
            "revenue": marked(pnl.get("total_revenue"), "books"),
            "expenses": marked(pnl.get("total_expenses"), "books"),
        },
        "forecast": {
            "opening": marked((forecast.get("opening") or {}).get("amount") if isinstance(forecast.get("opening"), dict) else forecast.get("opening"), "bank"),
            "weeks": forecast.get("weeks") or [],
            "engine": forecast.get("engine"),
        },
        "budget_vs_actual": budget,
        "assumptions": assumptions,
        "provider_calls": 0,
    }
