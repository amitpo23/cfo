"""
Bank Intelligence — derive actionable insights from Open Finance bank-statement data.

The engine is a set of pure analyzer functions over an in-memory list of `Txn`
records (extracted from `BankTransaction` rows + their Open Finance `raw_data`),
optionally enriched with the Open Finance monthly report. Each analyzer yields
`Insight` dicts shaped for upsert into the `CfoInsight` table (fingerprint,
insight_type, severity, title, message, evidence, recommended_action).

Insights produced:
  * duplicate_charge        — same amount charged twice on the same day
  * subscription            — recurring monthly charge to the same merchant
  * installment_ending      — תשלומים שמסתיימים בקרוב (frees up budget)
  * bank_fees               — bank/card fees + FX markup that can be trimmed
  * category_spike          — a category jumped vs its recent average
  * cashflow_forecast       — projected end-of-month plus/minus
  * savings_opportunity     — discretionary categories worth cutting
  * anomaly                 — unusually large/odd charge vs personal baseline
  * risk_signal             — NSF / bounced cheques / foreclosure from monthly report

All amounts follow the convention: positive = inflow, negative = outflow.
"""
from __future__ import annotations

import hashlib
import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

# Discretionary expense categories most amenable to cuts.
DISCRETIONARY = {"LEISURE", "SHOPPING", "FOOD_&_DRINKS", "HEALTH_&_BEAUTY"}
SEV_INFO, SEV_LOW, SEV_MED, SEV_HIGH, SEV_CRIT = "info", "low", "medium", "high", "critical"

# Hebrew labels for the Open Finance main categories.
CATEGORY_HE = {
    "HOUSEHOLD_&_SERVICES": "בית ושירותים",
    "HOME_IMPROVEMENTS": "שיפוצים",
    "FOOD_&_DRINKS": "אוכל ומשקאות",
    "TRANSPORT": "תחבורה",
    "SHOPPING": "קניות",
    "LEISURE": "פנאי",
    "HEALTH_&_BEAUTY": "בריאות ויופי",
    "FINANCE": "פיננסים",
    "OTHER": "אחר",
    "SALARY": "משכורת",
}


@dataclass
class Txn:
    """Normalized transaction the analyzers operate on."""
    external_id: str
    date: date
    amount: float            # signed: + inflow, - outflow
    currency: str = "ILS"
    description: str = ""
    category_main: Optional[str] = None
    category_sub: Optional[str] = None
    merchant: Optional[str] = None
    is_duplicate: bool = False
    installment_number: Optional[int] = None
    installment_total: Optional[int] = None
    markup_fee: float = 0.0
    account_id: Optional[str] = None
    raw: dict = field(default_factory=dict)

    @property
    def is_expense(self) -> bool:
        return self.amount < 0

    @property
    def abs_amount(self) -> float:
        return abs(self.amount)

    @property
    def month_key(self) -> tuple[int, int]:
        return (self.date.year, self.date.month)

    @property
    def merchant_key(self) -> str:
        return (self.merchant or self.description or "").strip().lower()


def txn_from_raw(
    *, external_id: str, tx_date: date, amount: float, currency: str,
    description: str, raw: Optional[dict], account_id: Optional[str] = None,
) -> Txn:
    """Build a `Txn` from a BankTransaction row + its Open Finance raw_data."""
    raw = raw or {}
    category = raw.get("category") or {}
    installments = raw.get("installments") or {}
    markup = raw.get("markupFee") or {}
    return Txn(
        external_id=external_id,
        date=tx_date,
        amount=float(amount),
        currency=currency or "ILS",
        description=description or "",
        category_main=(category.get("main") if isinstance(category, dict) else None),
        category_sub=(category.get("sub") if isinstance(category, dict) else None),
        merchant=raw.get("merchantName"),
        is_duplicate=bool(raw.get("isDuplicate")),
        installment_number=_int(installments.get("number")) if isinstance(installments, dict) else None,
        installment_total=_int(installments.get("total")) if isinstance(installments, dict) else None,
        markup_fee=_float(markup.get("amount")) if isinstance(markup, dict) else 0.0,
        account_id=account_id or raw.get("accountId"),
        raw=raw,
    )


