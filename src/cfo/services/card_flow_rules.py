"""כללי מוצר לתנועות כרטיסי אשראי בבנק — מקום אחד לפער-המסמכים ולהתאמת הבנק.

מקס, ישראכרט וכאל הן גם חברות סליקה (כסף **נכנס** — מכירות בכרטיס) וגם
מנפיקות כרטיסי הוצאה (כסף **יוצא** — חיוב הכרטיס החודשי). לכן הכלל נקבע
לפי כיוון התנועה, לא לפי שם החברה:

* נכנס מחברת כרטיסים  -> ``clearing_income``: הפקדה נטו שבועית מול הרבה
  מכירות בכרטיס (N:1). העמלה = ברוטו − נטו; כשאין ברוטו — חסר, לא 0.
* יוצא לחברת כרטיסים -> ``card_settlement``: לא דורש חשבונית מס, ולא מוצע
  מול חשבון ספק/הוצאה. ההוצאות עצמן מתועדות ברמת שורת הכרטיס.

מילות המפתח נבדקות כמילה שלמה (``cal`` לא תופס ``medical``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable, Optional

CARD_COMPANY_TERMS = (
    "מקס", "max", "ישראכרט", "isracard", "כאל", 'כא"ל', "cal", "ויזה", "visa",
    "אמריקן אקספרס", "american express", "amex", "לאומי קארד", "diners", "דיינרס",
    "סליקה", 'שב"א',
)
OWNER_TERMS = (
    "משיכת בעלים", "משיכות בעלים", "הפקדת בעלים", 'חו"ז בעלים', "חו״ז בעלים",
    "הלוואת בעלים",
)

# הפקדת סליקה שבועית: מכירות מ-7 הימים שלפני ההפקדה, ועוד 3 ימי עסקים
# (א'–ה') לעיכובי זיכוי. מכירה שתאריכה אחרי ההפקדה לא נכללת.
CLEARING_CYCLE_DAYS = 7
CLEARING_SLACK_BUSINESS_DAYS = 3
# עמלת סליקה מעל 5% מהברוטו אינה עמלה סבירה — ייתכן שחסרות מכירות או
# שההפקדה כוללת יותר ממחזור אחד. לבדיקה ידנית, בלי עמלה.
CLEARING_FEE_CAP_RATE = 0.05

_WORD = r"[\w֐-׿]"
# אות יחס אחת בעברית לפני המונח ("לישראכרט", "ממקס").
_HEB_PREFIX = "(?:[ובלמה])?"


def _term_pattern(terms: Iterable[str]) -> re.Pattern:
    alts = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<!{_WORD}){_HEB_PREFIX}(?:{alts})(?!{_WORD})", re.IGNORECASE)


_CARD_RE = _term_pattern(CARD_COMPANY_TERMS)
# שמות עסקים שמכילים מונח של חברת כרטיסים אבל אינם חברת כרטיסים.
NOT_CARD_COMPANY_TERMS = ("מקס סטוק", "max stock")
_NOT_CARD_RE = _term_pattern(NOT_CARD_COMPANY_TERMS)
_OWNER_RE = _term_pattern(OWNER_TERMS)


def mentions_card_company(text: Optional[str]) -> bool:
    text = _NOT_CARD_RE.sub(" ", text or "")
    return bool(_CARD_RE.search(text))


def card_flow(description: Optional[str], amount: float) -> Optional[str]:
    """``clearing_income`` / ``card_settlement`` / None לפי כיוון ותיאור."""
    if not mentions_card_company(description):
        return None
    if amount > 0:
        return "clearing_income"
    if amount < 0:
        return "card_settlement"
    return None


def payee(row) -> Optional[str]:
    """הצד הנגדי משדות Open Finance שכבר על השורה (debtor/creditor, payee,
    merchant). "מטרת ההעברה" היא הערה, לא נמען — לא נלקחת. אין שם — None."""
    from .dashboards.filing import (
        _EXPLICIT_PARTY_KEYS, _additional_info, _named, parties_from_raw,
    )

    raw = getattr(row, "raw_data", None)
    debtor, creditor, _label = parties_from_raw(raw, getattr(row, "description", "") or "")
    amount = float(getattr(row, "amount", 0) or 0)
    party = (creditor or debtor) if amount < 0 else (debtor or creditor)
    if party:
        return party
    raw = raw if isinstance(raw, dict) else {}
    return _named([raw, _additional_info(raw)], _EXPLICIT_PARTY_KEYS) or None


def is_owner_transfer(row, owner_aliases: Optional[list] = None) -> bool:
    """מילת בעלים מפורשת בתיאור, או צד נגדי שמופיע בכינויי הבעלים של הארגון."""
    description = getattr(row, "description", "") or ""
    if _OWNER_RE.search(description):
        return True
    if not owner_aliases:
        return False
    from .dashboards.filing import is_intercompany_counterparty

    return is_intercompany_counterparty(payee(row) or "", aliases=owner_aliases)


def owner_aliases_for_org(db, organization_id: int) -> list[str]:
    """כינויי בעלים מכללי התיוק השמורים (``plan.statusRules`` בקטגוריה
    ``owner_draws``) של לוחות הארגון — אותו כלל שמור, בלי סכימת plan חדשה."""
    from ..models import ClientDashboard, DashboardPlan

    rows = (db.query(DashboardPlan.payload)
            .join(ClientDashboard, ClientDashboard.id == DashboardPlan.dashboard_id)
            .filter(ClientDashboard.primary_organization_id == organization_id).all())
    aliases: list[str] = []
    for (payload,) in rows:
        for rule in (payload or {}).get("statusRules") or []:
            if (isinstance(rule, dict) and rule.get("category") == "owner_draws"
                    and rule.get("direction", "both") in ("out", "both")
                    and isinstance(rule.get("contains"), str) and rule["contains"].strip()):
                aliases.append(rule["contains"].strip())
    return sorted(set(aliases))


# --------------------------------------------------------------------- #
# הפקדת סליקה <-> מכירות בכרטיס
# --------------------------------------------------------------------- #
@dataclass
class CardSale:
    id: Any
    amount: float  # ברוטו, חיובי
    date: date


def _minus_business_days(day: date, n: int) -> date:
    """ימי עסקים בישראל: א'–ה' (ו' ושבת אינם)."""
    while n > 0:
        day -= timedelta(days=1)
        if day.weekday() not in (4, 5):  # Friday, Saturday
            n -= 1
    return day


def clearing_window(deposit_date: date) -> tuple[date, date]:
    start = _minus_business_days(deposit_date - timedelta(days=CLEARING_CYCLE_DAYS),
                                 CLEARING_SLACK_BUSINESS_DAYS)
    return start, deposit_date


def match_clearing_deposit(net: float, deposit_date: date, sales: list[CardSale], *,
                           as_of: date, used: Optional[set] = None) -> dict[str, Any]:
    """הצעת התאמה (לא אישור) של הפקדת סליקה נטו מול מכירות בכרטיס בחלון."""
    start, end = clearing_window(deposit_date)
    picked = [s for s in sales
              if s.date and start <= s.date <= end and s.amount > 0
              and (used is None or s.id not in used)]
    base = {
        "net": round(net, 2), "window": [start.isoformat(), end.isoformat()],
        "as_of": as_of.isoformat(), "sale_ids": [s.id for s in picked],
        "gross": None, "fee": None, "fee_rate": None,
    }
    if not picked:
        return {**base, "status": "missing", "reason": "no_card_sales_in_window"}
    gross = round(sum(s.amount for s in picked), 2)
    fee = round(gross - net, 2)
    base["gross"] = gross
    if fee < 0:
        return {**base, "status": "review", "reason": "net_exceeds_gross"}
    if fee > gross * CLEARING_FEE_CAP_RATE:
        return {**base, "status": "review", "reason": "fee_above_cap"}
    return {**base, "status": "candidate", "reason": "identity_review_required",
            "fee": fee, "fee_rate": round(fee / gross, 4)}


def match_clearing_deposits(deposits: list[tuple[Any, float, date]], sales: list[CardSale], *,
                            as_of: date) -> list[dict[str, Any]]:
    """לפי סדר תאריכים; מכירה שהוצעה להפקדה אחת לא מוצעת לבאה."""
    used: set = set()
    out = []
    for txn_id, net, when in sorted(deposits, key=lambda d: (d[2], str(d[0]))):
        m = match_clearing_deposit(net, when, sales, as_of=as_of, used=used)
        if m["status"] == "candidate":
            used.update(m["sale_ids"])
        out.append({"bank_txn_id": txn_id, **m})
    return out


def load_card_sales(db, organization_id: int) -> list[CardSale]:
    """מכירות בכרטיס לפי ראיה מפורשת בלבד: Payment.method='credit_card', או
    חשבונית SUMIT שב-raw_data.Payments שלה יש Type='CreditCard'. אין
    ראיה — לא נחשב מכירת כרטיס (ואז ההצעה 'missing', לא ניחוש)."""
    from ..models import Invoice, Payment

    sales: list[CardSale] = []
    for p in db.query(Payment).filter(Payment.organization_id == organization_id,
                                      Payment.method == "credit_card").all():
        if p.payment_date and p.amount:
            sales.append(CardSale(id=f"payment:{p.id}", amount=float(p.amount), date=p.payment_date))
    for inv in db.query(Invoice).filter(Invoice.organization_id == organization_id).all():
        raw = inv.raw_data if isinstance(inv.raw_data, dict) else {}
        pays = raw.get("Payments") if isinstance(raw.get("Payments"), list) else []
        card = sum(float(p.get("Amount") or 0) for p in pays
                   if isinstance(p, dict) and str(p.get("Type") or "").lower() == "creditcard")
        when = inv.issue_date or inv.due_date
        if card > 0 and when:
            sales.append(CardSale(id=f"invoice:{inv.id}", amount=round(card, 2), date=when))
    return sales
