"""Filing (תיוק) of bank rows into cash-flow lines. Pure functions, no provider calls.

A one-to-one port of the built-in rules of the Eliav tool
(``lib/status-model.js``: ``CATEGORIES``, ``rules`` and ``classifyTxn``), so
Rezef and the tool file every row the same way. Order of precedence:

1. a manager decision (``plan.statusDecisions[bank_id]``) that still matches
   the row (organization, date, amount within 0.005);
2. a custom rule (``plan.statusRules``), first match wins;
3. the built-in rules below, first match wins.

Every result carries ``filed_by`` so the dashboard can say why a row landed
where it did. Unresolved categories ("לבירור") are never forced into a line.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

VAT_RATE = 0.18

CATEGORIES: dict[str, dict] = {
    # inflows
    "sales_card": {"label": "סליקת אשראי (מכירות)", "group": "operating", "dir": "in"},
    "sales_cash": {"label": "הפקדות מזומן (מכירות)", "group": "operating", "dir": "in"},
    "customer_receipts": {"label": "תקבולים מלקוחות לפי חשבונית", "group": "operating", "dir": "in"},
    "customer_checks": {"label": "הפקדות שיקים", "group": "operating", "dir": "in"},
    "other_in": {"label": "תקבולים אחרים — לבירור", "group": "operating", "dir": "in", "review": True, "unresolved": True},
    "other_income": {"label": "הכנסות אחרות (אושר ידנית)", "group": "operating", "dir": "in", "manual": True},
    "tax_refund": {"label": "החזרי מע״מ ומסים", "group": "tax", "dir": "in"},
    # outflows
    "card_bills": {"label": "חיובי כרטיסי אשראי (רכישות)", "group": "operating", "dir": "out"},
    "supplier_checks": {"label": "שיקים שנפרעו (ספקים)", "group": "operating", "dir": "out"},
    "fuel_energy": {"label": "דלק ואנרגיה", "group": "operating", "dir": "out"},
    "vehicles": {"label": "ליסינג ורכבים", "group": "operating", "dir": "out"},
    "national_insurance": {"label": "ביטוח לאומי", "group": "operating", "dir": "out"},
    "pension_insurance": {"label": "פנסיה וביטוחים", "group": "operating", "dir": "out"},
    "office": {"label": "תקשורת ומשרד", "group": "operating", "dir": "out"},
    "cash_withdrawals": {"label": "משיכות מזומן", "group": "operating", "dir": "out", "review": True},
    "suppliers_direct": {"label": "ספקים בהוראת קבע / חיוב ישיר", "group": "operating", "dir": "out"},
    "supplier_transfers": {"label": "ספקים בהעברה בנקאית (אושר ידנית)", "group": "operating", "dir": "out", "manual": True},
    "salaries": {"label": "שכר עובדים (אושר ידנית)", "group": "operating", "dir": "out", "manual": True},
    "rent": {"label": "שכירות (אושר ידנית)", "group": "operating", "dir": "out", "manual": True},
    "transfers_out": {"label": "העברות יוצאות — לבירור (ספקים/שכר)", "group": "operating", "dir": "out", "review": True, "unresolved": True},
    "taxes_paid": {"label": "תשלומי מע״מ ומסים (אושר ידנית)", "group": "tax", "dir": "out", "manual": True},
    "owner_draws": {"label": "משיכות והפקדות בעלים (אושר ידנית)", "group": "financing", "dir": "both", "manual": True},
    # below the operating line
    "bank_fees": {"label": "עמלות בנק", "group": "finance", "dir": "out"},
    "interest": {"label": "ריבית", "group": "finance", "dir": "both"},
    "loans_in": {"label": "הלוואות שהתקבלו", "group": "financing", "dir": "in"},
    "loans_out": {"label": "החזרי הלוואות ומימון", "group": "financing", "dir": "out"},
    "check_discounting": {"label": "ניכיון שיקים (מימון)", "group": "financing", "dir": "in"},
    "intercompany": {"label": "העברות בין השף לפוד גרופ", "group": "internal", "dir": "both"},
    "reversal": {"label": "חיובים שבוטלו והחזרם", "group": "internal", "dir": "both"},
    "bank_journal": {"label": "זיכויי יומן בנק — לבירור", "group": "operating", "dir": "in", "review": True, "unresolved": True},
}
DECISION_CATEGORIES = frozenset(k for k, v in CATEGORIES.items() if not v.get("unresolved"))
UNRESOLVED = frozenset(k for k, v in CATEGORIES.items() if v.get("unresolved"))


def _re(pattern: str, flags: int = 0):
    return re.compile(pattern, flags)


_R = {
    "card_issuers_in": _re(r'מקס איט|ישראכרט|כאל|כא"ל|ויזה|אמריקן|לאומי קארד|סליקה|שב"א'),
    "card_issuers_out": _re(r'ויזה|כא"ל|כאל|ישראכרט|מקס איט|אמריקן|לאומי קארד'),
    "check_discounting": _re(r"צ'קים דחויים|שיקים דחויים|ניכיון"),
    "loans_in": _re(r"הלואה קרן|הלוואה קרן|העמדת הלוואה|הלוואה-ז|הלואה-ז"),
    "loans_out": _re(r"הלוואה|הלואה|מימון ישיר|פרעון הלוואה|פיגור|קרן/כללי"),
    "interest": _re(r"ריבית|רבית"),
    "bank_fees": _re(r"עמלת|עמלה|ע\.מפעולות|ע\.טיפול|עמ'|דמי טפול|פנקסי שיקים"),
    "tax_refund": _re(r'מכס ומע|מע"מ|מע”מ|רשות המסים'),
    "sales_cash": _re(r"הפקדת מזומן|ה\.מזומן|הפק מזומן"),
    "customer_checks": _re(r"הפקדת שיק"),
    "reversal": _re(r"החזר חיוב|תיקון חובה|ביטול חיוב"),
    "bank_journal": _re(r"יומן זכות|העברת יומן"),
    "supplier_checks": _re(r"פירעון שיק|^שיק|שיקים עסקיים"),
    "national_insurance": _re(r"ביטוח לאומי|ב\. לאומי"),
    "pension_insurance": _re(r"מנורה|פנסיה|ניוד|הראל|כלל חיים|מגדל|פניקס|קרן בטחונות"),
    "fuel_energy": _re(r"אנרגיה|דלק|פז |סונול|דור אלון|ten|טן חברה"),
    "vehicles": _re(r"ליסינג|השכרת רכב|ליס קום"),
    "office": _re(r"בזק|טלפון|פרטנר|סלקום|הוט |אינטרנט רימון|גוגל|google", re.IGNORECASE),
    "cash_withdrawals": _re(r"משיכת מזומן|כספ\.|כספומט"),
    "transfers_out": _re(r"העברה|העב'"),
    "food_group": _re(r"פוד.?גרו"),
}

# (category, test(description, amount)) — same order as the tool.
RULES: list[tuple[str, callable]] = [
    ("sales_card", lambda d, a: a > 0 and bool(_R["card_issuers_in"].search(d))),
    ("card_bills", lambda d, a: a < 0 and bool(_R["card_issuers_out"].search(d))),
    ("check_discounting", lambda d, a: bool(_R["check_discounting"].search(d))),
    ("loans_in", lambda d, a: a > 0 and bool(_R["loans_in"].search(d))),
    ("loans_out", lambda d, a: bool(_R["loans_out"].search(d))),
    ("interest", lambda d, a: bool(_R["interest"].search(d))),
    ("bank_fees", lambda d, a: bool(_R["bank_fees"].search(d))),
    ("tax_refund", lambda d, a: a > 0 and bool(_R["tax_refund"].search(d))),
    ("sales_cash", lambda d, a: a > 0 and bool(_R["sales_cash"].search(d))),
    ("customer_checks", lambda d, a: a > 0 and bool(_R["customer_checks"].search(d))),
    ("reversal", lambda d, a: a > 0 and bool(_R["reversal"].search(d))),
    ("bank_journal", lambda d, a: a > 0 and bool(_R["bank_journal"].search(d))),
    ("supplier_checks", lambda d, a: a < 0 and bool(_R["supplier_checks"].search(d))),
    ("national_insurance", lambda d, a: bool(_R["national_insurance"].search(d))),
    ("pension_insurance", lambda d, a: bool(_R["pension_insurance"].search(d))),
    ("fuel_energy", lambda d, a: bool(_R["fuel_energy"].search(d))),
    ("vehicles", lambda d, a: bool(_R["vehicles"].search(d))),
    ("office", lambda d, a: bool(_R["office"].search(d))),
    ("cash_withdrawals", lambda d, a: bool(_R["cash_withdrawals"].search(d))),
    ("transfers_out", lambda d, a: a < 0 and bool(_R["transfers_out"].search(d))),
    ("other_in", lambda d, a: a > 0),
    ("suppliers_direct", lambda d, a: a < 0),
]

# Intercompany shortcut of the tool: chef checking account 35 or Food Group org 6.
CHEF_ORG, CHEF_ACCOUNT, FOOD_GROUP_ORG = 2, 35, 6


@dataclass
class Txn:
    id: int | None
    organization_id: int
    account_id: int | None
    date: str  # YYYY-MM-DD
    amount: float
    description: str = ""
    debtor: str = ""
    creditor: str = ""


@dataclass
class Filed:
    category: str
    filed_by: str  # decision | custom_rule:<id> | rule:<category> | default
    rule_category: str
    decision_mismatch: bool = False
    extra: dict = field(default_factory=dict)


def classify_builtin(t: Txn) -> tuple[str, str]:
    d = t.description or ""
    if _R["food_group"].search(t.debtor or "") or _R["food_group"].search(t.creditor or ""):
        if (t.organization_id == CHEF_ORG and t.account_id == CHEF_ACCOUNT) or t.organization_id == FOOD_GROUP_ORG:
            return "intercompany", "rule:intercompany"
    for category, test in RULES:
        if test(d, t.amount):
            return category, f"rule:{category}"
    return ("other_in" if t.amount > 0 else "suppliers_direct"), "default"


def _custom_match(rule: dict, t: Txn) -> bool:
    needle = str(rule.get("contains") or "").strip()
    if not needle:
        return False
    org = rule.get("organizationId")
    if org not in (None, "", "all") and org != t.organization_id:
        return False
    direction = rule.get("direction") or "both"
    if direction == "in" and t.amount <= 0 or direction == "out" and t.amount >= 0:
        return False
    fieldname = rule.get("field") or "description"
    if fieldname == "counterparty":
        haystack = f"{t.debtor or ''} {t.creditor or ''}"
    elif fieldname == "any":
        haystack = f"{t.description or ''} {t.debtor or ''} {t.creditor or ''}"
    else:
        haystack = t.description or ""
    return needle.casefold() in haystack.casefold()


def _decision_fits(decision: dict, t: Txn) -> bool:
    try:
        amount_ok = abs(float(decision.get("amount")) - t.amount) < 0.005
    except (TypeError, ValueError):
        return False
    return (
        decision.get("organizationId") == t.organization_id
        and decision.get("date") == t.date
        and amount_ok
        and decision.get("category") in DECISION_CATEGORIES
    )


def classify(t: Txn, *, decisions: dict | None = None, custom_rules: list | None = None) -> Filed:
    rule_category, rule_by = classify_builtin(t)
    decision = (decisions or {}).get(str(t.id)) if t.id is not None else None
    if decision is not None and _decision_fits(decision, t):
        return Filed(decision["category"], "decision", rule_category)
    for rule in custom_rules or []:
        if isinstance(rule, dict) and rule.get("category") in DECISION_CATEGORIES and _custom_match(rule, t):
            return Filed(rule["category"], f"custom_rule:{rule.get('id') or ''}", rule_category,
                         decision_mismatch=decision is not None)
    return Filed(rule_category, rule_by, rule_category, decision_mismatch=decision is not None)


def txn_from_row(row) -> Txn:
    raw = row.raw_data if isinstance(getattr(row, "raw_data", None), dict) else {}
    when = row.transaction_date
    return Txn(
        id=row.id,
        organization_id=row.organization_id,
        account_id=row.account_id,
        date=when.isoformat() if isinstance(when, date) else str(when),
        amount=float(row.amount or 0),
        description=row.description or "",
        debtor=str(raw.get("debtorName") or ""),
        creditor=str(raw.get("creditorName") or ""),
    )


# Comparison rows of the tool (budget-model.js COMPARISON_ROWS): which filing
# categories feed each P&L line, and whether the bank amount carries VAT.
REVENUE_CATS = ("sales_card", "sales_cash", "customer_receipts", "customer_checks", "other_income")
PNL_ROWS: list[dict] = [
    {"id": "revenue", "label": "הכנסות (סליקה, מזומן, לקוחות)", "side": "revenue", "cats": REVENUE_CATS, "vat": True},
    {"id": "payroll", "label": "כוח אדם", "side": "cost", "cats": ("salaries", "national_insurance", "pension_insurance"), "vat": False},
    {"id": "suppliers", "label": "ספקים ורכש", "side": "cost", "cats": ("card_bills", "supplier_checks", "suppliers_direct", "supplier_transfers"), "vat": True},
    {"id": "vehicles", "label": "רכבים — תפעול ודלק", "side": "cost", "cats": ("vehicles", "fuel_energy"), "vat": True},
    {"id": "overhead", "label": "הנהלה וכלליות", "side": "cost", "cats": ("office", "rent"), "vat": True},
    {"id": "bank_fees", "label": "עמלות בנק", "side": "cost", "cats": ("bank_fees",), "vat": False},
    {"id": "interest", "label": "ריבית", "side": "cost", "cats": ("interest",), "vat": False},
]
# Rows that can hold wages or supplier money; a big unresolved amount hides their variance.
UNASSIGNED_BLOCK = 5000.0
BLOCKABLE = frozenset({"payroll", "suppliers"})


def _days(a: str, b: str) -> float:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def classify_all(
    txns: list[Txn],
    *,
    invoices: list[dict] | None = None,
    decisions: dict | None = None,
    custom_rules: list | None = None,
) -> dict[int, Filed]:
    """Port of ``classifyAll``: rules first, then evidence that crosses rows.

    ``invoices`` items are ``{"organization_id", "number", "date", "total"}``.
    Rows locked by a decision keep the decided category. Input rows must be
    BOOKED rows only (the caller filters PENDING).
    """
    out: dict[int, Filed] = {}
    for t in txns:
        out[id(t)] = classify(t, decisions=decisions, custom_rules=custom_rules)

    def locked(t: Txn) -> bool:
        return out[id(t)].filed_by == "decision"

    # Invoice matching: inflows filed as other_in / bank_journal that equal an
    # invoice of the same organization (the tool does this for the chef only).
    open_inv = [dict(i, used=False) for i in (invoices or []) if float(i.get("total") or 0) > 0]
    for t in txns:
        f = out[id(t)]
        if locked(t) or t.amount <= 0:
            continue
        if f.category not in ("other_in", "bank_journal"):
            continue
        cands = []
        for inv in open_inv:
            if inv["used"] or inv.get("organization_id") != t.organization_id:
                continue
            if abs(float(inv["total"]) - t.amount) >= 1:
                continue
            lag = (date.fromisoformat(t.date) - date.fromisoformat(str(inv["date"]))).days
            if -10 <= lag <= 150:
                cands.append(inv)
        if not cands:
            continue
        cands[0]["used"] = True
        f.category = "customer_receipts"
        f.filed_by = "invoice_match"
        f.extra["invoice"] = cands[0].get("number") if len(cands) == 1 else [c.get("number") for c in cands]

    # Reversals: a charge followed by an equal refund within 20 days.
    for r in txns:
        if out[id(r)].category != "reversal":
            continue
        for c in txns:
            fc = out[id(c)]
            if c is r or locked(c) or c.amount >= 0 or c.account_id != r.account_id:
                continue
            if abs(c.amount + r.amount) < 0.01 and _days(c.date, r.date) <= 20 and fc.category != "reversal":
                fc.category = "reversal"
                fc.filed_by = "reversal_match"
                break

    # Intercompany: chef inflow vs Food Group outflow of the same amount (±4 days).
    company_out = [c for c in txns if c.organization_id == FOOD_GROUP_ORG and c.amount < 0
                   and out[id(c)].category in ("transfers_out", "intercompany")]
    matched: set[int] = set()
    for t in txns:
        f = out[id(t)]
        if not (t.organization_id == CHEF_ORG and t.account_id == CHEF_ACCOUNT and t.amount > 0):
            continue
        if not (f.category == "intercompany" or (not locked(t) and "בנק הפועלים" in (t.description or ""))):
            continue
        m = next((c for c in company_out if id(c) not in matched
                  and abs(c.amount + t.amount) < 0.01 and _days(c.date, t.date) <= 4), None)
        if m is not None:
            matched.add(id(m))
            if not locked(m):
                out[id(m)].category = "intercompany"
                out[id(m)].filed_by = "intercompany_match"
            if not locked(t):
                f.category = "intercompany"
                f.filed_by = "intercompany_match"
        elif not locked(t) and f.category != "intercompany":
            f.category = "intercompany"
            f.filed_by = "intercompany_probable"
            f.extra["probable"] = True
    return out