# Categories that appear in exactly one of the API's expense/income lists.
# (FINANCE and OTHER appear in BOTH, so they tell us nothing about direction.)
_INCOME_ONLY = {"SALARY", "PENSION", "REIMBURSEMENTS", "BENEFITS"}
_EXPENSE_ONLY = {
    "HOUSEHOLD_&_SERVICES", "HOME_IMPROVEMENTS", "FOOD_&_DRINKS",
    "TRANSPORT", "SHOPPING", "LEISURE", "HEALTH_&_BEAUTY",
}


def validate_sign_convention(txns: Iterable[Txn], *, min_sample: int = 8) -> Optional[dict[str, Any]]:
    """Batch-level sanity check on the +inflow/-outflow convention.

    We do NOT force per-transaction signs from the category — a refund inside an
    expense category is a legitimate inflow and must keep its positive sign. Instead
    we anchor on the API's pre-categorization across the whole batch: if transactions
    in income-only categories skew negative (or expense-only skew positive), the
    provider is almost certainly emitting positive-for-debit and the sign everywhere
    needs to flip. Returns a warning dict when an inversion is detected, else None.

    This is the validator that turns the moment a real bank first connects into a
    definitive answer on the sign convention (see open_finance_connector._transaction_amount).
    """
    txns = list(txns)
    income = [t for t in txns if t.category_main in _INCOME_ONLY and t.amount != 0]
    expense = [t for t in txns if t.category_main in _EXPENSE_ONLY and t.amount != 0]
    sample = len(income) + len(expense)
    if sample < min_sample:
        return None
    # Under the correct convention: income positive, expense negative.
    wrong = sum(1 for t in income if t.amount < 0) + sum(1 for t in expense if t.amount > 0)
    wrong_ratio = wrong / sample
    if wrong_ratio >= 0.8:
        logger.warning(
            "Open Finance sign convention looks INVERTED: %.0f%% of %d categorized "
            "txns contradict +inflow/-outflow. Provider likely emits positive-for-debit; "
            "flip the sign in _transaction_amount.",
            wrong_ratio * 100, sample,
        )
        return {
            "inverted": True,
            "wrong_ratio": round(wrong_ratio, 3),
            "sample": sample,
            "message": (
                f"מוסכמת הסימן מהבנק נראית הפוכה: {round(wrong_ratio*100)}% מ-{sample} "
                "תנועות מסווגות סותרות את הכלל (חיובי=נכנס). יש להפוך את הסימן."
            ),
        }
    return None


# ---------------------------------------------------------------------- #
# Engine
# ---------------------------------------------------------------------- #
def generate_insights(
    transactions: Iterable[Txn],
    *,
    monthly_report: Optional[dict] = None,
    today: Optional[date] = None,
) -> list[dict[str, Any]]:
    txns = sorted(transactions, key=lambda t: t.date)
    today = today or (txns[-1].date if txns else date.today())
    insights: list[dict] = []
    if txns:
        insights += detect_duplicate_charges(txns)
        insights += detect_subscriptions(txns)
        insights += detect_installments_ending(txns)
        insights += detect_bank_fees(txns)
        insights += detect_category_spikes(txns)
        insights += forecast_cashflow(txns, today=today)
        insights += detect_savings_opportunities(txns)
        insights += detect_anomalies(txns)
    if monthly_report:
        insights += detect_risk_signals(monthly_report)
    return insights


# ---------------------------------------------------------------------- #
# Analyzers
# ---------------------------------------------------------------------- #
def detect_duplicate_charges(txns: list[Txn]) -> list[dict]:
    out: list[dict] = []
    groups: dict[tuple, list[Txn]] = defaultdict(list)
    for t in txns:
        if not t.is_expense:
            continue
        key = (t.date, round(t.abs_amount, 2), t.merchant_key or t.account_id)
        groups[key].append(t)
    for (d, amount, who), group in groups.items():
        flagged = len(group) >= 2 or any(t.is_duplicate for t in group)
        if not flagged or len(group) < 2:
            continue
        label = group[0].merchant or group[0].description or "חיוב"
        out.append(_insight(
            insight_type="duplicate_charge",
            severity=SEV_HIGH,
            title=f"חיוב כפול: {label} ×{len(group)}",
            message=(
                f"זוהו {len(group)} חיובים זהים של {_money(amount, group[0].currency)} "
                f"באותו יום ({d.isoformat()}) עבור \"{label}\". ייתכן חיוב כפול בטעות."
            ),
            evidence={
                "date": d.isoformat(), "amount": amount, "count": len(group),
                "merchant": label, "external_ids": [t.external_id for t in group],
            },
            recommended_action="בדוק מול הספק/הבנק וזכה אם מדובר בכפילות.",
            fingerprint_parts=["dup", d.isoformat(), f"{amount:.2f}", who or label],
        ))
    return out


