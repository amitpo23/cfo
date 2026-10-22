"""The reviewed SUMIT journal of an import-only client (Food Group) in the P&L.

``local_client_service`` stores the journal under ``source='reviewed_local_import'``
with the source chart codes and keeps it out of the derived ledger. This module
maps those codes to the comparison rows of ``filing.PNL_ROWS`` so the cash-basis
P&L, budget vs actual and forecast of the organization can use it.

The mapping is the Eliav tool's draft (``journalAccountLine``), keyed to the
comparison rows. ``plan.journalAccountMap`` (``{"<code>": "<row id>" | null}``)
overrides it per exact code, so the bookkeeper's approved mapping replaces the
draft without a code change. Balance-sheet codes (banks 1xxxx, customers 3xxxx,
institutions 4xxxx, suppliers 5xxxx) are not P&L and are skipped.

Dedupe with the bank (one source per row per month):
the journal books the expense (net of VAT) and the bank shows its payment, so in a
month where the journal has an amount on a comparison row, that row takes the
journal amount and the bank amount of the row is dropped. Rows the journal does not
cover (revenue, payroll, ...) stay on the bank. A month without bank rows keeps an
unknown P&L: the journal has no revenue accounts, so the month has no revenue
source; its journal lines are still reported. A books month (ledger) never reads
the journal. No provider calls. Reads only.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from ...models import JournalEntry
from . import filing

SOURCE = "reviewed_local_import"
SOURCE_LABEL = "יומן SUMIT מיובא (מיפוי טיוטה)"
_CODE = re.compile(r"[A-Za-z0-9_.:-]{1,60}")
_ROW_IDS = {row["id"]: row for row in filing.PNL_ROWS}
_SIDES = {row["id"]: row["side"] for row in filing.PNL_ROWS}

# The tool's draft: (row id of filing.PNL_ROWS, the tool's own label).
_EXACT = {
    "90003": ("suppliers", "מזון וחומרי גלם"),
    "90004": ("suppliers", "משקאות"),
    "90005": ("suppliers", "אריזות"),
    "90050": ("vehicles", "דלק"),
    "99001": ("bank_fees", "עמלות בנק ואשראי"),
    "99002": ("interest", "ריבית"),
}


class JournalMapError(ValueError):
    pass


def validate_account_map(value) -> dict:
    """``plan.journalAccountMap``: exact source code -> comparison row id, or null to skip it."""
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 500:
        raise JournalMapError("journalAccountMap must be an object of at most 500 codes")
    out = {}
    for code, row in value.items():
        if not isinstance(code, str) or not _CODE.fullmatch(code):
            raise JournalMapError(f"journalAccountMap: invalid account code {code!r}")
        if row is not None and row not in _ROW_IDS:
            raise JournalMapError(f"journalAccountMap: unknown row {row!r} for {code}")
        out[code] = row
    return out


def default_line(code: str) -> tuple[str, str] | None:
    """The draft mapping of one source code, or None for a balance-sheet code."""
    code = str(code)
    if code in _EXACT:
        return _EXACT[code]
    if code.startswith("905"):
        return ("overhead", "אחזקה, הקמה ותפעול")
    if code.startswith("9"):
        return ("overhead", "הוצאה אחרת (9xxxx)")
    return None


def line_for(code: str, overrides: dict) -> tuple[str, str] | None:
    if code in overrides:
        row = overrides[code]
        return None if row is None else (row, _ROW_IDS[row]["label"])
    return default_line(code)


def _amount(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def journal_months(db, organization_id: int, start: date, end: date, plan: dict | None = None) -> dict:
    """``{"YYYY-MM": month}`` of the mapped journal. Empty when the organization has none.

    ``month``: ``rows`` (row id -> amount, cost positive / revenue positive),
    ``lines`` (per code), ``entries``, ``unbalanced`` and ``balance_only`` counts.
    """
    plan = plan if isinstance(plan, dict) else {}
    try:
        overrides = validate_account_map(plan.get("journalAccountMap"))
    except JournalMapError:
        overrides = {}
    entries = (
        db.query(JournalEntry)
        .filter(
            JournalEntry.organization_id == organization_id,
            JournalEntry.source == SOURCE,
            JournalEntry.entry_date >= start,
            JournalEntry.entry_date <= end,
        )
        .order_by(JournalEntry.entry_date, JournalEntry.id)
        .all()
    )
    out: dict[str, dict] = {}
    for entry in entries:
        key = entry.entry_date.strftime("%Y-%m")
        month = out.setdefault(key, {"rows": {}, "lines": {}, "entries": 0, "unbalanced": 0, "balance_only": 0})
        month["entries"] += 1
        lines = entry.lines if isinstance(entry.lines, list) else []
        debit = sum((_amount(line.get("debit")) for line in lines if isinstance(line, dict)), Decimal(0))
        credit = sum((_amount(line.get("credit")) for line in lines if isinstance(line, dict)), Decimal(0))
        if len(lines) < 2 or abs(debit - credit) > Decimal("0.01"):
            month["unbalanced"] += 1
        touched = False
        for line in lines:
            if not isinstance(line, dict):
                continue
            code = str(line.get("account") or "")
            mapped = line_for(code, overrides) if code else None
            if mapped is None:
                continue
            touched = True
            row_id, label = mapped
            signed = _amount(line.get("debit")) - _amount(line.get("credit"))
            value = float(signed if _SIDES[row_id] == "cost" else -signed)
            month["rows"][row_id] = month["rows"].get(row_id, 0.0) + value
            slot = month["lines"].setdefault(code, {"code": code, "label": label, "row": row_id, "amount": 0.0})
            slot["amount"] += value
        if not touched:
            month["balance_only"] += 1
    for month in out.values():
        month["rows"] = {key: round(value, 2) for key, value in month["rows"].items()}
        month["lines"] = sorted(
            ({**line, "amount": round(line["amount"], 2)} for line in month["lines"].values()),
            key=lambda line: (-abs(line["amount"]), line["code"]),
        )
    return out


def merge_into_cash_month(bank: dict, journal: dict | None) -> dict:
    """The cash-basis month with the journal's rows in place of the bank's (see module doc)."""
    if not journal or not journal.get("rows"):
        return bank
    merged = dict(bank)
    replaced = []
    lines = []
    revenue = costs = 0.0
    for line in bank.get("lines") or []:
        line = dict(line)
        if line["id"] in journal["rows"]:
            replaced.append({"id": line["id"], "label": line["label"], "bank_amount": line["amount"],
                             "journal_amount": journal["rows"][line["id"]]})
            line["amount"] = journal["rows"][line["id"]]
            line["source"] = "journal"
            line["vat_basis"] = "ex_vat"
        else:
            line["source"] = "bank"
        if line["side"] == "revenue":
            revenue += line["amount"]
        else:
            costs += line["amount"]
        lines.append(line)
    merged["lines"] = lines
    merged["revenue"] = round(revenue, 2)
    merged["costs"] = round(costs, 2)
    merged["net"] = round(revenue - costs, 2)
    merged["journal"] = {
        "rows_replaced": replaced,
        "bank_dropped": round(sum(item["bank_amount"] for item in replaced), 2),
        "journal_used": round(sum(item["journal_amount"] for item in replaced), 2),
    }
    return merged


def summary(journal: dict | None) -> dict | None:
    """The journal lines of one month as the view shows them."""
    if not journal:
        return None
    return {
        "source_label": SOURCE_LABEL,
        "lines": journal["lines"],
        "entries": journal["entries"],
        "unbalanced": journal["unbalanced"],
        "balance_only": journal["balance_only"],
    }
