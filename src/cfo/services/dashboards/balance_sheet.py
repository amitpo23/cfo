"""Balance sheet for the client dashboard.

Prefer a SUMIT portal balance-sheet export when one was imported. Otherwise
use the derived books already stored in Rezef (invoices, bills, expenses,
payments, journal). A section with no postings is unknown, not zero. A posted
zero stays zero. Every figure carries its source and sync time. No provider
calls, and portal rows are not added to the derived ledger.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func

from .. import ledger_service
from ..sumit_portal_export import SOURCE, SOURCE_LABEL, load_snapshots

DERIVED_SOURCE = "rezef_books"
DERIVED_LABEL = "ספרים ברצף (נגזר מהמסמכים)"
DERIVED_DISCLAIMER = "נגזר מהמסמכים שנשמרו ברצף. זה אינו המאזן הרשמי של SUMIT."
PORTAL_DISCLAIMER = "ייצוא שהועלה מפורטל SUMIT. זה אינו סנכרון API."


def _empty_section() -> dict:
    return {
        "status": "unknown",
        "total": None,
        "source": None,
        "source_label": None,
        "synced_at": None,
        "lines": [],
    }


def _empty_equity() -> dict:
    return {**_empty_section(), "opening_equity": None, "retained_earnings": None}


def _empty_profit() -> dict:
    return {
        "status": "unknown",
        "total_revenue": None,
        "total_expenses": None,
        "net": None,
        "lines": [],
        "unmapped": [],
        "unmapped_count": 0,
        "synced_at": None,
        "as_of": None,
        "source": None,
        "source_label": None,
    }


def _empty_cards() -> dict:
    return {
        "status": "unknown",
        "cards": [],
        "unmapped": [],
        "unmapped_count": 0,
        "total": None,
        "synced_at": None,
        "as_of": None,
        "source": None,
        "source_label": None,
    }


def _empty_imports() -> dict:
    return {"profit_loss": _empty_profit(), "ledger_cards": _empty_cards()}


def unknown_balance_sheet(message: str) -> dict:
    return {
        "status": "unknown",
        "basis": None,
        "basis_label": None,
        "as_of": None,
        "synced_at": None,
        "provider_calls": 0,
        "balanced": None,
        "message": message,
        "disclaimer": None,
        "assets": _empty_section(),
        "liabilities": _empty_section(),
        "equity": _empty_equity(),
        "unclassified": [],
        "unmapped": [],
        "imports": _empty_imports(),
    }


def _num(value) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal("0.01")))


def _total(lines: list[dict]) -> float | None:
    if not lines or any(line["amount"] is None for line in lines):
        return None
    return round(sum(line["amount"] for line in lines), 2)


def _section(lines: list[dict], *, source: str | None, source_label: str | None, synced_at: str | None) -> dict:
    if not lines:
        return _empty_section()
    total = _total(lines)
    return {
        "status": "ready" if total is not None else "partial",
        "total": total,
        "source": source,
        "source_label": source_label,
        "synced_at": synced_at,
        "lines": lines,
    }


def _figure(line: dict) -> dict:
    return {
        "code": line.get("code"),
        "name": line.get("name") or "",
        "amount": line.get("amount"),
        "mapped": line.get("mapped"),
        "reason": line.get("reason"),
        "source": line.get("source"),
        "source_label": line.get("source_label"),
        "synced_at": line.get("synced_at"),
    }


def _balanced(assets, liabilities, equity, *, incomplete: bool):
    totals = (assets["total"], liabilities["total"], equity["total"])
    if incomplete or any(total is None for total in totals):
        return None
    return abs(totals[0] - totals[1] - totals[2]) < 0.01


def _books_synced_at(db, organization_id: int, as_of: date) -> str | None:
    from ...models import Bill, Expense, Invoice, JournalEntry, Payment
    stamps = []
    for model, column in (
        (Invoice, Invoice.issue_date),
        (Bill, Bill.issue_date),
        (Expense, Expense.expense_date),
        (Payment, Payment.payment_date),
    ):
        stamp = db.query(func.max(model.created_at)).filter(
            model.organization_id == organization_id,
            column.isnot(None),
            column <= as_of,
        ).scalar()
        if stamp is not None:
            stamps.append(stamp)
    stamp = db.query(func.max(JournalEntry.created_at)).filter(
        JournalEntry.organization_id == organization_id,
        JournalEntry.entry_date <= as_of,
        JournalEntry.source != SOURCE,
    ).scalar()
    if stamp is not None:
        stamps.append(stamp)
    if not stamps:
        return None
    latest = max(stamps)
    return latest.isoformat() if hasattr(latest, "isoformat") else str(latest)


def _profit_view(snapshot: dict | None) -> dict:
    if not snapshot or not snapshot.get("lines"):
        return _empty_profit()
    placed = [line for line in snapshot["lines"] if line["applies"]]
    revenue = [_figure(line) for line in placed if line["section"] == "revenue"]
    expenses = [_figure(line) for line in placed if line["section"] == "expense"]
    total_revenue = _total(revenue)
    total_expenses = _total(expenses)
    unmapped = [_figure(line) for line in snapshot["lines"] if not line["mapped"] or not line["applies"]]
    if total_revenue is not None and total_expenses is not None and not unmapped:
        status = "ready"
    elif total_revenue is None and total_expenses is None and not placed:
        status = "unknown"
    else:
        status = "partial"
    net = None if total_revenue is None or total_expenses is None else round(total_revenue - total_expenses, 2)
    return {
        "status": status,
        "total_revenue": total_revenue,
        "total_expenses": total_expenses,
        "net": net,
        "lines": revenue + expenses,
        "unmapped": unmapped[:100],
        "unmapped_count": len(unmapped),
        "synced_at": snapshot.get("imported_at"),
        "as_of": snapshot.get("as_of"),
        "source": SOURCE,
        "source_label": SOURCE_LABEL,
    }


def _card_amount(group: list[dict]):
    dated = [line for line in group if line.get("movement_date") and line["amount"] is not None]
    if dated:
        return max(dated, key=lambda line: line["movement_date"])["amount"]
    if len(group) == 1:
        return group[0]["amount"]
    return None


def _cards_view(snapshot: dict | None) -> dict:
    if not snapshot or not snapshot.get("lines"):
        return _empty_cards()
    groups: dict[str, list] = {}
    for line in snapshot["lines"]:
        groups.setdefault(line["code"] or line["name"], []).append(line)
    cards = []
    for code, group in groups.items():
        head = group[0]
        cards.append({
            "code": head.get("code"),
            "name": head.get("name") or "",
            "amount": _card_amount(group),
            "mapped": all(line["mapped"] for line in group),
            "reason": next((line["reason"] for line in group if line.get("reason")), None),
            "movements": len(group),
            "source": SOURCE,
            "source_label": SOURCE_LABEL,
            "synced_at": snapshot.get("imported_at"),
        })
    cards.sort(key=lambda card: (card["code"] or "", card["name"]))
    unmapped = [card for card in cards if not card["mapped"]]
    if cards and all(card["amount"] is not None and card["mapped"] for card in cards):
        status = "ready"
    elif not cards:
        status = "unknown"
    else:
        status = "partial"
    return {
        "status": status,
        "cards": cards,
        "unmapped": unmapped[:100],
        "unmapped_count": len(unmapped),
        "total": None,
        "synced_at": snapshot.get("imported_at"),
        "as_of": snapshot.get("as_of"),
        "source": SOURCE,
        "source_label": SOURCE_LABEL,
    }


def _imports(snapshots: dict) -> dict:
    return {
        "profit_loss": _profit_view(snapshots.get("profit_loss")),
        "ledger_cards": _cards_view(snapshots.get("ledger_cards")),
    }


def _from_portal(snapshot: dict, imports: dict) -> dict:
    placed = [line for line in snapshot["lines"] if line["applies"] and line["section"] in {"asset", "liability", "equity"}]
    grouped = {"asset": [], "liability": [], "equity": []}
    for line in placed:
        grouped[line["section"]].append(_figure(line))
    source = {"source": SOURCE, "source_label": SOURCE_LABEL, "synced_at": snapshot.get("imported_at")}
    assets = _section(grouped["asset"], **source)
    liabilities = _section(grouped["liability"], **source)
    equity = {**_section(grouped["equity"], **source), "opening_equity": None, "retained_earnings": None}
    unplaced = [line for line in snapshot["lines"] if not line["applies"]]
    unmapped = [line for line in snapshot["lines"] if not line["mapped"] or not line["applies"]]
    incomplete = bool(unplaced)
    balanced = _balanced(assets, liabilities, equity, incomplete=incomplete)
    sections_ready = all(section["status"] == "ready" for section in (assets, liabilities, equity))
    if not snapshot["lines"]:
        status = "unknown"
    elif sections_ready and not unmapped and not incomplete:
        status = "ready"
    else:
        status = "partial"
    notes = [PORTAL_DISCLAIMER]
    if unmapped:
        notes.append(f"{len(unmapped)} שורות לא מופו לחשבון ברצף או לא נכללו בסעיף.")
    return {
        "status": status,
        "basis": SOURCE,
        "basis_label": SOURCE_LABEL,
        "as_of": snapshot.get("as_of"),
        "synced_at": snapshot.get("imported_at"),
        "provider_calls": 0,
        "balanced": balanced,
        "message": " ".join(notes),
        "disclaimer": PORTAL_DISCLAIMER,
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity,
        "unclassified": [],
        "unmapped": [_figure(line) for line in unmapped[:100]],
        "imports": imports,
    }


def _from_books(db, organization_id: int, as_of: date, imports: dict) -> dict:
    trial = ledger_service.trial_balance(db, organization_id, end=as_of)
    synced_at = _books_synced_at(db, organization_id, as_of)
    assets, liabilities, equity_lines, unclassified = [], [], [], []
    revenue = expenses = 0.0
    saw_pnl = False
    for account in trial["accounts"]:
        natural = round(account["debit"] - account["credit"], 2)
        figure = {
            "code": account["account"],
            "name": account["name"],
            "amount": None,
            "mapped": True,
            "reason": None,
            "source": DERIVED_SOURCE,
            "source_label": DERIVED_LABEL,
            "synced_at": synced_at,
        }
        if account["type"] == "asset":
            figure["amount"] = natural
            assets.append(figure)
        elif account["type"] == "liability":
            figure["amount"] = round(-natural, 2)
            liabilities.append(figure)
        elif account["type"] == "equity":
            figure["amount"] = round(-natural, 2)
            equity_lines.append(figure)
        elif account["type"] == "revenue":
            saw_pnl = True
            revenue += -natural
        elif account["type"] == "expense":
            saw_pnl = True
            expenses += natural
        else:
            figure["amount"] = natural
            figure["mapped"] = False
            figure["reason"] = "הכרטיס לא סווג לנכס, התחייבות או הון"
            unclassified.append(figure)
    meta = {"source": DERIVED_SOURCE, "source_label": DERIVED_LABEL, "synced_at": synced_at}
    asset_section = _section(assets, **meta) if assets else _empty_section()
    liability_section = _section(liabilities, **meta) if liabilities else _empty_section()
    opening = _total(equity_lines) if equity_lines else None
    retained = round(revenue - expenses, 2) if saw_pnl else None
    if equity_lines or retained is not None:
        equity = {
            "status": "ready" if opening is not None and retained is not None else "partial",
            "total": None if opening is None or retained is None else round(opening + retained, 2),
            "source": DERIVED_SOURCE,
            "source_label": DERIVED_LABEL,
            "synced_at": synced_at,
            "lines": equity_lines,
            "opening_equity": opening,
            "retained_earnings": retained,
        }
    else:
        equity = _empty_equity()
    nothing = (
        asset_section["status"] == "unknown"
        and liability_section["status"] == "unknown"
        and equity["status"] == "unknown"
        and not unclassified
    )
    if nothing:
        status = "unknown"
        message = "אין בספרים נכסים, התחייבויות או הון לתאריך הזה. חסר אינו אפס."
        header_sync = None
    else:
        ready = all(section["status"] == "ready" for section in (asset_section, liability_section, equity)) and not unclassified
        status = "ready" if ready else "partial"
        message = DERIVED_DISCLAIMER if ready else "חלק מהמאזן לא ידוע. חסר אינו אפס."
        header_sync = synced_at
    if trial.get("imported_warning_he"):
        message = f"{message} {trial['imported_warning_he']}"
    return {
        "status": status,
        "basis": None if nothing else DERIVED_SOURCE,
        "basis_label": None if nothing else DERIVED_LABEL,
        "as_of": as_of.isoformat(),
        "synced_at": header_sync,
        "provider_calls": 0,
        "balanced": _balanced(asset_section, liability_section, equity, incomplete=bool(unclassified)),
        "message": message,
        "disclaimer": None if nothing else DERIVED_DISCLAIMER,
        "assets": asset_section,
        "liabilities": liability_section,
        "equity": equity,
        "unclassified": unclassified,
        "unmapped": [],
        "imports": imports,
    }


def build_balance_sheet(db, organization_id: int, as_of: date) -> dict:
    snapshots = load_snapshots(db, organization_id)
    imports = _imports(snapshots)
    portal = snapshots.get("balance_sheet")
    if portal and portal.get("lines"):
        sheet = _from_portal(portal, imports)
        return sheet
    sheet = _from_books(db, organization_id, as_of, imports)
    return sheet