def detect_subscriptions(txns: list[Txn], *, min_months: int = 3, tolerance: float = 0.12) -> list[dict]:
    """Recurring same-merchant monthly charges = subscriptions / standing orders."""
    out: list[dict] = []
    by_merchant: dict[str, list[Txn]] = defaultdict(list)
    for t in txns:
        if t.is_expense and t.merchant_key:
            by_merchant[t.merchant_key].append(t)

    for merchant_key, group in by_merchant.items():
        months = {t.month_key for t in group}
        if len(months) < min_months:
            continue
        amounts = [t.abs_amount for t in group]
        median = statistics.median(amounts)
        if median <= 0:
            continue
        # Consistent monthly amount → recurring subscription.
        consistent = [a for a in amounts if abs(a - median) <= median * tolerance]
        if len(consistent) < min_months:
            continue
        label = group[0].merchant or group[0].description
        monthly = round(median, 2)
        annual = round(monthly * 12, 2)
        out.append(_insight(
            insight_type="subscription",
            severity=SEV_MED,
            title=f"מנוי חודשי: {label} — {_money(monthly, group[0].currency)}/חודש",
            message=(
                f"חיוב חוזר של כ-{_money(monthly, group[0].currency)} בחודש ל\"{label}\" "
                f"({len(months)} חודשים). עלות שנתית מוערכת: {_money(annual, group[0].currency)}. "
                f"אם אינך משתמש — שקול ביטול."
            ),
            evidence={
                "merchant": label, "monthly": monthly, "annual_estimate": annual,
                "months": len(months), "currency": group[0].currency,
                "external_ids": [t.external_id for t in group[:24]],
            },
            recommended_action="ודא שאתה עדיין משתמש במנוי; אם לא — בטל וחסוך.",
            fingerprint_parts=["sub", merchant_key],
        ))
    return out


def detect_installments_ending(txns: list[Txn], *, within: int = 2) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for t in txns:
        n, total = t.installment_number, t.installment_total
        if not n or not total or total < 2:
            continue
        if total - n > within:
            continue
        label = t.merchant or t.description or "תשלום"
        key = f"{t.merchant_key}|{total}"
        if key in seen:
            continue
        seen.add(key)
        remaining = max(total - n, 0)
        out.append(_insight(
            insight_type="installment_ending",
            severity=SEV_INFO,
            title=f"תשלומים מסתיימים: {label} ({n}/{total})",
            message=(
                f"פריסת התשלומים ל\"{label}\" כמעט הסתיימה ({n} מתוך {total}, "
                f"נותרו {remaining}). בקרוב יתפנה תקציב של {_money(t.abs_amount, t.currency)}/חודש."
            ),
            evidence={"merchant": label, "number": n, "total": total,
                      "monthly": round(t.abs_amount, 2), "external_id": t.external_id},
            recommended_action="תכנן מראש לאן לכוון את הסכום שמתפנה.",
            fingerprint_parts=["inst", t.merchant_key, str(total)],
        ))
    return out


def detect_bank_fees(txns: list[Txn]) -> list[dict]:
    fee_txns = [t for t in txns if t.is_expense and (t.category_main == "FINANCE" or t.markup_fee)]
    if not fee_txns:
        return []
    currency = fee_txns[0].currency
    total_fees = round(sum(t.abs_amount for t in fee_txns if t.category_main == "FINANCE"), 2)
    total_markup = round(sum(t.markup_fee for t in fee_txns), 2)
    grand = round(total_fees + total_markup, 2)
    if grand <= 0:
        return []
    return [_insight(
        insight_type="bank_fees",
        severity=SEV_MED,
        title=f"עמלות בנק/מט\"ח: {_money(grand, currency)}",
        message=(
            f"שולמו כ-{_money(total_fees, currency)} עמלות (קטגוריית FINANCE) "
            f"ו-{_money(total_markup, currency)} עמלות המרת מט\"ח. רבות מהן ניתנות לקיצוץ "
            f"במשא ומתן מול הבנק או במעבר לכרטיס ללא עמלת מט\"ח."
        ),
        evidence={"fees": total_fees, "fx_markup": total_markup, "total": grand,
                  "currency": currency, "count": len(fee_txns)},
        recommended_action="פנה לבנק להפחתת עמלות / עבור לכרטיס פטור מעמלת מט\"ח.",
        fingerprint_parts=["fees", currency],
    )]


