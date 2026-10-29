"""Budget line fill status. No provider calls and no invented amounts.

A line is filled only when both quantity and rate are already stored, or the
owner saved an amount. ``none`` is an explicit mark. Everything else is
``missing`` ("חסר, הבעלים יזין"). There is no fixed payroll amount. A wage
total is only the sum of wage lines that already have both numbers. A P&L
row with no saved amount is prefilled from the same month last year when
that history exists, and stays missing when it does not.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from ...models import Budget, ClientDashboard, DashboardEntity, DashboardPlan
from .plan_budget import FINANCING, budget_catalog

NONE_MARK = "none"
NONE_NOTE = "budget-line:none"
STATUS_HE = {
    "filled": "יש סכום",
    "none": "אין",
    "missing": "חסר, הבעלים יזין",
    "assumption": "הנחה מהיסטוריה",
    "confirmed": "מאושר",
}
_KIND_IN = {
    "income": "revenue",
    "revenue": "revenue",
    "expense": "cost",
    "cost": "cost",
    "financing": "financing",
}
_ACTIVE = {"revenue", "cost", "expense", "interest", "depreciation"}
_MONEY = Decimal("0.01")


def _q(value: Decimal) -> str:
    return f"{value.quantize(_MONEY, rounding=ROUND_HALF_UP):f}"


def _month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def is_active(kind: str | None) -> bool:
    return kind in _ACTIVE


def dashboard_for_org(db, organization_id: int) -> ClientDashboard | None:
    row = (
        db.query(ClientDashboard)
        .filter(ClientDashboard.primary_organization_id == organization_id)
        .order_by(ClientDashboard.id)
        .first()
    )
    if row is not None:
        return row
    entity = (
        db.query(DashboardEntity)
        .filter(DashboardEntity.organization_id == organization_id)
        .order_by(DashboardEntity.id)
        .first()
    )
    if entity is None:
        return None
    return db.get(ClientDashboard, entity.dashboard_id)


def _amount(quantity, rate) -> Decimal | None:
    if quantity is None or rate is None:
        return None
    try:
        return (Decimal(str(quantity)) * Decimal(str(rate))).quantize(_MONEY)
    except Exception:
        return None


def _cell_status(cell, mark) -> tuple[str, Decimal | None]:
    if isinstance(cell, dict):
        amount = _amount(cell.get("quantity"), cell.get("rate"))
        if amount is not None:
            return "filled", amount
    if mark == NONE_MARK:
        return "none", None
    return "missing", None


def _plan_lines(payload: dict | None) -> list[dict] | None:
    if not isinstance(payload, dict) or "budgetLines" not in payload:
        return None
    raw = payload.get("budgetLines")
    return raw if isinstance(raw, list) else None


def _catalog_lines() -> list[dict]:
    return [
        {"id": row["key"], "label": row["label_he"], "category": row["key"], "kind": row["kind"], "months": {}}
        for row in budget_catalog()
        if row["kind"] != FINANCING
    ]


def _stored_budget(db, organization_id: int, year: int, month: int, category: str) -> Budget | None:
    rows = db.query(Budget).filter(
        Budget.organization_id == organization_id,
        Budget.year == year,
        Budget.month == month,
    ).all()
    matches = [row for row in rows if (row.category_name or "") == category or (row.category_name or "") == category]
    if not matches:
        return None
    return sorted(matches, key=lambda row: (row.updated_at or datetime.min, row.id or 0), reverse=True)[0]


def _history_amounts(db, organization_id: int, year: int, months: list[int]) -> dict[tuple[int, str], Decimal]:
    """Same calendar month last year, by P&L row. No history stays absent."""
    from .books import cash_basis_month, classified_bank
    if not months:
        return {}
    prior = year - 1
    start = date(prior, min(months), 1)
    end = date(prior, max(months), monthrange(prior, max(months))[1])
    filed = classified_bank(db, organization_id, start, end, None)
    found = {}
    for month in months:
        prefix = f"{prior:04d}-{month:02d}"
        items = [(txn, row) for txn, row in filed if str(txn.date).startswith(prefix)]
        if not items:
            continue
        report = cash_basis_month(items)
        for line in report["lines"]:
            amount = line.get("amount")
            if amount:
                found[(month, line["id"])] = Decimal(str(amount)).quantize(_MONEY)
    return found


def _assumptions(db, organization_id: int, payload, year: int, from_month: int, to_month: int) -> list[dict]:
    from .budget_assumptions import list_assumptions
    from .liquidity import checking_snapshot
    months = [f"{year:04d}-{month:02d}" for month in range(from_month, to_month + 1)]
    snap = checking_snapshot(db, organization_id)
    return list_assumptions(
        payload if isinstance(payload, dict) else None, months, as_of=date.today(),
        bank_balance=snap.get("balance"), bank_as_of=snap.get("as_of"),
    )


def entry_lines(db, organization_id: int, year: int, from_month: int, to_month: int) -> dict:
    dashboard = dashboard_for_org(db, organization_id)
    payload = None
    if dashboard is not None:
        stored = db.get(DashboardPlan, dashboard.id)
        payload = stored.payload if stored is not None and isinstance(stored.payload, dict) else None
    plan_lines = _plan_lines(payload)
    source = "plan" if plan_lines is not None else "catalog"
    raw_lines = plan_lines if plan_lines is not None else _catalog_lines()
    imported = ((payload or {}).get("eliavImport") or {}).get("lines") if isinstance(payload, dict) else None
    imported = imported if isinstance(imported, dict) else {}
    months = list(range(from_month, to_month + 1))
    history = _history_amounts(db, organization_id, year, months)
    lines = []
    missing = []
    filled = none = 0
    for raw in raw_lines:
        if not isinstance(raw, dict):
            continue
        kind = raw.get("kind")
        if not is_active(kind):
            continue
        line_id = str(raw.get("id") or "")
        if not line_id:
            continue
        detail = imported.get(line_id) if isinstance(imported.get(line_id), dict) else {}
        defaults = detail.get("defaults") if isinstance(detail.get("defaults"), dict) else {}
        if not defaults and isinstance(raw.get("defaults"), dict):
            defaults = raw["defaults"]
        default_amount = _amount(defaults.get("quantity"), defaults.get("rate"))
        marks = raw.get("fill") if isinstance(raw.get("fill"), dict) else {}
        month_cells = raw.get("months") if isinstance(raw.get("months"), dict) else {}
        by_month = {}
        line_missing = []
        for month in months:
            key = _month_key(year, month)
            cell = month_cells.get(key)
            if not isinstance(cell, dict) and default_amount is not None:
                cell = {"quantity": defaults.get("quantity"), "rate": defaults.get("rate")}
            status, amount = _cell_status(cell, marks.get(key))
            if source == "catalog" and status == "missing":
                stored = _stored_budget(db, organization_id, year, month, line_id)
                if stored is not None and stored.notes == NONE_NOTE:
                    status, amount = "none", None
                elif stored is not None:
                    status, amount = "filled", Decimal(str(stored.budgeted_amount or 0)).quantize(_MONEY)
            source_name = None
            if isinstance(cell, dict) and cell.get("status") in {"assumption", "confirmed"} and amount is not None:
                status = cell["status"]
            if status == "missing" and not raw.get("custom"):
                prior = history.get((month, line_id)) or history.get((month, str(raw.get("category") or "")))
                if prior is not None and prior != 0:
                    status, amount = "assumption", prior
                    source_name = "history"
            warning = None
            income = kind == "revenue" or str(raw.get("category") or "") in {"revenue", "sales", "income"}
            if income and status in {"filled", "assumption", "confirmed"}:
                warning = looks_like_placeholder(amount)
            by_month[key] = {
                "status": status,
                "status_he": STATUS_HE[status],
                # A round-million income placeholder stays on the line so the
                # owner can delete it, and is left out of the amount and the total.
                "amount": None if amount is None or warning else _q(amount),
                "quantity": None if not isinstance(cell, dict) or warning else cell.get("quantity"),
                "rate": None if not isinstance(cell, dict) or warning else cell.get("rate"),
                **({"source": source_name} if source_name else {}),
                **({"placeholder_warning": warning, "placeholder_amount": _q(amount)} if warning else {}),
            }
            if status == "missing":
                line_missing.append(key)
            if raw.get("custom") and status == "missing":
                by_month[key]["status_he"] = "חסר"
            elif status == "assumption" and raw.get("custom") and source_name != "history":
                by_month[key]["status_he"] = "הנחה"
        has_amount = any(
            cell.get("amount") is not None and cell.get("status") in {"filled", "assumption", "confirmed"}
            for cell in by_month.values()
        )
        all_none = bool(by_month) and all(cell["status"] == "none" for cell in by_month.values())
        if all_none:
            none += 1
        elif has_amount:
            filled += 1
        elif line_missing:
            missing.append({"id": line_id, "label": raw.get("label") or line_id, "months": line_missing})
        line_warning = next((
            cell["placeholder_warning"] for cell in by_month.values() if cell.get("placeholder_warning")
        ), None)
        lines.append({
            "id": line_id,
            "label": raw.get("label") or line_id,
            "kind": "revenue" if kind == "revenue" else "cost",
            "category": raw.get("category"),
            "custom": bool(raw.get("custom")),
            "months": by_month,
            **({"division": raw.get("division")} if raw.get("custom") else {}),
            **({"line_source": raw.get("source")} if raw.get("custom") and raw.get("source") else {}),
            **({"driver_formula": raw.get("driver_formula")} if raw.get("custom") and raw.get("driver_formula") else {}),
            **({"covers": raw.get("covers")} if raw.get("covers") else {}),
            **({"placeholder_warning": line_warning} if line_warning else {}),
        })
    wage_months = []
    for month in months:
        key = _month_key(year, month)
        total = Decimal("0")
        ids = []
        any_filled = False
        for line in lines:
            if not str(line["id"]).startswith("wage_"):
                continue
            cell = line["months"][key]
            if cell["status"] != "filled":
                continue
            any_filled = True
            total += Decimal(cell["amount"])
            ids.append(line["id"])
        wage_months.append({
            "month": key,
            "filled_sum": _q(total) if any_filled else None,
            "matches_declared": None,
            "line_ids": ids,
        })
    return {
        "year": year,
        "from_month": from_month,
        "to_month": to_month,
        "source": source,
        "lines": lines,
        "counts": {"active": len(lines), "filled": filled, "none": none, "missing": len(missing)},
        "missing": missing,
        "declared_payroll": {
            "monthly": None,
            "note_he": "השכר המוצהר הוא סכום שורות השכר שכבר יש להן כמות ותעריף. אין סכום קבוע.",
            "months": wage_months,
        },
        "provider_calls": 0,
        "assumptions": _assumptions(db, organization_id, payload, year, from_month, to_month),
    }


def _normalize_kind(kind) -> str | None:
    if not isinstance(kind, str):
        return None
    return _KIND_IN.get(kind.strip())


def _stamp_custom(line: dict, update: dict) -> None:
    if update.get("custom") is True:
        line["custom"] = True
    for field, limit in (("division", 40), ("source", 80), ("driver_formula", 160), ("covers", 40)):
        value = update.get(field)
        if isinstance(value, str) and value.strip():
            line[field] = value.strip()[:limit]
            line["custom"] = True


def _amount_cell(update: dict, status: str) -> dict:
    quantity = update.get("qty", update.get("quantity"))
    rate = update.get("unit_price", update.get("rate"))
    amount = update.get("amount")
    if quantity is not None and rate is not None:
        qty = Decimal(str(quantity))
        price = Decimal(str(rate))
    elif amount is not None:
        qty = Decimal("1")
        price = Decimal(str(amount))
    else:
        raise ValueError("סכום חסר")
    if qty < 0 or price < 0:
        raise ValueError("סכום שלילי")
    cell = {"quantity": float(qty), "rate": float(price)}
    if status in {"assumption", "confirmed"}:
        cell["status"] = status
    return cell


def apply_updates(payload: dict, updates: list[dict]) -> dict:
    """Return a new plan payload. Unknown amounts are not created."""
    payload = dict(payload or {})
    lines = [dict(line) for line in payload.get("budgetLines") or [] if isinstance(line, dict)]
    by_id = {str(line.get("id")): line for line in lines if line.get("id")}
    for raw_update in updates:
        update = dict(raw_update)
        line_id = str(update.get("id") or "").strip()
        if not line_id:
            raise ValueError("חסר מזהה שורה")
        if update.get("remove"):
            lines = [line for line in lines if str(line.get("id")) != line_id]
            by_id.pop(line_id, None)
            continue
        mapped = _normalize_kind(update.get("kind"))
        if mapped is not None:
            update["kind"] = mapped
        if update.get("custom") is True and not update.get("category"):
            update["category"] = "revenue" if update.get("kind") == "revenue" else "other"
        line = by_id.get(line_id)
        if line is None:
            label = update.get("label")
            category = update.get("category")
            kind = update.get("kind")
            if not isinstance(label, str) or not label.strip():
                raise ValueError("לשורה חדשה חסרה כותרת")
            if kind not in {"revenue", "cost", "financing"} or not isinstance(category, str) or not category:
                raise ValueError("שורה חדשה צריכה קטגוריה וסוג")
            line = {"id": line_id, "label": label.strip(), "category": category, "kind": kind, "months": {}}
            lines.append(line)
            by_id[line_id] = line
        _stamp_custom(line, update)
        if isinstance(update.get("label"), str) and update["label"].strip():
            line["label"] = update["label"].strip()
        month = update.get("month")
        if not isinstance(month, str):
            continue
        months = dict(line.get("months") or {})
        marks = dict(line.get("fill") or {})
        status = update.get("status")
        if status in {"filled", "assumption", "confirmed"}:
            months[month] = _amount_cell(update, status)
            marks.pop(month, None)
        elif status == NONE_MARK:
            months.pop(month, None)
            marks[month] = NONE_MARK
        elif status == "missing":
            months.pop(month, None)
            marks.pop(month, None)
        else:
            raise ValueError("סטטוס שורה אינו מוכר")
        line["months"] = months
        if marks:
            line["fill"] = marks
        elif "fill" in line:
            line.pop("fill", None)
    payload["budgetLines"] = lines
    return payload


def _save_budget_rows(db, organization_id: int, updates: list[dict]) -> dict:
    """Orgs without a dashboard keep amounts on ``budgets``. Missing stays absent, not zero."""
    for update in updates:
        month = update.get("month")
        if update.get("remove"):
            category = str(update.get("category") or update.get("id") or "")
            if not category:
                continue
            year = int(month[:4]) if isinstance(month, str) and len(month) >= 7 else None
            month_number = int(month[5:7]) if isinstance(month, str) and len(month) >= 7 else None
            query = db.query(Budget).filter(
                Budget.organization_id == organization_id, Budget.category_name == category,
            )
            if year is not None and month_number is not None:
                query = query.filter(Budget.year == year, Budget.month == month_number)
            for row in query.all():
                db.delete(row)
            continue
        if not isinstance(month, str) or len(month) != 7:
            continue
        status = update.get("status")
        category = str(update.get("category") or update.get("id") or "")
        if not category:
            continue
        year, month_number = int(month[:4]), int(month[5:7])
        row = _stored_budget(db, organization_id, year, month_number, category)
        if status == "missing":
            if row is not None:
                db.delete(row)
            continue
        if row is None:
            row = Budget(
                organization_id=organization_id, year=year, month=month_number, category_name=category,
            )
            db.add(row)
        if status == NONE_MARK:
            row.budgeted_amount = Decimal("0")
            row.notes = NONE_NOTE
        elif status == "filled":
            if update.get("amount") is None:
                raise ValueError("סכום חסר")
            row.budgeted_amount = Decimal(str(update["amount"]))
            row.notes = None
        else:
            raise ValueError("סטטוס שורה אינו מוכר")
        row.updated_at = datetime.utcnow()
    db.commit()
    return {"version": None, "provider_calls": 0}


PLACEHOLDER_MIN = Decimal("1000000")


def driver_month_rows(plan: dict | None, month: str) -> list[dict]:
    """One comparison row per custom line. A missing amount stays null, not 0."""
    rows = []
    raw = (plan or {}).get("budgetLines") if isinstance(plan, dict) else None
    for line in raw or []:
        if not isinstance(line, dict) or not line.get("custom"):
            continue
        kind = "revenue" if line.get("kind") == "revenue" else "cost"
        cell = (line.get("months") or {}).get(month)
        quantity = rate = amount = None
        status = "missing"
        if isinstance(cell, dict) and cell.get("quantity") is not None and cell.get("rate") is not None:
            quantity = float(cell["quantity"])
            rate = float(cell["rate"])
            amount = round(quantity * rate, 2)
            status = cell.get("status") or "assumption"
        warning = looks_like_placeholder(amount) if kind == "revenue" and amount is not None else None
        budget = None if warning or amount is None else amount
        rolled = line.get("category") or ("revenue" if kind == "revenue" else "other")
        rows.append({
            "kind": kind,
            "category": str(line.get("id") or ""),
            "category_he": line.get("label") or str(line.get("id") or ""),
            "budget": budget,
            "actual": None,
            "variance": None,
            "variance_pct": None,
            "driver": True,
            "division": line.get("division"),
            "driver_formula": line.get("driver_formula"),
            "quantity": quantity,
            "rate": rate,
            "line_source": line.get("source"),
            "line_status": status,
            "placeholder": bool(warning),
            "placeholder_warning": warning,
            "placeholder_amount": amount if warning else None,
            "rolled_category": rolled,
        })
    return rows


def counts_in_total(line: dict, cell) -> Decimal | None:
    """An amount that belongs in a month total. Missing and round-million income stay out."""
    if not isinstance(line, dict) or not isinstance(cell, dict) or cell.get("amount") is None:
        return None
    if cell.get("status") == "missing" or cell.get("placeholder") is True:
        return None
    try:
        number = Decimal(str(cell["amount"]))
    except (ArithmeticError, ValueError, TypeError):
        return None
    income = line.get("kind") == "revenue" or line.get("category") in {
        "sales", "services", "other_income", "interest_income", "rent_income", "revenue",
    }
    if income and looks_like_placeholder(number):
        return None
    return number


def driver_csv_updates(text: str, month: str) -> list[dict]:
    """One month of driver lines from the budget_lines.csv columns. Blank amount stays missing."""
    import csv
    import io

    if not isinstance(month, str) or len(month) != 7 or month[4] != "-":
        raise ValueError("חודש הייבוא חייב להיות YYYY-MM")
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    updates = []
    for raw in reader:
        if not raw:
            continue
        line_id = str(raw.get("line_key") or "").strip()
        label = str(raw.get("label_he") or "").strip()
        if not line_id or not label:
            raise ValueError("לשורת CSV חסר מזהה או כותרת")
        kind_raw = str(raw.get("kind") or "").strip()
        covers = None
        if "income" in kind_raw and "expense" in kind_raw:
            kind = "revenue"
            covers = "income_and_expense"
        elif kind_raw == "expense":
            kind = "cost"
        else:
            kind = "revenue"
        status = str(raw.get("status") or "missing").strip() or "missing"
        if status not in {"assumption", "confirmed", "missing"}:
            raise ValueError("סטטוס CSV אינו מוכר")
        amount_text = str(raw.get("amount") or "").strip()
        qty_text = str(raw.get("qty") or "").strip()
        price_text = str(raw.get("unit_price") or "").strip()
        if status != "missing" and not amount_text and not (qty_text and price_text):
            status = "missing"
        update = {
            "id": line_id,
            "label": label,
            "kind": kind,
            "custom": True,
            "division": str(raw.get("division") or "").strip(),
            "source": str(raw.get("source") or "").strip(),
            "driver_formula": str(raw.get("driver_formula") or "").strip(),
            "month": month,
            "status": status,
        }
        if covers:
            update["covers"] = covers
        if qty_text and price_text:
            update["qty"] = float(qty_text)
            update["unit_price"] = float(price_text)
        elif amount_text and status != "missing":
            update["amount"] = float(amount_text)
        if status == "missing":
            update.pop("amount", None)
            update.pop("qty", None)
            update.pop("unit_price", None)
        updates.append(update)
    if not updates:
        raise ValueError("הקובץ לא מכיל שורות")
    return updates


def budget_lines_for_org(plan, organization_id: int | None, *, primary: bool) -> list[dict]:
    """Budget lines of one organization.

    A line without ``organizationId`` belongs to the dashboard's primary
    organization (Chef's 49,700 payroll). It is not applied to the other
    entities. A line that names an organization is only that organization's.
    """
    raw = plan.get("budgetLines") if isinstance(plan, dict) else None
    if not isinstance(raw, list):
        return []
    kept = []
    for line in raw:
        if not isinstance(line, dict):
            continue
        named = line.get("organizationId")
        if named is None:
            if primary:
                kept.append(line)
            continue
        if organization_id is not None and named == organization_id:
            kept.append(line)
    return kept


def looks_like_placeholder(amount, actual=None) -> str | None:
    """A warning for an income figure that looks invented. Never a deletion."""
    if amount is None:
        return None
    try:
        number = Decimal(str(amount))
    except (ArithmeticError, ValueError, TypeError):
        return None
    if number < PLACEHOLDER_MIN:
        return None
    if actual is None:
        if number % PLACEHOLDER_MIN == 0:
            return "סכום עגול של מיליון ומעלה, בלי ביצוע להשוואה. אזהרה בלבד — לא נמחק."
        return None
    actual_abs = abs(Decimal(str(actual)))
    if number >= max(actual_abs * 10, PLACEHOLDER_MIN):
        return "תקציב ההכנסה גבוה בהרבה מהביצוע הידוע. אזהרה בלבד — לא נמחק."
    return None


def _split_opening(payload: dict, updates: list[dict], organization_id: int) -> tuple[dict, list[dict]]:
    """An opening balance is evidence, including a negative checking balance."""
    from .budget_assumptions import upsert_assumption
    kept = []
    plan = payload
    as_of = date.today()
    for update in updates:
        line_id = str(update.get("id") or "")
        if update.get("category") != "opening_balance" and line_id != "opening_balance":
            kept.append(update)
            continue
        status = update.get("status")
        amount = None if status in {"missing", "none"} else update.get("amount")
        when = update.get("month")
        if isinstance(when, str) and len(when) == 7:
            when = f"{when}-01"
        if not isinstance(when, str) or len(when) < 10:
            when = as_of.isoformat()
        plan = upsert_assumption(
            plan, kind="opening_balance", month=when[:10], amount=amount,
            as_of=as_of, organization_id=organization_id,
            note=update.get("note"), override=update.get("override") is True,
        )
    return plan, kept


def save_entry(db, user, organization_id: int, updates: list[dict]) -> dict:
    from .service import save_plan
    dashboard = dashboard_for_org(db, organization_id)
    opening = any(
        item.get("category") == "opening_balance" or str(item.get("id") or "") == "opening_balance"
        for item in updates
    )
    if dashboard is None:
        if opening:
            raise ValueError("יתרת פתיחה נשמרת בדשבורד של הארגון")
        return _save_budget_rows(db, organization_id, updates)
    current = db.get(DashboardPlan, dashboard.id)
    payload = dict(current.payload) if current is not None and isinstance(current.payload, dict) else {}
    if "budgetLines" not in payload:
        payload["budgetLines"] = [
            {"id": line["id"], "label": line["label"], "category": line["category"], "kind": line["kind"], "months": {}}
            for line in _catalog_lines()
        ]
    payload, updates = _split_opening(payload, updates, organization_id)
    updated = apply_updates(payload, updates)
    version = current.version if current is not None else "null"
    saved = save_plan(db, user, dashboard.id, updated, version)
    return {"version": saved["version"], "provider_calls": 0}


def seed_status(seed: list[dict]) -> dict:
    """Which seed lines already have an amount. Does not invent the rest."""
    filled, missing = [], []
    wage = Decimal("0")
    wage_ids = []
    for raw in seed:
        if not isinstance(raw, dict) or not is_active(raw.get("kind")):
            continue
        amount = _amount(raw.get("quantity"), raw.get("rate"))
        item = {"id": raw.get("id"), "label": raw.get("label"), "kind": raw.get("kind")}
        if amount is None:
            missing.append(item)
            continue
        item["amount"] = _q(amount)
        filled.append(item)
        if str(raw.get("id") or "").startswith("wage_"):
            wage += amount
            wage_ids.append(raw.get("id"))
    return {
        "active": len(filled) + len(missing),
        "filled": filled,
        "missing": missing,
        "declared_payroll": {
            "monthly": None,
            "filled_sum": _q(wage) if wage_ids else None,
            "matches_declared": None,
            "line_ids": wage_ids,
        },
    }


def with_history_assumptions(db, organization_id: int, plan: dict | None, today: date) -> dict | None:
    """A forecast-only copy. Missing budget months are filled from stored history.

    Nothing is written. A month the owner already filled is left alone. A zero
    history amount is not used.
    """
    if not isinstance(plan, dict):
        return plan
    lines = [dict(line) for line in plan.get("budgetLines") or [] if isinstance(line, dict)]
    if not lines:
        return plan
    history = _history_amounts(db, organization_id, today.year, list(range(today.month, 13)))
    if not history:
        return plan
    changed = False
    for line in lines:
        cells = dict(line.get("months") or {})
        for month in range(today.month, 13):
            key = f"{today.year:04d}-{month:02d}"
            cell = cells.get(key)
            if isinstance(cell, dict) and (cell.get("rate") is not None or cell.get("amount") is not None):
                continue
            prior = history.get((month, str(line.get("id") or ""))) or history.get((month, str(line.get("category") or "")))
            if prior is None or prior == 0:
                continue
            cells[key] = {"quantity": 1, "rate": float(prior), "amount": float(prior), "source": "history"}
            changed = True
        line["months"] = cells
    if not changed:
        return plan
    copied = dict(plan)
    copied["budgetLines"] = lines
    return copied
