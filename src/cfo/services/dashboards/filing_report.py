"""Filing report for the dashboard editor.

Classification stays in ``filing.classify_all``. This module only pages the
unresolved rows and counts how often each rule was the one that filed them.
"""
from __future__ import annotations

from . import filing

# Display-only: which compiled pattern to show next to a built-in category.
# Matching itself is ``filing.classify`` / ``classify_all``.
_KEYWORD_KEY = {
    "sales_card": "card_issuers_in",
    "card_bills": "card_issuers_out",
}


def build_filing_report(
    rows,
    payload: dict | None,
    *,
    page: int,
    page_size: int,
    invoices: list | None = None,
) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    decisions = payload.get("statusDecisions") if isinstance(payload.get("statusDecisions"), dict) else {}
    rules = [rule for rule in (payload.get("statusRules") or []) if isinstance(rule, dict)]
    txns = [filing.txn_from_row(row) for row in rows]
    scope = filing.scope_from_plan(payload)
    filed = filing.classify_all(
        txns, invoices=invoices, decisions=decisions, custom_rules=rules, scope=scope,
    )
    paired = [(txn, filed[id(txn)], filing.classify(txn, custom_rules=rules, scope=scope)) for txn in txns]
    return {
        "rules": [*_custom_rules(rules, paired), *_builtin_rules(paired)],
        "review": _review(paired, page=page, page_size=page_size),
        "categories": [
            {"key": key, "label_he": meta["label"]}
            for key, meta in filing.CATEGORIES.items()
            if key in filing.DECISION_CATEGORIES
        ],
        "unmatched_decisions": _unmatched(decisions, paired),
        "builtin_manifest": _manifest_status(payload),
    }


def _manifest_status(payload: dict) -> dict:
    manifest = filing.builtin_rules_manifest()
    pinned = payload.get("filingRulesBuiltin")
    pinned_sha = pinned.get("sha256") if isinstance(pinned, dict) else None
    return {
        "count": manifest["count"],
        "sha256": manifest["sha256"],
        "pinned_sha256": pinned_sha,
        "in_sync": None if pinned_sha is None else pinned_sha == manifest["sha256"],
    }


def _custom_rules(rules: list[dict], paired: list[tuple]) -> list[dict]:
    listed = []
    for rule in rules:
        token = f"custom_rule:{rule.get('id') or ''}"
        matches = [(txn, final) for txn, final, _preview in paired if final.filed_by == token]
        overridden = sum(
            1 for _txn, final, preview in paired
            if final.filed_by == "decision" and preview.filed_by == token
        )
        category = rule.get("category")
        listed.append({
            "id": str(rule.get("id") or ""),
            "source": "custom",
            "contains": str(rule.get("contains") or ""),
            "field": rule.get("field") or "description",
            "direction": rule.get("direction") or "both",
            "category": category,
            "category_he": filing.CATEGORIES.get(category, {}).get("label", category or ""),
            "organization_id": rule.get("organizationId") if isinstance(rule.get("organizationId"), int) else None,
            "match_count": len(matches),
            "overridden": overridden,
            "total": _total(matches),
        })
    return listed


def _builtin_rules(paired: list[tuple]) -> list[dict]:
    listed = []
    seen: set[str] = set()
    categories = [category for category, _test in filing.RULES]
    categories.append("intercompany")
    for category in categories:
        if category in seen:
            continue
        keywords = _keywords(category)
        fallback = category in filing.FALLBACK_RULES
        if not keywords and not fallback:
            continue
        seen.add(category)
        meta = filing.CATEGORIES.get(category, {})
        direction = meta.get("dir") if meta.get("dir") in {"in", "out", "both"} else "both"
        field = "counterparty" if category == "intercompany" else "description"
        matches = [(txn, final) for txn, final, _preview in paired if final.filed_by == f"rule:{category}"]
        overridden = sum(
            1 for _txn, final, _preview in paired
            if final.rule_category == category and (
                final.filed_by == "decision" or str(final.filed_by).startswith("custom_rule:")
            )
        )
        listed.append({
            "id": f"builtin:{category}",
            "source": "builtin",
            "contains": keywords,
            "field": field,
            "direction": direction,
            "category": category,
            "category_he": meta.get("label", category),
            "organization_id": None,
            "match_count": len(matches),
            "overridden": overridden,
            "total": _total(matches),
            "fallback": fallback,
        })
    return listed


def _keywords(category: str) -> str:
    if category == "intercompany":
        return filing.INTERCOMPANY_RULE_TEXT
    pattern = filing._R.get(_KEYWORD_KEY.get(category, category))
    return pattern.pattern if pattern is not None else ""


def _review(paired: list[tuple], *, page: int, page_size: int) -> dict:
    queued = [(txn, final) for txn, final, _preview in paired if final.category in filing.UNRESOLVED]
    start = (page - 1) * page_size
    return {
        "total": len(queued),
        "page": page,
        "page_size": page_size,
        "items": [_review_item(txn, final) for txn, final in queued[start:start + page_size]],
    }


def _review_item(txn: filing.Txn, final: filing.Filed) -> dict:
    counterparty = " ".join(part for part in (txn.debtor, txn.creditor) if part).strip()
    return {
        "id": str(txn.id),
        "organization_id": txn.organization_id,
        "date": txn.date,
        "description": txn.description or "",
        "counterparty": counterparty,
        "amount": txn.amount,
        "category": final.category,
        "filed_by": {"reason_he": _reason(final), "source": final.filed_by},
    }


def _reason(final: filing.Filed) -> str:
    label = filing.CATEGORIES.get(final.category, {}).get("label", final.category)
    filed_by = final.filed_by
    if filed_by == "decision":
        return f"החלטה ידנית · {label}"
    if str(filed_by).startswith("custom_rule:"):
        return f"כלל מותאם · {label}"
    if str(filed_by).startswith("rule:"):
        return f"כלל מובנה · {label}"
    if filed_by == "invoice_match":
        return "הותאם לחשבונית"
    if filed_by == "reversal_match":
        return "הותאם לביטול חיוב"
    if filed_by == "intercompany_match":
        return "העברה בין חברות"
    if filed_by == "intercompany_probable":
        return "העברה בין חברות (סביר)"
    return label


def _unmatched(decisions: dict, paired: list[tuple]) -> list[dict]:
    by_id = {str(txn.id): (txn, final) for txn, final, _preview in paired if txn.id is not None}
    unmatched = []
    for key, decision in decisions.items():
        if not isinstance(decision, dict):
            continue
        found = by_id.get(str(key))
        if found is None:
            unmatched.append({"transaction_id": str(key), "reason": "missing"})
            continue
        txn, final = found
        if final.filed_by == "decision":
            continue
        unmatched.append({"transaction_id": str(key), "reason": _mismatch_reason(decision, txn)})
    return unmatched


def _mismatch_reason(decision: dict, txn: filing.Txn) -> str:
    try:
        decided = float(decision.get("amount"))
    except (TypeError, ValueError):
        return "amount"
    if decision.get("organizationId") != txn.organization_id:
        return "organization"
    if decision.get("date") != txn.date:
        return "date"
    if abs(decided - txn.amount) >= 0.005:
        return "amount"
    if decision.get("category") not in filing.DECISION_CATEGORIES:
        return "category"
    return "mismatch"


def _total(matches: list[tuple]) -> float:
    return round(sum(abs(txn.amount) for txn, _final in matches), 2)