def detect_category_spikes(txns: list[Txn], *, min_months: int = 3, factor: float = 1.4) -> list[dict]:
    out: list[dict] = []
    # per category -> per month total expense
    cat_month: dict[str, dict[tuple, float]] = defaultdict(lambda: defaultdict(float))
    for t in txns:
        if t.is_expense and t.category_main:
            cat_month[t.category_main][t.month_key] += t.abs_amount
    for cat, months in cat_month.items():
        if len(months) < min_months:
            continue
        ordered = sorted(months.items())
        *prior, (latest_key, latest_val) = ordered
        baseline = statistics.mean([v for _, v in prior])
        if baseline <= 0 or latest_val < baseline * factor:
            continue
        pct = round((latest_val / baseline - 1) * 100)
        cat_he = CATEGORY_HE.get(cat, cat)
        out.append(_insight(
            insight_type="category_spike",
            severity=SEV_MED,
            title=f"קפיצה בהוצאות {cat_he}: +{pct}%",
            message=(
                f"החודש הוצאת {_money(round(latest_val, 2), 'ILS')} על {cat_he}, "
                f"כ-{pct}% מעל הממוצע שלך ({_money(round(baseline, 2), 'ILS')})."
            ),
            evidence={"category": cat, "latest": round(latest_val, 2),
                      "baseline": round(baseline, 2), "pct": pct,
                      "month": f"{latest_key[0]}-{latest_key[1]:02d}"},
            recommended_action="בדוק מה הניע את העלייה והאם היא חד-פעמית.",
            fingerprint_parts=["spike", cat, f"{latest_key[0]}-{latest_key[1]:02d}"],
        ))
    return out


def forecast_cashflow(txns: list[Txn], *, today: date) -> list[dict]:
    cur = (today.year, today.month)
    month_txns = [t for t in txns if t.month_key == cur]
    if not month_txns:
        return []
    income = sum(t.amount for t in month_txns if t.amount > 0)
    expense = sum(-t.amount for t in month_txns if t.amount < 0)
    net_so_far = income - expense
    day = today.day
    days_in_month = _days_in_month(today.year, today.month)
    # Pro-rate expenses (income is lumpier; project conservatively on expenses only).
    projected_expense = expense / day * days_in_month if day else expense
    projected_net = round(income - projected_expense, 2)
    sev = SEV_HIGH if projected_net < 0 else SEV_INFO
    sign = "מינוס" if projected_net < 0 else "פלוס"
    return [_insight(
        insight_type="cashflow_forecast",
        severity=sev,
        title=f"תחזית סוף חודש: {sign} {_money(abs(projected_net), 'ILS')}",
        message=(
            f"עד היום ({day}/{days_in_month}) נכנסו {_money(round(income, 2), 'ILS')} "
            f"ויצאו {_money(round(expense, 2), 'ILS')}. בקצב הנוכחי הצפי לסוף החודש הוא "
            f"{sign} של כ-{_money(abs(projected_net), 'ILS')}."
        ),
        evidence={"income": round(income, 2), "expense": round(expense, 2),
                  "net_so_far": round(net_so_far, 2), "projected_net": projected_net,
                  "day": day, "days_in_month": days_in_month},
        recommended_action=("צמצם הוצאות לא הכרחיות עד סוף החודש." if projected_net < 0
                            else "יש עודף צפוי — שקול להעביר אותו לחיסכון שעובד בשבילך."),
        fingerprint_parts=["forecast", f"{cur[0]}-{cur[1]:02d}"],
    )]


def detect_savings_opportunities(txns: list[Txn], *, top: int = 1) -> list[dict]:
    cat_totals: dict[str, float] = defaultdict(float)
    for t in txns:
        if t.is_expense and t.category_main in DISCRETIONARY:
            cat_totals[t.category_main] += t.abs_amount
    if not cat_totals:
        return []
    out: list[dict] = []
    for cat, total in sorted(cat_totals.items(), key=lambda kv: kv[1], reverse=True)[:top]:
        cat_he = CATEGORY_HE.get(cat, cat)
        potential = round(total * 0.15, 2)  # a modest 15% trim
        out.append(_insight(
            insight_type="savings_opportunity",
            severity=SEV_INFO,
            title=f"הזדמנות חיסכון: {cat_he}",
            message=(
                f"קטגוריית {cat_he} היא מההוצאות הגדולות שניתן לגמישות בהן "
                f"({_money(round(total, 2), 'ILS')}). קיצוץ של 15% יחסוך "
                f"כ-{_money(potential, 'ILS')}."
            ),
            evidence={"category": cat, "total": round(total, 2), "potential_saving": potential},
            recommended_action="הגדר תקרה חודשית לקטגוריה הזו.",
            fingerprint_parts=["savings", cat],
        ))
    return out


