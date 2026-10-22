"""Pizza revenue from Z reports (the Eliav tool's ``reviewed-evidence.json`` ``pizza_z``).

Rezef has no Z-report feed, so the reviewed monthly totals are entered on the
plan, owner only: ``plan.zReports`` =
``[{organizationId, month: "YYYY-MM", revenueExVat, totalInclVat?, cashNet?,
cardNet?, source, note?}]``, one item per organization and month. Two ways in:
the dashboard's owner form, and ``scripts/import_z_reports.py`` (the tool's
``pizza_z`` file, dry-run by default).

In the cash-basis P&L of that organization and month the Z total replaces the
till takings of the bank: the revenue row is the Z report's ``revenueExVat`` plus
the bank's other revenue (customer receipts by invoice, checks, approved other
income) ex-VAT; the bank's card settlements (``sales_card``) and cash deposits
(``sales_cash``) are the money of the same sales and are dropped. A books month
does not read Z reports. A month without bank rows stays unknown (its costs are
not known), and its Z report is still listed. No provider calls.
"""
from __future__ import annotations

import re

from . import filing

TILL_CATEGORIES = ("sales_card", "sales_cash")
SOURCE_LABEL = "דוח Z מאומת"
LIMIT = 120
_MONTH = re.compile(r"^20\d{2}-(0[1-9]|1[0-2])$")
_AMOUNTS = ("revenueExVat", "totalInclVat", "cashNet", "cardNet")
_KEYS = {"organizationId", "month", "source", "note", *_AMOUNTS}
MAX_AMOUNT = 1e9


class ZReportError(ValueError):
    pass


def _amount(value, *, required: bool) -> bool:
    if value is None:
        return not required
    return not isinstance(value, bool) and isinstance(value, (int, float)) and 0 <= value <= MAX_AMOUNT


def validate_z_reports(value) -> list:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > LIMIT:
        raise ZReportError(f"zReports must be a list of at most {LIMIT} months")
    seen = set()
    for item in value:
        if not isinstance(item, dict) or set(item) - _KEYS:
            raise ZReportError("zReports: invalid item")
        org = item.get("organizationId")
        if isinstance(org, bool) or not isinstance(org, int):
            raise ZReportError("zReports: organizationId required")
        month = item.get("month")
        if not isinstance(month, str) or not _MONTH.fullmatch(month):
            raise ZReportError("zReports: month must be YYYY-MM")
        if (org, month) in seen:
            raise ZReportError("zReports: one item per organization and month")
        seen.add((org, month))
        if not _amount(item.get("revenueExVat"), required=True):
            raise ZReportError("zReports: revenueExVat required")
        if not all(_amount(item.get(key), required=False) for key in _AMOUNTS[1:]):
            raise ZReportError("zReports: invalid amount")
        source = item.get("source")
        if not isinstance(source, str) or not source.strip() or len(source) > 300:
            raise ZReportError("zReports: source required")
        note = item.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > 300):
            raise ZReportError("zReports: invalid note")
    return value


def for_organization(plan: dict | None, organization_id: int) -> dict:
    """``{"YYYY-MM": item}`` of one organization; empty when the plan has none or is invalid."""
    plan = plan if isinstance(plan, dict) else {}
    try:
        items = validate_z_reports(plan.get("zReports"))
    except ZReportError:
        return {}
    return {item["month"]: item for item in items if item["organizationId"] == organization_id}


def merge_into_cash_month(cash: dict, z: dict | None, vat_rate: float = filing.VAT_RATE) -> dict:
    """The cash-basis month with the Z total in place of the bank's till takings."""
    if not z:
        return cash
    by_category = cash.get("by_category") or {}
    till = round(sum(by_category.get(c, 0.0) for c in TILL_CATEGORIES) / (1 + vat_rate), 2)
    merged = dict(cash)
    lines = []
    revenue = costs = 0.0
    for line in cash.get("lines") or []:
        line = dict(line)
        if line["id"] == "revenue":
            line["amount"] = round(line["amount"] - till + float(z["revenueExVat"]), 2)
            line["source"] = "z_report"
            line["vat_basis"] = "ex_vat"
        if line["side"] == "revenue":
            revenue += line["amount"]
        else:
            costs += line["amount"]
        lines.append(line)
    merged["lines"] = lines
    merged["revenue"] = round(revenue, 2)
    merged["costs"] = round(costs, 2)
    merged["net"] = round(revenue - costs, 2)
    merged["z_report"] = {
        "revenue_ex_vat": float(z["revenueExVat"]),
        "bank_till_dropped": till,
        "source": z["source"],
    }
    return merged


def summary(z: dict | None) -> dict | None:
    if not z:
        return None
    return {
        "source_label": SOURCE_LABEL,
        "revenue_ex_vat": float(z["revenueExVat"]),
        "total_incl_vat": z.get("totalInclVat"),
        "cash_net": z.get("cashNet"),
        "card_net": z.get("cardNet"),
        "source": z["source"],
        "note": z.get("note"),
    }


def from_tool_file(document: dict, organization_id: int, source: str) -> list[dict]:
    """The tool's ``reviewed-evidence.json`` ``pizza_z`` rows as ``plan.zReports`` items."""
    rows = document.get("pizza_z") if isinstance(document, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ZReportError("the file has no pizza_z rows")
    items = []
    for row in rows:
        if not isinstance(row, dict):
            raise ZReportError("pizza_z: invalid row")
        items.append({
            "organizationId": organization_id,
            "month": row.get("month"),
            "revenueExVat": row.get("revenue_ex_vat"),
            "totalInclVat": row.get("total_net_vat_included"),
            "cashNet": row.get("cash_net"),
            "cardNet": row.get("card_net"),
            "source": source,
        })
    validate_z_reports(items)
    return items


def merge_items(current: list | None, incoming: list[dict]) -> list[dict]:
    """``plan.zReports`` with the incoming months replacing the same (organization, month)."""
    keyed = {(item["organizationId"], item["month"]): item for item in incoming}
    kept = [item for item in current or [] if isinstance(item, dict)
            and (item.get("organizationId"), item.get("month")) not in keyed]
    return sorted(kept + incoming, key=lambda item: (item.get("organizationId") or 0, item.get("month") or ""))
