"""Books P&L by month from documents already stored. No provider calls.

Each month is either the imported books (invoices, bills and filed expenses,
or a mapped SUMIT journal when that month has no such documents) or an explicit
"אין נתוני ספרים". Bank rows are never substituted for a missing month.

A document lands in פיצה / משלוחים / קולינרי only when it carries that
division itself (or a plan ``divisionMap`` names its account). Costs marked
shared (Food Group, common to pizza and culinary) stay in עלויות משותפות.
Division profit is before those costs. They are allocated only when the plan
has a key for that month: manual percentages, or the month's pizza/culinary
revenue share. Anything else is לבירור, with its share of the month.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import re

from ...models import Account, BankTransaction, Bill, Expense, Invoice, JournalEntry
from ..vat_utils import bill_counts, expense_counts, invoice_counts
from . import source_journal
from .freshness import build_freshness
from .plan_budget import PlanBudgetError, monthly_line_sums, validate_budget_lines

BOOKS = "books"
NO_BOOKS = "no_books"
CLARIFY = "clarify"
SHARED = "shared"
# Shared Food Group costs are split only between pizza and culinary.
SHARED_TARGETS = ("pizza", "culinary")
DIVISIONS = ("pizza", "deliveries", "culinary", SHARED, CLARIFY)
LABELS = {
    "pizza": "פיצה",
    "deliveries": "משלוחים",
    "culinary": "קולינרי",
    SHARED: "עלויות משותפות",
    CLARIFY: "לבירור",
}
BASIS_BOOKS = "ספרים — מסמכי SUMIT שכבר במערכת"
BASIS_JOURNAL = "ספרים — יומן SUMIT מיובא"
BASIS_NONE = "אין נתוני ספרים"
_ALIASES = {
    "pizza": "pizza",
    "פיצה": "pizza",
    "deliveries": "deliveries",
    "משלוחים": "deliveries",
    "משלוח": "deliveries",
    "culinary": "culinary",
    "קולינרי": "culinary",
    "chef": "culinary",
    "שף": "culinary",
    "shared": "shared",
    "common": "shared",
    "food_group": "shared",
    "משותף": "shared",
    "משותפות": "shared",
    "עלויות משותפות": "shared",
}
_MONTH_KEY = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_MONEY = Decimal("0.01")
_SPLIT_TOLERANCE = Decimal("0.02")
_JOURNAL_SOURCES = ("reviewed_local_import", "hashavshevet_mdb")


def _row_side(row_id: str) -> str:
    from .filing import PNL_ROWS
    for row in PNL_ROWS:
        if row["id"] == row_id:
            return row["side"]
    return "cost"


def _q(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _num(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _net(row, net_attr: str, gross_attr: str, tax_attr: str) -> Decimal:
    net = getattr(row, net_attr, None)
    if net is not None:
        return _num(net)
    return _num(getattr(row, gross_attr, None)) - _num(getattr(row, tax_attr, None))


def _alias(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text in _ALIASES:
        return _ALIASES[text]
    return _ALIASES.get(text.casefold())


def _month_end(day: date) -> date:
    nxt = date(day.year + 1, 1, 1) if day.month == 12 else date(day.year, day.month + 1, 1)
    return nxt - timedelta(days=1)


def _shift_months(day: date, back: int) -> date:
    year, month = day.year, day.month
    for _ in range(back):
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return date(year, month, 1)


def _windows(start: date, end: date):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        first = date(year, month, 1)
        last = _month_end(first)
        yield f"{year}-{month:02d}", max(first, start), min(last, end)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _explicit(raw) -> str | None:
    if not isinstance(raw, dict):
        return None
    for key in ("division", "activity"):
        found = _alias(raw.get(key))
        if found:
            return found
    return None


def _line_amount(item: dict) -> Decimal | None:
    for key in ("total", "amount"):
        if item.get(key) is not None:
            return _num(item.get(key))
    return None


def _slices(net: Decimal, raw, line_items, account_division: str | None) -> list[tuple[str, Decimal]]:
    items = line_items if isinstance(line_items, list) else []
    parsed = []
    for item in items:
        if not isinstance(item, dict):
            return [(_bucket(raw, account_division), net)]
        division = _alias(item.get("division") or item.get("activity"))
        amount = _line_amount(item)
        if division is None or amount is None:
            return [(_bucket(raw, account_division), net)]
        parsed.append((division, amount))
    if parsed and abs(sum((amount for _, amount in parsed), Decimal("0")) - net) <= _SPLIT_TOLERANCE:
        return parsed
    return [(_bucket(raw, account_division), net)]


def _bucket(raw, account_division: str | None) -> str:
    return _explicit(raw) or _alias(getattr(raw, "category", None) if not isinstance(raw, dict) else None) or account_division or CLARIFY


def _bucket_row(raw, account_division: str | None) -> str:
    found = _explicit(raw if isinstance(raw, dict) else None)
    if found:
        return found
    if not isinstance(raw, dict):
        found = _alias(getattr(raw, "category", None))
        if found:
            return found
    return account_division or CLARIFY


def _stale(db, organization_id: int, as_of: date) -> list[dict]:
    report = build_freshness(db, organization_id, today=as_of)
    out = []
    for item in report.get("items") or []:
        if item.get("status") != "stale":
            continue
        out.append({
            "kind": item.get("kind"),
            "kind_label": item.get("kind_label"),
            "label": item.get("label"),
            "source": item.get("source"),
            "source_label": item.get("source_label"),
            "last_date": item.get("last_date"),
            "age_days": item.get("age_days"),
            "status": item.get("status"),
            "status_label": item.get("status_label"),
        })
    return out


def _empty_divisions() -> dict[str, dict[str, Decimal]]:
    return {key: {"revenue": Decimal("0"), "costs": Decimal("0")} for key in DIVISIONS}


def validate_shared_cost_allocation(value) -> None:
    """Reject a plan key that would require inventing a percentage."""
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("מפתח החלוקה חייב להיות אובייקט לפי חודש")
    for month, cell in value.items():
        if not isinstance(month, str) or not _MONTH_KEY.fullmatch(month):
            raise ValueError("חודש החלוקה חייב להיות YYYY-MM")
        if not isinstance(cell, dict):
            raise ValueError("הגדרת החלוקה לא תקינה")
        method = cell.get("method")
        if method == "revenue_share":
            if set(cell) - {"method"}:
                raise ValueError("חלוקה לפי הכנסות אינה מקבלת אחוזים")
            continue
        if method != "manual":
            raise ValueError("שיטת החלוקה אינה מוכרת")
        percentages = cell.get("percentages")
        if not isinstance(percentages, dict) or not percentages or set(percentages) - set(SHARED_TARGETS):
            raise ValueError("חלוקה ידנית היא אחוזים לפיצה ולקולינרי בלבד")
        total = Decimal("0")
        for raw in percentages.values():
            number = _percent(raw)
            if number is None:
                raise ValueError("אחוז החלוקה חייב להיות בין 0 ל-100")
            total += number
        if total > Decimal("100"):
            raise ValueError("סכום האחוזים גדול מ-100")


def _percent(value) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        number = Decimal(str(value))
    except Exception:
        return None
    if not number.is_finite() or number < 0 or number > 100:
        return None
    return number


def _allocation_key(plan: dict, month: str) -> dict | None:
    raw = plan.get("sharedCostAllocation") if isinstance(plan, dict) else None
    if not isinstance(raw, dict):
        return None
    cell = raw.get(month)
    if not isinstance(cell, dict):
        return None
    try:
        validate_shared_cost_allocation({month: cell})
    except ValueError:
        return None
    if cell.get("method") == "revenue_share":
        return {"method": "revenue_share"}
    percentages = {
        key: _percent(cell["percentages"][key])
        for key in SHARED_TARGETS if key in cell.get("percentages", {})
    }
    if any(value is None for value in percentages.values()) or not percentages:
        return None
    return {"method": "manual", "percentages": percentages}


def _split(total: Decimal, weights: list[tuple[str, Decimal]]) -> dict[str, Decimal]:
    if not weights:
        return {}
    full = sum((weight for _, weight in weights), Decimal("0"))
    out: dict[str, Decimal] = {}
    running = Decimal("0")
    for index, (name, weight) in enumerate(weights):
        if index == len(weights) - 1 and full == 1:
            amount = _q(total - running)
        else:
            amount = _q(total * weight)
            running += amount
        out[name] = amount
    return out


def _allocate_shared(buckets: dict[str, dict[str, Decimal]], key: dict | None) -> tuple[dict[str, Decimal], dict]:
    """Allocate only after a valid key. Missing revenue does not become 50/50."""
    shared = buckets[SHARED]["costs"]
    info = {"applied": False, "method": None, "reason": None, "percentages": None, "derived_percentages": None}
    if key is None or shared == 0:
        return {}, info
    if key["method"] == "revenue_share":
        pizza = buckets["pizza"]["revenue"]
        culinary = buckets["culinary"]["revenue"]
        base = pizza + culinary
        if base == 0:
            info["method"] = "revenue_share"
            info["reason"] = "אין הכנסות פיצה או קולינרי בחודש, ולכן העלויות המשותפות לא חולקו"
            return {}, info
        weights = [("pizza", pizza / base), ("culinary", culinary / base)]
        info["derived_percentages"] = {
            name: float(_q(weight * Decimal(100))) for name, weight in weights
        }
    else:
        weights = [(name, pct / Decimal(100)) for name, pct in key["percentages"].items()]
        info["percentages"] = {name: float(pct) for name, pct in key["percentages"].items()}
    allocated = _split(shared, weights)
    info["applied"] = True
    info["method"] = key["method"]
    return allocated, info


def _division_rows(buckets: dict[str, dict[str, Decimal]] | None, allocated: dict[str, Decimal] | None = None,
                   applied: bool = False) -> list[dict] | None:
    if buckets is None:
        return None
    allocated = allocated or {}
    whole = sum((abs(side["revenue"]) + abs(side["costs"]) for side in buckets.values()), Decimal("0"))
    clarify = abs(buckets[CLARIFY]["revenue"]) + abs(buckets[CLARIFY]["costs"])
    share = None if whole == 0 else float(_q(clarify / whole * Decimal(100)))
    shared_total = buckets[SHARED]["costs"]
    allocated_sum = sum(allocated.values(), Decimal("0")) if applied else Decimal("0")
    remaining = shared_total - allocated_sum if applied else shared_total
    rows = []
    for key in DIVISIONS:
        side = buckets[key]
        own = side["revenue"] - side["costs"]
        row = {
            "id": key,
            "label": LABELS[key],
            "revenue": float(_q(side["revenue"])),
            "costs": float(_q(side["costs"])),
            "net": float(_q(own)),
            "profit_before_shared": None if key in (SHARED, CLARIFY) else float(_q(own)),
            "allocated_shared": None,
        }
        if key == CLARIFY:
            row["share_pct"] = share
        if key == SHARED:
            row["remaining"] = float(_q(remaining))
            row["allocation_applied"] = applied
        elif applied and key in allocated:
            row["allocated_shared"] = float(_q(allocated[key]))
            row["profit"] = float(_q(own - allocated[key]))
        elif key not in (SHARED, CLARIFY):
            row["profit"] = float(_q(own))
        rows.append(row)
    return rows


def _journal_slices(db, organization_id: int, start: date, end: date, plan: dict) -> dict[str, list]:
    try:
        overrides = source_journal.validate_account_map(plan.get("journalAccountMap"))
    except source_journal.JournalMapError:
        overrides = {}
    division_map = plan.get("divisionMap") if isinstance(plan.get("divisionMap"), dict) else {}
    entries = (
        db.query(JournalEntry)
        .filter(
            JournalEntry.organization_id == organization_id,
            JournalEntry.source.in_(_JOURNAL_SOURCES),
            JournalEntry.entry_date >= start,
            JournalEntry.entry_date <= end,
        )
        .all()
    )
    by_month: dict[str, list] = {}
    for entry in entries:
        if entry.entry_date is None:
            continue
        key = f"{entry.entry_date.year:04d}-{entry.entry_date.month:02d}"
        lines = entry.lines if isinstance(entry.lines, list) else []
        for line in lines:
            if not isinstance(line, dict):
                continue
            code = str(line.get("account") or "")
            mapped = source_journal.line_for(code, overrides) if code else None
            if mapped is None:
                continue
            row_id, _label = mapped
            side = "cost" if _row_side(row_id) == "cost" else "revenue"
            signed = _num(line.get("debit")) - _num(line.get("credit"))
            amount = signed if side == "cost" else -signed
            if amount == 0:
                continue
            division = _alias(division_map.get(code)) or CLARIFY
            by_month.setdefault(key, []).append({
                "kind": "journal",
                "id": entry.id,
                "side": side,
                "division": division,
                "net": amount,
                "account": code,
            })
    return by_month


def books_pnl(db, organization_id: int, *, as_of: date | None = None, months: int = 4,
              start: date | None = None, end: date | None = None,
              plan: dict | None = None, include_documents: bool = False) -> dict:
    """Last ``months`` calendar months ending at ``as_of``, unless ``start``/``end`` are set."""
    plan = plan if isinstance(plan, dict) else {}
    if start is None or end is None:
        as_of = as_of or date.today()
        end = as_of
        start = _shift_months(as_of, max(months, 1) - 1)
    else:
        as_of = end
    if end < start:
        raise ValueError("end date is before the start date")

    invoices = db.query(Invoice).filter(
        Invoice.organization_id == organization_id,
        Invoice.issue_date >= start,
        Invoice.issue_date <= end,
    ).all()
    bills = db.query(Bill).filter(
        Bill.organization_id == organization_id,
        Bill.issue_date >= start,
        Bill.issue_date <= end,
    ).all()
    expenses = db.query(Expense).filter(
        Expense.organization_id == organization_id,
        Expense.expense_date >= start,
        Expense.expense_date <= end,
    ).all()
    account_ids = {row.account_id for row in expenses if row.account_id}
    accounts = {}
    if account_ids:
        accounts = {
            row.id: row for row in db.query(Account).filter(Account.id.in_(account_ids)).all()
        }
    division_map = plan.get("divisionMap") if isinstance(plan.get("divisionMap"), dict) else {}
    journal = _journal_slices(db, organization_id, start, end, plan)
    bank_days = db.query(BankTransaction.transaction_date).filter(
        BankTransaction.organization_id == organization_id,
        BankTransaction.transaction_date >= start,
        BankTransaction.transaction_date <= end,
    ).all()
    bank_months = {
        f"{day.year:04d}-{day.month:02d}" for (day,) in bank_days if day is not None
    }

    def _account_division(row: Expense) -> str | None:
        account = accounts.get(row.account_id)
        if account is None:
            return None
        code = account.source_account_code or account.sumit_account_code
        return _alias(division_map.get(code)) if code else None

    docs: dict[str, list] = {}

    def _add(key: str, kind: str, row_id: int, side: str, net: Decimal, division: str):
        docs.setdefault(key, []).append({
            "kind": kind, "id": row_id, "side": side, "division": division, "net": net,
        })

    for row in invoices:
        if row.issue_date is None or not invoice_counts(row.status):
            continue
        key = f"{row.issue_date.year:04d}-{row.issue_date.month:02d}"
        net = _net(row, "subtotal", "total", "tax")
        for division, amount in _slices(net, row.raw_data, row.line_items, None):
            _add(key, "invoice", row.id, "revenue", amount, division)
    for row in bills:
        if row.issue_date is None or not bill_counts(row.status):
            continue
        key = f"{row.issue_date.year:04d}-{row.issue_date.month:02d}"
        net = _net(row, "subtotal", "total", "tax")
        for division, amount in _slices(net, row.raw_data, row.line_items, None):
            _add(key, "bill", row.id, "cost", amount, division)
    counted_bills: dict[str, set[str]] = {}
    for row in bills:
        if row.issue_date is None or not bill_counts(row.status) or not row.external_id:
            continue
        key = f"{row.issue_date.year:04d}-{row.issue_date.month:02d}"
        counted_bills.setdefault(key, set()).add(str(row.external_id))
    for row in expenses:
        if row.expense_date is None or not expense_counts(row.status):
            continue
        key = f"{row.expense_date.year:04d}-{row.expense_date.month:02d}"
        if row.external_id and str(row.external_id) in counted_bills.get(key, set()):
            continue
        net = _net(row, "amount", "total", "vat_amount")
        division = _bucket_row(row.raw_data, _account_division(row))
        if division == CLARIFY:
            division = _alias(row.category) or CLARIFY
        for part, amount in _slices(net, row.raw_data, None, division if division != CLARIFY else _account_division(row)):
            _add(key, "expense", row.id, "cost", amount, part)

    out_months = []
    for key, lo, hi in _windows(start, end):
        month_docs = [item for item in docs.get(key, []) if True]
        journal_rows = journal.get(key) or []
        partial = lo.day != 1 or hi != _month_end(lo)
        if month_docs:
            source = "documents"
            basis_label = BASIS_BOOKS
            used = month_docs
            journal_not_added = bool(journal_rows)
        elif journal_rows:
            source = "journal"
            basis_label = BASIS_JOURNAL
            used = [{**item, "net": item["net"]} for item in journal_rows]
            journal_not_added = False
        else:
            message = BASIS_NONE
            if key in bank_months:
                message = "אין נתוני ספרים. יש תנועות בנק בחודש; הן לא ממלאות את הרווח וההפסד."
            out_months.append({
                "month": key,
                "period_start": lo.isoformat(),
                "period_end": hi.isoformat(),
                "partial_month": partial,
                "basis": NO_BOOKS,
                "basis_label": BASIS_NONE,
                "source": None,
                "revenue": None,
                "costs": None,
                "net": None,
                "divisions": None,
                "clarify_share_pct": None,
                "document_count": 0,
                "journal_not_added": False,
                "bank_rows_present": key in bank_months,
                "message": message,
            })
            continue
        buckets = _empty_divisions()
        revenue = costs = Decimal("0")
        for item in used:
            amount = item["net"] if isinstance(item["net"], Decimal) else _num(item["net"])
            division = item["division"] if item["division"] in buckets else CLARIFY
            if item["side"] == "revenue":
                buckets[division]["revenue"] += amount
                revenue += amount
            else:
                buckets[division]["costs"] += amount
                costs += amount
        allocated, allocation = _allocate_shared(buckets, _allocation_key(plan, key))
        rows = _division_rows(buckets, allocated, allocation["applied"])
        clarify = next(row for row in rows if row["id"] == CLARIFY)
        public_docs = [
            {"kind": item["kind"], "id": item["id"], "side": item["side"],
             "division": item["division"], "net": float(_q(item["net"] if isinstance(item["net"], Decimal) else _num(item["net"])))}
            for item in used
        ]
        out_months.append({
            "month": key,
            "period_start": lo.isoformat(),
            "period_end": hi.isoformat(),
            "partial_month": partial,
            "basis": BOOKS,
            "basis_label": basis_label,
            "source": source,
            "revenue": float(_q(revenue)),
            "costs": float(_q(costs)),
            "net": float(_q(revenue - costs)),
            "divisions": rows,
            "clarify_share_pct": clarify.get("share_pct"),
            "shared_allocation": allocation,
            "document_count": len(used),
            "journal_not_added": journal_not_added,
            "bank_rows_present": key in bank_months,
            "message": basis_label,
            **({"documents": public_docs} if include_documents else {}),
        })
    try:
        line_budget = monthly_line_sums(validate_budget_lines(plan))
    except PlanBudgetError:
        line_budget = None
    sums = line_budget or {}
    for month in out_months:
        slot = sums.get(month["month"]) or {}
        month["budget_revenue"] = slot.get("revenue")
        month["budget_costs"] = slot.get("cost")
    known = [month for month in out_months if month["basis"] == BOOKS]
    return {
        "months": out_months,
        "basis": BOOKS if known and all(month["basis"] == BOOKS for month in out_months) else (
            "mixed" if known else NO_BOOKS
        ),
        "stale_sources": _stale(db, organization_id, as_of),
        "provider_calls": 0,
    }


def combine_books(parts: list[dict]) -> dict:
    """Sum entities only for a month every entity has books for. A gap stays no-books."""
    keys = []
    for part in parts:
        for month in part.get("months") or []:
            if month.get("month") not in keys:
                keys.append(month["month"])
    months = []
    for key in keys:
        group = []
        for part in parts:
            found = next((month for month in part.get("months") or [] if month.get("month") == key), None)
            group.append(found)
        if any(month is None or month.get("basis") != BOOKS for month in group):
            months.append({
                "month": key,
                "basis": NO_BOOKS,
                "basis_label": BASIS_NONE,
                "source": None,
                "revenue": None,
                "costs": None,
                "net": None,
                "divisions": None,
                "clarify_share_pct": None,
                "message": "אין נתוני ספרים לאחת הישויות בחודש, ולכן אין סכום מאוחד.",
            })
            continue
        buckets = _empty_divisions()
        for month in group:
            for row in month.get("divisions") or []:
                buckets[row["id"]]["revenue"] += _num(row.get("revenue"))
                buckets[row["id"]]["costs"] += _num(row.get("costs"))
        rows = _division_rows(buckets)
        revenue = sum((_num(month.get("revenue")) for month in group), Decimal("0"))
        costs = sum((_num(month.get("costs")) for month in group), Decimal("0"))
        months.append({
            "month": key,
            "basis": BOOKS,
            "basis_label": BASIS_BOOKS,
            "source": "combined",
            "revenue": float(_q(revenue)),
            "costs": float(_q(costs)),
            "net": float(_q(revenue - costs)),
            "divisions": rows,
            "clarify_share_pct": next(row for row in rows if row["id"] == CLARIFY).get("share_pct"),
            "message": BASIS_BOOKS,
        })
    seen = set()
    stale = []
    for part in parts:
        for item in part.get("stale_sources") or []:
            ident = (item.get("kind"), item.get("source"), item.get("label"), item.get("last_date"))
            if ident in seen:
                continue
            seen.add(ident)
            stale.append(item)
    known = [month for month in months if month["basis"] == BOOKS]
    return {
        "months": months,
        "basis": BOOKS if known and len(known) == len(months) else ("mixed" if known else NO_BOOKS),
        "stale_sources": stale,
        "provider_calls": 0,
    }
