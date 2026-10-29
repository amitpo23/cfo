"""Unclassified bank transfers, with a suggestion the owner has to accept.

A suggestion is only the counterparty's own history or a rule the owner
already saved. Nothing here picks a category for a name it has not seen.
Accepting a real counterparty writes a rule, so the next transfer of that
name files the same way. A row with no counterparty is filed as a decision
on that transaction (its date, amount and description). No placeholder name
is stored. Coverage is signed: classified + unclassified = total.
"""
from __future__ import annotations

import re

from .filing import (
    CATEGORIES, DECISION_CATEGORIES, FALLBACK_RULES, UNRESOLVED, Filed, Txn,
    _party_text, displayed_counterparty,
)

_DATE_RE = re.compile(r"^20\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


def unclassified(filed: Filed) -> bool:
    """A catch-all bucket is not a category. An owner rule is."""
    if filed.filed_by.startswith("custom_rule:") or filed.filed_by == "decision":
        return False
    if filed.category in UNRESOLVED:
        return True
    return filed.category in FALLBACK_RULES and filed.filed_by in {"default", f"rule:{filed.category}"}


def _party(txn: Txn) -> str:
    return displayed_counterparty(txn)


def suggest(counterparty: str, classified: list[dict], rules: list[dict]) -> dict | None:
    """A labelled suggestion, or None. Never a guessed category."""
    party = (counterparty or "").strip()
    if not party:
        return None
    folded = party.casefold()
    for rule in rules or []:
        if not isinstance(rule, dict) or rule.get("category") not in DECISION_CATEGORIES:
            continue
        if (rule.get("field") or "description") != "counterparty":
            continue
        needle = str(rule.get("contains") or "").strip()
        if needle and needle.casefold() in folded:
            label = CATEGORIES.get(rule["category"], {}).get("label") or rule["category"]
            return {
                "category": rule["category"],
                "label_he": label,
                "suggestion": True,
                "source": "rule",
                "reason_he": f"הצעה: כלל שמור לצד הנגדי «{needle}» → {label}. לא סווג עד שהבעלים מאשר.",
            }
    counts: dict[str, int] = {}
    for row in classified:
        other = str(row.get("counterparty") or "").strip().casefold()
        category = row.get("category")
        if other == folded and category in DECISION_CATEGORIES:
            counts[category] = counts.get(category, 0) + 1
    if not counts:
        return None
    category = max(counts, key=lambda key: (counts[key], key))
    label = CATEGORIES.get(category, {}).get("label") or category
    return {
        "category": category,
        "label_he": label,
        "suggestion": True,
        "source": "counterparty_history",
        "reason_he": f"הצעה לפי היסטוריה: «{party}» סווג {counts[category]} פעמים כ{label}. לא סווג עד שהבעלים מאשר.",
    }


def coverage(rows: list[dict]) -> dict:
    classified_amount = round(sum(row["amount"] for row in rows if not row["unclassified"]), 2)
    unclassified_amount = round(sum(row["amount"] for row in rows if row["unclassified"]), 2)
    total = round(classified_amount + unclassified_amount, 2)
    by_category: dict[str, float] = {}
    for row in rows:
        if row["unclassified"]:
            continue
        key = row.get("category") or ""
        by_category[key] = round(by_category.get(key, 0.0) + row["amount"], 2)
    category_sum = round(sum(by_category.values()), 2)
    return {
        "classified": classified_amount,
        "unclassified": unclassified_amount,
        "total": total,
        "by_category": [
            {"category": key, "label_he": CATEGORIES.get(key, {}).get("label") or key, "amount": amount}
            for key, amount in sorted(by_category.items())
        ],
        "balanced": abs(total - (category_sum + unclassified_amount)) < 0.01,
        "unclassified_count": sum(1 for row in rows if row["unclassified"]),
    }


def queue_from_filed(paired: list[tuple[Txn, Filed]], rules: list | None = None) -> dict:
    rules = [rule for rule in (rules or []) if isinstance(rule, dict)]
    rows = []
    for txn, filed in paired:
        party = _party(txn)
        row = {
            "id": txn.id,
            "date": txn.date,
            "amount": round(float(txn.amount), 2),
            "counterparty": party,
            "description": txn.description or "",
            "category": None if unclassified(filed) else filed.category,
            "category_he": None if unclassified(filed) else (CATEGORIES.get(filed.category, {}).get("label") or filed.category),
            "unclassified": unclassified(filed),
            "suggestion": None,
        }
        rows.append(row)
    known = [row for row in rows if not row["unclassified"]]
    for row in rows:
        if row["unclassified"]:
            row["suggestion"] = suggest(row["counterparty"], known, rules)
    return {
        "rows": [row for row in rows if row["unclassified"]],
        "coverage": coverage(rows),
        "categories": [
            {"category": key, "label_he": CATEGORIES[key]["label"]}
            for key in sorted(DECISION_CATEGORIES)
        ],
        "provider_calls": 0,
    }


def load_queue(db, organization_id: int, start, end, plan: dict | None) -> dict:
    from .books import classified_bank
    paired = classified_bank(db, organization_id, start, end, plan)
    rules = plan.get("statusRules") if isinstance(plan, dict) else None
    report = queue_from_filed(paired, rules)
    report["start"] = start.isoformat()
    report["end"] = end.isoformat()
    return report


def _identity(item: dict) -> dict:
    txn_id = item.get("transaction_id")
    org_id = item.get("organization_id")
    when = item.get("date")
    amount = item.get("amount")
    if (
        isinstance(txn_id, bool) or not isinstance(txn_id, int) or txn_id <= 0
        or isinstance(org_id, bool) or not isinstance(org_id, int)
        or not isinstance(when, str) or _DATE_RE.fullmatch(when) is None
        or isinstance(amount, bool) or not isinstance(amount, (int, float))
        or abs(amount) > 1e9
    ):
        raise ValueError("בלי צד נגדי הסיווג נשמר לפי התנועה, התאריך והסכום")
    decision = {
        "category": item.get("category"),
        "organizationId": org_id,
        "date": when,
        "amount": round(float(amount), 2),
    }
    description = item.get("description")
    if isinstance(description, str) and description.strip():
        decision["description"] = description.strip()[:500]
    return {"id": txn_id, "decision": decision}


def bind_accepts(db, organization_id: int, accepts: list[dict]) -> list[dict]:
    """Fill date, amount and description from the bank row when the party is empty.

    The client does not get to choose those fields. A placeholder counterparty
    is treated as empty.
    """
    from ...models import BankTransaction

    bound = []
    for item in accepts:
        if not isinstance(item, dict):
            raise ValueError("אישור סיווג לא תקין")
        party = _party_text(item.get("counterparty"))
        if party:
            bound.append({"counterparty": party, "category": item.get("category")})
            continue
        txn_id = item.get("transaction_id")
        if isinstance(txn_id, bool) or not isinstance(txn_id, int) or txn_id <= 0:
            raise ValueError("בלי צד נגדי הסיווג נשמר לפי התנועה, התאריך והסכום")
        txn = db.get(BankTransaction, txn_id)
        if txn is None or txn.organization_id != organization_id:
            raise ValueError("התנועה לא נמצאה בארגון הזה")
        when = txn.transaction_date
        bound.append({
            "category": item.get("category"),
            "transaction_id": txn.id,
            "organization_id": txn.organization_id,
            "date": when.isoformat() if hasattr(when, "isoformat") else str(when),
            "amount": round(float(txn.amount), 2),
            "description": txn.description or "",
        })
    return bound


def apply_accepts(plan: dict | None, accepts: list[dict]) -> dict:
    """A named accept becomes a counterparty rule. An unnamed one files that row.

    Does not invent a category or a counterparty.
    """
    plan = dict(plan or {})
    rules = [dict(rule) for rule in (plan.get("statusRules") or []) if isinstance(rule, dict)]
    decisions = {
        str(key): dict(value)
        for key, value in (plan.get("statusDecisions") or {}).items()
        if isinstance(value, dict)
    }
    wrote_decision = False
    for item in accepts:
        if not isinstance(item, dict):
            raise ValueError("אישור סיווג לא תקין")
        category = item.get("category")
        if category not in DECISION_CATEGORIES:
            raise ValueError("צריך קטגוריה שהבעלים בחר")
        party = _party_text(item.get("counterparty"))
        if party:
            if any(
                rule.get("field") == "counterparty" and str(rule.get("contains") or "").strip() == party
                and rule.get("category") == category
                for rule in rules
            ):
                continue
            rules.append({
                "id": f"counterparty:{party}"[:80],
                "field": "counterparty",
                "contains": party[:120],
                "category": category,
                "direction": "both",
            })
            continue
        identity = _identity(item)
        decisions[str(identity["id"])] = identity["decision"]
        wrote_decision = True
    plan["statusRules"] = rules
    if wrote_decision or isinstance(plan.get("statusDecisions"), dict):
        plan["statusDecisions"] = decisions
    return plan