def detect_anomalies(txns: list[Txn], *, z: float = 3.0, min_n: int = 8) -> list[dict]:
    expenses = [t for t in txns if t.is_expense]
    if len(expenses) < min_n:
        return []
    amounts = [t.abs_amount for t in expenses]
    mean = statistics.mean(amounts)
    stdev = statistics.pstdev(amounts)
    if stdev <= 0:
        return []
    out: list[dict] = []
    threshold = mean + z * stdev
    for t in expenses:
        if t.abs_amount >= threshold:
            label = t.merchant or t.description or "חיוב"
            out.append(_insight(
                insight_type="anomaly",
                severity=SEV_MED,
                title=f"חיוב חריג: {label} {_money(t.abs_amount, t.currency)}",
                message=(
                    f"חיוב של {_money(t.abs_amount, t.currency)} ל\"{label}\" "
                    f"({t.date.isoformat()}) חריג משמעותית מהממוצע שלך "
                    f"({_money(round(mean, 2), t.currency)}). ודא שאתה מזהה אותו."
                ),
                evidence={"amount": round(t.abs_amount, 2), "mean": round(mean, 2),
                          "threshold": round(threshold, 2), "merchant": label,
                          "date": t.date.isoformat(), "external_id": t.external_id},
                recommended_action="אם אינך מזהה את החיוב — בדוק מול הבנק/חברת האשראי.",
                fingerprint_parts=["anom", t.external_id],
            ))
    return out


def detect_risk_signals(monthly_report: dict) -> list[dict]:
    balances = (monthly_report or {}).get("openBankingReportBalances") or {}
    checks = {
        "nsf": ("חריגה ללא כיסוי (NSF)", SEV_HIGH),
        "canceledChecks": ("צ'קים שחזרו", SEV_HIGH),
        "accountForeclosure": ("עיקול חשבון", SEV_CRIT),
        "limitationAlert": ("התראת הגבלת חשבון", SEV_CRIT),
        "fallingBehindWarnings": ("התראות פיגור", SEV_HIGH),
        "standingOrdersReturns": ("הוראות קבע שחזרו", SEV_MED),
    }
    out: list[dict] = []
    for field_name, (label, sev) in checks.items():
        value = balances.get(field_name)
        try:
            count = int(value or 0)
        except (TypeError, ValueError):
            count = 0
        if count > 0:
            out.append(_insight(
                insight_type="risk_signal",
                severity=sev,
                title=f"סיכון: {label} ({count})",
                message=f"הדוח החודשי מציין {count} מקרים של {label}. כדאי לטפל בהקדם.",
                evidence={"field": field_name, "count": count},
                recommended_action="בדוק מול הבנק והסדר את החשבון למניעת עמלות/הגבלות.",
                fingerprint_parts=["risk", field_name],
            ))
    return out


# ---------------------------------------------------------------------- #
# helpers
# ---------------------------------------------------------------------- #
def _insight(*, insight_type, severity, title, message, evidence,
             recommended_action, fingerprint_parts) -> dict:
    fp = hashlib.sha256("|".join(str(p) for p in fingerprint_parts).encode()).hexdigest()[:32]
    return {
        "insight_type": insight_type,
        "severity": severity,
        "title": title,
        "message": message,
        "evidence": evidence,
        "recommended_action": recommended_action,
        "fingerprint": f"{insight_type}:{fp}",
    }


def _money(amount: float, currency: str = "ILS") -> str:
    symbol = {"ILS": "₪", "USD": "$", "EUR": "€", "GBP": "£"}.get(currency, currency + " ")
    return f"{symbol}{amount:,.0f}" if float(amount).is_integer() else f"{symbol}{amount:,.2f}"


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    import datetime as _dt
    return (_dt.date(year, month + 1, 1) - _dt.date(year, month, 1)).days


def _int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
