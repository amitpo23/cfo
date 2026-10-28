"""Liquidity, obligations and loans for one organization of a dashboard.

A port of the Eliav tool's "נזילות והתחייבויות" tab (``lib/liquidity-model.js``
and ``lib/liquidity-read.js``). Inputs are rows already in the database:

* ``accounts``: balance, credit limit and provider type of each bank account.
  When the dashboard binds accounts to the entity (``dashboard_entity_accounts``)
  only those are read; otherwise every Open Finance account of the organization.
* BOOKED bank rows of the checking accounts: the provider's end-of-day balance
  (``raw_data.balancePerEndDay``) gives the monthly low and the days below zero
  or beyond the limit.
* Filed bank rows (``books.classified_bank``): principal, interest and new loans
  per month (debt service).
* ``plan.liquidityEvidence``: dated evidence the feed does not carry (credit
  facilities, loans of an entity without a live connection, post-dated checks,
  loan maturities) and dated opening balances of checking accounts whose
  import has no balance column. Each item may name an ``organizationId``.

Unknown is ``None``, never 0. A loan account whose name says it is the credit
line ("מסגרת") mirrors the overdraft and is not added to the debts again.
No provider calls.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, timedelta

from sqlalchemy import func

from ...models import Account, BankTransaction, DashboardEntityAccount

# Operating cash only. SAVINGS is not the current account: a blocked savings
# row with no balance date must not hide a known Hapoalim checking balance.
OPERATING_CASH = {"CHECKING", "CURRENT", "CACC", "CURRENT_ACCOUNT"}
CHECKING_TYPES = OPERATING_CASH | {"SAVINGS"}
CARD = "CARD"
LOAN = "LOAN"
CREDIT_LINE_TEXT = "מסגרת"
CHECK_TEXT = re.compile(r"שיק|צ'ק|צ׳ק|צ\"ק")
CHECK_HORIZON_DAYS = 120
EVENT_HORIZON_DAYS = 400
EVIDENCE_KINDS = ("facilities", "loans", "checks", "events", "openingBalances")


def _r(value: float) -> float:
    return round(value + 0.0, 2)


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sum_or_none(values) -> float | None:
    known = [v for v in values if v is not None]
    return _r(sum(known)) if known else None


# Cheque discounting is an advance on customer receipts, not a loan.
_DISCOUNTING_NAME = re.compile(r"ניכיון|צ['׳\"״]?קים\s*דחויים|שיקים\s*דחויים")
_DISCOUNTING_KINDS = frozenset({"check_discounting", "cheque_discounting"})
ADVANCE_LABEL = "ניכיון שיקים — מקדמה על תקבולי לקוחות"
ADVANCE_NOTE = "מקדמה על תקבולי לקוחות, לא הלוואה ולא תשלום. אינו נכלל בחוב."
BALANCE_VS_FLOW_NOTE = (
    "שפל וסוף חודש הם יתרות סוף יום: הנמוכה בחודש, והאחרונה שנצפתה. "
    "הנטו החודשי בתזרים הוא סכום התנועות. אלה מדדים שונים, והם לא אמורים להיות שווים. "
    "השינוי ביתרה שווה לסכום התנועות רק כשיתרת הפתיחה ויתרת הסגירה ידועות. "
    "השפל אינו יתרת הפתיחה."
)
MIN_DEFINITION = "יתרת סוף היום הנמוכה בחודש. זו יתרה, לא תזרים."
LAST_DEFINITION = "יתרת סוף היום האחרון בחודש שיש לו יתרת ספק. זו יתרה, לא הנטו החודשי."
CARD_ACTIVITY_DEFINITION = (
    "סכום מסומן של תנועות BOOKED בחשבונות הכרטיס בחלון (חיוב שלילי, זיכוי חיובי) ומספרן. "
    "זה אינו יתרת החיוב, אינו המסגרת הפנויה, ואינו נכלל בסה״כ ההתחייבויות."
)
_IDENTITY_DIGITS = 6


def is_check_discounting(name, kind=None) -> bool:
    if str(kind or "").strip().casefold() in _DISCOUNTING_KINDS:
        return True
    return bool(_DISCOUNTING_NAME.search(str(name or "")))


def bank_key(account) -> str | None:
    """Public stand-in for ``account_identity``. Same account, same key; not the account number."""
    ident = account_identity(account)
    if ident is None:
        return None
    return hashlib.sha256(ident.encode()).hexdigest()[:16]


def account_identity(account) -> str | None:
    """Stable bank identity across organizations. Unknown (too short, or absent) is None.

    Fewer than six digits is not collapsed with another account: a short tail
    collides, and a missing number is not a zero and not a match.
    """
    digits = re.sub(r"\D", "", str(getattr(account, "provider_account_number", None) or ""))
    if len(digits) < _IDENTITY_DIGITS:
        return None
    return f"{_account_kind(account)}:{digits}"


# Evidence and a live loan are one loan when their names match and the balances are
# within this share of the evidence balance (interest accrues between the two dates).
LOAN_MATCH_TOLERANCE = 0.05


def _name_key(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def merge_loan_evidence(live: list[dict], evidence: list[dict]) -> list[dict]:
    """The bank's loans win over the plan's loan evidence.

    Without a live loan the evidence stands (an entity with no connection). With
    live loans, evidence adds only the maturity the feed does not carry, matched
    by name and the nearest balance across all pairs (so a repaid loan cannot take
    a live loan from its real twin). Unmatched evidence whose name the bank still
    reports for other loans is gone from that feed, so it is no longer a debt
    (production 27/10/2026: a repaid bridge loan was still counted). Unmatched
    evidence with a name the feed never reports stays: it may be a loan at a bank
    that is not connected."""
    rows = [_evidence_loan(item) for item in evidence]
    if not live:
        return rows
    pairs = sorted(
        (abs(live[j]["balance"] - row["balance"]), i, j)
        for i, row in enumerate(rows) for j in range(len(live))
        if row["balance"] and live[j]["balance"] is not None
        and _name_key(row["name"]) == _name_key(live[j]["name"])
        and abs(live[j]["balance"] - row["balance"]) <= LOAN_MATCH_TOLERANCE * row["balance"]
    )
    merged = [dict(loan) for loan in live]
    used_rows, used_live = set(), set()
    for _gap, i, j in pairs:
        if i in used_rows or j in used_live:
            continue
        used_rows.add(i)
        used_live.add(j)
        if rows[i].get("maturity"):
            merged[j]["maturity"] = rows[i]["maturity"]
        for key in ("kind", "payment_amount", "payment_date", "approximate", "owner_note"):
            if rows[i].get(key) not in (None, False, ""):
                merged[j][key] = rows[i][key]
        merged[j]["payment_source"] = "plan.liquidityEvidence"
    live_names = {_name_key(loan["name"]) for loan in live}
    merged += [
        row for i, row in enumerate(rows)
        if i not in used_rows and _name_key(row["name"]) not in live_names
    ]
    return merged


OWNER_EVIDENCE_SOURCE = "plan.liquidityEvidence"
UNKNOWN_OWNER_AMOUNT = "לא ידוע, הבעלים יזין"
CARD_AVAILABLE_DERIVED = "credit_limit_minus_unbilled"
CARD_AVAILABLE_STORED = "accounts.available_limit"


def _evidence_loan(item: dict) -> dict:
    return {
        "name": item.get("label"),
        "balance": _num(item.get("balance")),
        "as_of": item.get("asOf"),
        "maturity": item.get("maturity"),
        "source": item.get("source") or OWNER_EVIDENCE_SOURCE,
        "owner_entered": True,
        "provider_data": False,
        "kind": item.get("kind"),
        "payment_amount": _num(item.get("paymentAmount")),
        "payment_date": item.get("paymentDate"),
        "approximate": bool(item.get("approximate")),
        "owner_note": item.get("note"),
    }


def annotate_loan(loan: dict) -> dict:
    """Source and uncertainty on a loan row. Owner evidence is never labelled as the bank."""
    row = dict(loan)
    row["owner_entered"] = bool(row.get("owner_entered") or row.get("source") not in ("accounts", None))
    row["provider_data"] = not row["owner_entered"]
    if row["owner_entered"] and row.get("source") in ("accounts", "evidence", None):
        row["source"] = OWNER_EVIDENCE_SOURCE
    notes = []
    if row.get("approximate"):
        notes.append("יתרה שהבעלים מסר בקירוב, לא יתרת בנק")
    elif row["owner_entered"]:
        notes.append("ראיית בעלים. לא נתון שהבנק מסר.")
    if row.get("payment_source") == OWNER_EVIDENCE_SOURCE and not row["owner_entered"]:
        notes.append("ההחזר מתועד בראיית הבעלים; היתרה היא מהחשבון השמור")
    if row.get("owner_note"):
        notes.append(str(row["owner_note"]))
    row["uncertainty"] = " ".join(notes) or None
    return row


def _balance(account: Account) -> float | None:
    """A balance counts only with its date. A local import leaves 0 without a date: unknown."""
    if account.balance_as_of is None:
        return None
    return _num(account.balance)


# Column names of a statement's running balance in a reviewed local import
# (``raw_data.original``), compared without spaces, quotes or case.
_IMPORTED_BALANCE_KEYS = {
    "balance", "runningbalance", "balanceafter", "יתרה", "יתרהבשח", "יתרהבשקלים",
    "יתרהלאחרפעולה", "יתרהאחריהפעולה", "יתרהבחשבון",
}
_KEY_NOISE = re.compile(r"[\s\"'\u05f3\u05f4_\-.]")


def _statement_number(value) -> float | None:
    """A statement cell as a number: "1,234.50", "-1,234.50", "1,234.50-", "₪ 12"."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.replace(",", "").replace("₪", "").replace("\u200f", "").replace("\u200e", "").strip()
    negative = text.endswith("-") or (text.startswith("(") and text.endswith(")"))
    text = text.strip("-()").strip() if negative else text
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def _row_balance(row) -> float | None:
    raw = row.raw_data if isinstance(row.raw_data, dict) else {}
    original = raw.get("original")
    if not isinstance(original, dict):
        return None
    for key, value in original.items():
        if _KEY_NOISE.sub("", str(key)).casefold() in _IMPORTED_BALANCE_KEYS:
            return _statement_number(value)
    return None


def imported_balance(db, account: Account) -> dict | None:
    """Closing balance of an imported statement: the running balance of its last day.

    A local import has no balance on the account. When the statement rows carry
    their running balance, the last day's closing is the row no other row of that
    day follows (its balance is not another row's balance before the movement).
    Two candidates, or none, leave the balance unknown.
    """
    rows = (
        db.query(BankTransaction)
        .filter(BankTransaction.account_id == account.id, BankTransaction.superseded_by_id.is_(None))
        .order_by(BankTransaction.transaction_date.desc(), BankTransaction.id.desc())
        .limit(200)
        .all()
    )
    dated = [(row, _row_balance(row)) for row in rows]
    dated = [(row, value) for row, value in dated if value is not None]
    if not dated:
        return None
    last_day = dated[0][0].transaction_date
    same_day = [(row, value) for row, value in dated if row.transaction_date == last_day]
    before = {_r(value - float(row.amount or 0)) for row, value in same_day}
    closing = {_r(value) for _row, value in same_day if _r(value) not in before or len(same_day) == 1}
    if len(closing) != 1:
        return None
    return {"balance": closing.pop(), "as_of": last_day, "source": "imported_running_balance"}


def opening_balance(db, account: Account, items: list[dict], end: date, *, sole: bool) -> dict | None:
    """An owner-entered closing balance of one day plus the BOOKED rows after it.

    The item names the account (``accountId``) or only the organization; an
    organization-only item counts when this is the organization's only checking
    account without a known balance (``sole``). The latest item dated on or
    before ``end`` is used. Rows dated after ``end`` are not counted.
    """
    matching = [
        item for item in items
        if (item.get("accountId") == account.id
            or (item.get("accountId") is None and sole
                and item.get("organizationId") == account.organization_id))
        and _num(item.get("amount")) is not None and item.get("date")
        and date.fromisoformat(item["date"]) <= end
    ]
    if not matching:
        return None
    chosen = max(matching, key=lambda item: (item["date"], item.get("accountId") is not None))
    opened_on = date.fromisoformat(chosen["date"])
    rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.account_id == account.id,
            BankTransaction.superseded_by_id.is_(None),
            BankTransaction.transaction_date > opened_on,
            BankTransaction.transaction_date <= end,
        )
        .all()
    )
    booked = [row for row in rows if str((row.raw_data or {}).get("status") or "BOOKED").upper() != "PENDING"]
    moved = sum(float(row.amount or 0) for row in booked)
    return {
        "balance": _r(float(chosen["amount"]) + moved),
        "as_of": max((row.transaction_date for row in booked), default=opened_on),
        "source": "opening_balance",
        "opening": {"date": chosen["date"], "amount": _r(float(chosen["amount"])),
                    "source": chosen.get("source"), "transactions": len(booked)},
    }


def _account_kind(account: Account) -> str:
    raw = str(account.raw_account_type or "").strip().upper()
    if raw == CARD:
        return "card"
    if raw == LOAN:
        return "credit_line_mirror" if CREDIT_LINE_TEXT in (account.name or "") else "loan"
    if raw in OPERATING_CASH:
        return "checking"
    if raw == "SAVINGS":
        return "savings"
    # An Open Finance bank account with no type is a current account. Cards and
    # loans carry their own raw type and never get here as BANK.
    account_type = getattr(account, "account_type", None)
    type_name = getattr(account_type, "value", account_type)
    if not raw and getattr(account, "source", None) == "open_finance" and str(type_name) == "bank":
        return "checking"
    return "other"


def entity_accounts(db, organization_id: int, entity_id: int | None) -> list[Account]:
    """Accounts this entity's liquidity reads.

    No binding: every Open Finance account of the organization. A binding still
    limits manual accounts. An Open Finance current account with a dated balance
    is included when the binding has none, so a Hapoalim account synced onto the
    organization is not hidden by an older card-only binding.
    """
    bound: list[int] = []
    if entity_id:
        bound = [row.account_id for row in db.query(DashboardEntityAccount).filter_by(entity_id=entity_id).all()]
    rows = (
        db.query(Account)
        .filter(Account.organization_id == organization_id)
        .order_by(Account.id)
        .all()
    )
    if not bound:
        return [account for account in rows if account.source == "open_finance"]
    chosen = [account for account in rows if account.id in set(bound)]
    chosen_ids = {account.id for account in chosen}
    has_operating = any(
        account.source == "open_finance" and _account_kind(account) == "checking" and _balance(account) is not None
        for account in chosen
    )
    if not has_operating:
        for account in rows:
            if account.id in chosen_ids:
                continue
            if account.source == "open_finance" and _account_kind(account) == "checking" and _balance(account) is not None:
                chosen.append(account)
    return sorted(chosen, key=lambda account: account.id or 0)


def evidence_for(plan: dict | None, organization_id: int | None) -> dict:
    """Items of ``plan.liquidityEvidence`` for one organization (None: all)."""
    raw = (plan or {}).get("liquidityEvidence") if isinstance(plan, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for kind in EVIDENCE_KINDS:
        items = raw.get(kind) if isinstance(raw.get(kind), list) else []
        out[kind] = [
            item for item in items
            if isinstance(item, dict) and (
                organization_id is None or item.get("organizationId") in (None, organization_id)
            )
        ]
    out["observedAt"] = raw.get("observedAt")
    return out


def _daily_balances(db, account_ids: list[int], start: date, end: date) -> tuple[list[dict], int]:
    if not account_ids:
        return [], 0
    rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.account_id.in_(account_ids),
            BankTransaction.transaction_date >= start,
            BankTransaction.transaction_date <= end,
            BankTransaction.superseded_by_id.is_(None),
        )
        .all()
    )
    by_day: dict[tuple[int, str], set[float]] = {}
    for row in rows:
        raw = row.raw_data if isinstance(row.raw_data, dict) else {}
        if str(raw.get("status") or "").upper() != "BOOKED":
            continue
        value = _num(raw.get("balancePerEndDay"))
        if value is None:
            continue
        by_day.setdefault((row.account_id, row.transaction_date.isoformat()), set()).add(_r(value))
    days = []
    conflicts = 0
    for (account_id, day), values in sorted(by_day.items(), key=lambda item: (item[0][1], item[0][0])):
        if len(values) != 1:
            conflicts += 1  # the provider sent two closings for one day; neither is used
            continue
        days.append({"account_id": account_id, "date": day, "balance": values.pop()})
    return days, conflicts


def _months(days: list[dict], limit: float | None) -> list[dict]:
    """Daily low and last close of the combined checking position.

    Each ``days`` row is one account on one date. A date counts only once every
    account that has any end-of-day balance in the month already has one (carried
    forward from its previous day in the month). A partial sum of the accounts
    that happened to move that day is not the company's balance.
    """
    by_month: dict[str, dict[int, list[tuple[str, float]]]] = {}
    for day in days:
        by_month.setdefault(day["date"][:7], {}).setdefault(day["account_id"], []).append(
            (day["date"], day["balance"])
        )
    out = []
    for month in sorted(by_month):
        series = {aid: sorted(points) for aid, points in by_month[month].items()}
        dates = sorted({day for points in series.values() for day, _balance in points})
        carried = {aid: None for aid in series}
        index = {aid: 0 for aid in series}
        combined: list[tuple[str, float]] = []
        for day in dates:
            ready = True
            for aid, points in series.items():
                while index[aid] < len(points) and points[index[aid]][0] <= day:
                    carried[aid] = points[index[aid]][1]
                    index[aid] += 1
                if carried[aid] is None:
                    ready = False
            if not ready:
                continue
            combined.append((day, _r(sum(carried.values()))))
        if not combined:
            continue
        balances = [balance for _day, balance in combined]
        min_balance = min(balances)
        last_day, last_balance = combined[-1]
        out.append({
            "month": month,
            "days": len(combined),
            "min": min_balance,
            "min_date": next(day for day, balance in combined if balance == min_balance),
            "min_definition": MIN_DEFINITION,
            "negative_days": sum(1 for balance in balances if balance < 0),
            "beyond_limit_days": None if limit is None else sum(1 for balance in balances if balance < -limit),
            "last": last_balance,
            "last_date": last_day,
            "last_definition": LAST_DEFINITION,
        })
    return out


def _reconcile_months(db, account_ids: list[int], start: date, end: date) -> dict[str, dict]:
    """opening + booked net − closing, per month, across checking accounts that report a balance.

    An account with no end-of-day balance in the whole read is left out (the daily
    table does not include it either). A month is unknown when any included
    account lacks an opening before the month or a close inside it. The diff is
    never filled with zero.
    """
    if not account_ids:
        return {}
    rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.account_id.in_(account_ids),
            BankTransaction.transaction_date <= end,
            BankTransaction.superseded_by_id.is_(None),
        )
        .all()
    )
    per: dict[int, dict] = {aid: {"eod": {}, "net": {}} for aid in account_ids}
    for row in rows:
        raw = row.raw_data if isinstance(row.raw_data, dict) else {}
        if str(raw.get("status") or "").upper() != "BOOKED" or row.account_id not in per:
            continue
        if start <= row.transaction_date <= end:
            month = row.transaction_date.strftime("%Y-%m")
            per[row.account_id]["net"][month] = per[row.account_id]["net"].get(month, 0.0) + float(row.amount or 0)
        value = _num(raw.get("balancePerEndDay"))
        if value is None:
            continue
        per[row.account_id]["eod"].setdefault(row.transaction_date, set()).add(_r(value))
    active = []
    for aid in account_ids:
        clean = {}
        for day, values in per[aid]["eod"].items():
            if len(values) == 1:
                clean[day] = next(iter(values))
        per[aid]["eod"] = clean
        if clean:
            active.append(aid)
    result = {}
    for key in _month_keys(start, end):
        year, month = (int(key[:4]), int(key[5:]))
        first = date(year, month, 1)
        nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        last = min(nxt - timedelta(days=1), end)
        openings, closings, nets = [], [], []
        open_ok = close_ok = bool(active)
        for aid in active:
            eod = per[aid]["eod"]
            before = [day for day in eod if day < first]
            inside = [day for day in eod if first <= day <= last]
            nets.append(per[aid]["net"].get(key, 0.0))
            if before:
                openings.append(eod[max(before)])
            else:
                open_ok = False
            if inside:
                closings.append(eod[max(inside)])
            else:
                close_ok = False
        booked_net = _r(sum(nets)) if active else None
        opening = _r(sum(openings)) if open_ok else None
        closing = _r(sum(closings)) if close_ok else None
        diff = None if opening is None or closing is None or booked_net is None else _r(opening + booked_net - closing)
        if diff is None:
            note = "אין יתרת פתיחה וסגירה לכל חשבונות העו״ש עם יתרת סוף יום, ולכן אי אפשר לבדוק אם סכום התנועות שווה לשינוי ביתרה."
        elif abs(diff) < 0.05:
            note = "סכום התנועות שווה לשינוי ביתרה (יתרת פתיחה + נטו = יתרת סגירה)."
        else:
            note = f"פער של {diff:.2f} ₪ בין השינוי ביתרה לבין סכום התנועות. השפל אינו יתרת הפתיחה."
        result[key] = {
            "opening": opening,
            "booked_net": booked_net,
            "closing_balance": closing,
            "reconciliation_diff": diff,
            "reconciliation_note": note,
        }
    return result


def match_checks(checks: list[dict], bank_rows: list, *, last_covered: date | None, today: date) -> list[dict]:
    """Port of ``matchChecks``: each bank row clears one check, earliest first."""
    used: set[int] = set()
    out = []
    for check in sorted(checks, key=lambda item: str(item.get("date") or "")):
        when = date.fromisoformat(check["date"])
        amount = float(check["amount"])
        hits = sorted(
            (
                row for row in bank_rows
                if row.id not in used and float(row.amount) < 0
                and abs(float(row.amount) + amount) < 1
                and CHECK_TEXT.search(row.description or "")
                and when - timedelta(days=5) <= row.transaction_date <= when + timedelta(days=20)
            ),
            key=lambda row: (row.transaction_date, row.id),
        )
        item = {
            "check": check.get("check"), "date": check["date"], "amount": amount,
            "payee": check.get("payee"), "note": check.get("note"),
        }
        if hits:
            used.add(hits[0].id)
            item.update(state="cleared", cleared_on=hits[0].transaction_date.isoformat())
        elif when > today:
            item["state"] = "future"
        elif last_covered is None or when > last_covered:
            item["state"] = "no_coverage"
        else:
            item["state"] = "not_found"
        out.append(item)
    return out


def _debt_service(classified, months: list[str]) -> list[dict]:
    sums: dict[str, dict[str, float]] = {month: {} for month in months}
    for txn, filed in classified:
        month = txn.date[:7]
        if month in sums and filed.category in ("loans_out", "interest", "loans_in"):
            sums[month][filed.category] = sums[month].get(filed.category, 0.0) + txn.amount
    out = []
    for month in months:
        slot = sums[month]
        out.append({
            "month": month,
            "principal": _r(abs(slot.get("loans_out", 0.0))),
            "interest": _r(abs(slot.get("interest", 0.0))),
            "new_loans": _r(slot.get("loans_in", 0.0)),
        })
    return out


def build_liquidity(db, organization_id: int, start: date, end: date, *, plan: dict | None = None,
                    entity_id: int | None = None, classified=None, today: date | None = None) -> dict:
    today = today or end
    accounts = entity_accounts(db, organization_id, entity_id)
    by_kind: dict[str, list[Account]] = {}
    for account in accounts:
        by_kind.setdefault(_account_kind(account), []).append(account)
    evidence = evidence_for(plan, organization_id)

    checking = by_kind.get("checking", [])
    known = {}
    for account in checking:
        if _balance(account) is not None:
            known[account.id] = {"balance": _balance(account), "as_of": account.balance_as_of.date(),
                                 "source": "accounts"}
        elif account.source != "open_finance":
            derived = imported_balance(db, account)
            if derived is not None:
                known[account.id] = derived
    unknown = [account for account in checking if account.id not in known]
    for account in unknown:
        derived = opening_balance(db, account, evidence["openingBalances"], end, sole=len(unknown) == 1)
        if derived is not None:
            known[account.id] = derived
    balance = None if not checking or len(known) != len(checking) else _r(sum(k["balance"] for k in known.values()))
    as_of = max((k["as_of"] for k in known.values()), default=None)
    sources = {k["source"] for k in known.values()}
    balance_source = None if balance is None else (sources.pop() if len(sources) == 1 else "mixed")
    limits = [_num(account.credit_limit) for account in checking]
    limit = None if not checking or any(value is None for value in limits) else _r(sum(limits))
    limit_source = "accounts.credit_limit" if limit is not None else None
    facility = next((item for item in evidence["facilities"] if _num(item.get("limit")) is not None), None)
    if limit is None and facility is not None:
        limit = _r(float(facility["limit"]))
        limit_source = "plan.liquidityEvidence"

    days, conflicts = _daily_balances(db, [a.id for a in checking], start, end)
    month_keys = list(_month_keys(start, end))

    # מסגרת ופנוי כפי שהבנק מסר (creditLimit, interimAvailable). לא ידוע נשאר
    # None — לא נגזר "פנוי" ממסגרת פחות יתרה.
    card_accounts = by_kind.get("card", [])
    cards = present_cards(db, card_accounts)
    live_loans = [
        {"name": a.name, "bank_key": bank_key(a),
         "balance": None if _balance(a) is None else _r(abs(_balance(a))),
         "as_of": a.balance_as_of.date().isoformat() if a.balance_as_of else None, "source": "accounts"}
        for a in by_kind.get("loan", [])
    ]
    discount_live = [row for row in live_loans if is_check_discounting(row.get("name"))]
    real_live = [row for row in live_loans if not is_check_discounting(row.get("name"))]
    discount_evidence = [
        item for item in evidence["loans"] if is_check_discounting(item.get("label"), item.get("kind"))
    ]
    real_evidence = [
        item for item in evidence["loans"] if not is_check_discounting(item.get("label"), item.get("kind"))
    ]
    loans = [annotate_loan(row) for row in merge_loan_evidence(real_live, real_evidence)]
    advances = merge_loan_evidence(discount_live, discount_evidence)
    for row in advances:
        row["counts_as_debt"] = False
        row["label"] = ADVANCE_LABEL if not row.get("name") else f"{ADVANCE_LABEL} — {row['name']}"
        row["note"] = ADVANCE_NOTE
    advances = [annotate_loan(row) for row in advances]
    mirrors = [{"name": a.name, "balance": _balance(a)} for a in by_kind.get("credit_line_mirror", [])]

    bank_rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.organization_id == organization_id,
            BankTransaction.superseded_by_id.is_(None),
            BankTransaction.transaction_date >= start - timedelta(days=60),
        )
        .all()
    )
    booked = [row for row in bank_rows if str((row.raw_data or {}).get("status") or "BOOKED").upper() != "PENDING"]
    last_covered = max((row.transaction_date for row in bank_rows), default=None)
    checks = match_checks(
        [c for c in evidence["checks"] if c.get("date") and _num(c.get("amount"))],
        booked, last_covered=last_covered, today=today,
    )
    upcoming = [
        {"date": c["date"], "label": f"צ׳ק {c['check']} · {c.get('payee') or ''}".strip(" ·"),
         "amount": -c["amount"], "kind": "check"}
        for c in checks
        if c["state"] == "future" and date.fromisoformat(c["date"]) <= today + timedelta(days=CHECK_HORIZON_DAYS)
    ]
    observed_on = str(evidence.get("observedAt") or "")[:10] or None
    for event in evidence["events"]:
        when = date.fromisoformat(event["date"])
        if today <= when <= today + timedelta(days=EVENT_HORIZON_DAYS):
            upcoming.append({
                "date": event["date"], "label": event.get("label"), "kind": event.get("kind") or "event",
                **_event_amount(event, evidence["facilities"], loans, observed_on),
            })
    for loan in loans:
        if loan.get("maturity") and today <= date.fromisoformat(loan["maturity"]) <= today + timedelta(days=EVENT_HORIZON_DAYS):
            upcoming.append({"date": loan["maturity"], "label": f"{loan['name']} · סיום הלוואה",
                             "kind": "loan_maturity", **_outstanding(loan.get("balance"), loan.get("as_of"))})
    for advance in advances:
        if advance.get("maturity") and today <= date.fromisoformat(advance["maturity"]) <= today + timedelta(days=EVENT_HORIZON_DAYS):
            upcoming.append({
                "date": advance["maturity"],
                "label": f"{advance.get('name') or 'ניכיון שיקים'} · מקדמה על תקבולי לקוחות",
                "kind": "check_discounting",
                "amount": None,
                "note": ADVANCE_NOTE,
            })
    upcoming.sort(key=lambda item: item["date"])

    debts = []
    if checking:
        debts.append({
            "label": "מינוס בעו״ש",
            "amount": None if balance is None else (_r(-balance) if balance < 0 else 0.0),
            "as_of": as_of.isoformat() if as_of else None,
        })
    else:
        debts.append({"label": "מינוס בעו״ש", "amount": None, "as_of": None,
                      "note": "אין חשבון עו״ש עם יתרה ידועה"})
    if cards:
        debts.append({"label": "כרטיסי אשראי", "amount": _sum_or_none(c["balance"] for c in cards),
                      "as_of": cards[0]["as_of"]})
    debts += [{
        "label": f"הלוואה — {loan['name']}", "amount": loan["balance"], "as_of": loan["as_of"],
        "source": loan.get("source"), "uncertainty": loan.get("uncertainty"),
        "owner_entered": loan.get("owner_entered"), "provider_data": loan.get("provider_data"),
        "maturity": loan.get("maturity"), "payment_amount": loan.get("payment_amount"),
        "payment_date": loan.get("payment_date"),
    } for loan in loans]
    month_rows = _months(days, limit)
    reconciled = _reconcile_months(db, [a.id for a in checking], start, end)
    for row in month_rows:
        row.update(reconciled.get(row["month"]) or {})
    seen_days = {day["account_id"] for day in days}
    omitted = [account for account in checking if account.id not in seen_days]
    if checking and not days:
        daily_balance_note = "אין יתרת סוף יום לחשבונות העו״ש בחלון, ולכן אין שפל ואין סוף חודש."
    elif omitted:
        daily_balance_note = "אין יתרת סוף יום לחלק מחשבונות העו״ש, ולכן השפל וסוף החודש אינם כוללים אותם."
    else:
        daily_balance_note = None

    if classified is None:
        from .books import classified_bank
        classified = classified_bank(db, organization_id, start, end, plan)
    status = "ready" if accounts or evidence["loans"] or evidence["checks"] else "unknown"
    return {
        "status": status,
        "position": {
            "balance": balance,
            "as_of": as_of.isoformat() if as_of else None,
            "balance_source": balance_source,
            "limit": limit,
            "limit_source": limit_source,
            "available_to_limit": None if balance is None or limit is None else _r(limit + balance),
        },
        "accounts": [
            {"account_id": a.id, "name": a.name, "kind": _account_kind(a), "bank_key": bank_key(a),
             "balance": known[a.id]["balance"] if a.id in known else _balance(a),
             "credit_limit": _num(a.credit_limit),
             "as_of": known[a.id]["as_of"].isoformat() if a.id in known else (
                 a.balance_as_of.date().isoformat() if a.balance_as_of else None),
             "balance_source": known[a.id]["source"] if a.id in known else None,
             **({"opening": known[a.id]["opening"]} if "opening" in known.get(a.id, {}) else {})}
            for a in accounts
        ],
        "cards": cards,
        "card_summary": card_summary(cards),
        "card_activity": card_activity(db, card_accounts, start, end),
        "facilities": present_facilities(checking, evidence, observed_at=evidence.get("observedAt")),
        "loans": loans,
        "advances": advances,
        "credit_line_mirrors": mirrors,
        "months": month_rows,
        "balance_vs_flow_note": BALANCE_VS_FLOW_NOTE,
        "daily_balance_note": daily_balance_note,
        "balance_conflicts": conflicts,
        "debt_service": _debt_service(classified, month_keys),
        "checks": checks,
        "check_summary": {
            state: sum(1 for c in checks if c["state"] == state)
            for state in ("cleared", "future", "not_found", "no_coverage")
        },
        "upcoming": upcoming,
        "debts": debts,
        "debts_known_total": _sum_or_none(d["amount"] for d in debts),
        "debts_complete": all(d["amount"] is not None for d in debts),
        "evidence_observed_at": evidence.get("observedAt"),
        "message": (
            "יתרות מ-Open Finance כפי שנשמרו ברצף, וראיות מתוארכות מהתוכנית. יתרת סוף יום היא שדה ספק ולא דף בנק מאומת. "
            "חשבון \"מסגרת\" משקף את המינוס בעו״ש ואינו נספר שוב."
        ),
        "provider_calls": 0,
    }


NO_AMOUNT_NOTE = "הסכום לא מתועד"


def _outstanding(balance, as_of) -> dict:
    """A loan's last known balance as the amount due at its end. The schedule
    (instalments until then) is not in the evidence, so the amount is an upper bound."""
    value = _num(balance)
    if value is None:
        return {"amount": None, "note": NO_AMOUNT_NOTE}
    when = f" נכון ל־{as_of}" if as_of else ""
    return {
        "amount": _r(-abs(value)), "amount_basis": "outstanding_balance", "amount_as_of": as_of,
        "note": f"יתרת ההלוואה{when}; לוח הסילוקין לא מתועד, ולכן זה הסכום המרבי לסילוק",
    }


def _event_amount(event: dict, facilities: list[dict], loans: list[dict], observed_on: str | None) -> dict:
    """The amount of a dated event: as documented, else the evidence it points to."""
    amount = _num(event.get("amount"))
    if amount is not None:
        return {"amount": amount, "amount_basis": "documented", "note": None}
    kind = event.get("kind")
    if kind == "loan_maturity":
        if _num(event.get("referenceBalance")) is not None:
            return _outstanding(event.get("referenceBalance"), observed_on)
        loan = next((item for item in loans if item.get("name") and item["name"] in (event.get("label") or "")), None)
        if loan is not None:
            return _outstanding(loan.get("balance"), loan.get("as_of"))
    if kind == "facility_expiry":
        facility = next((
            item for item in facilities
            if _num(item.get("limit")) is not None and event.get("account") is not None
            and str(item.get("account")) == str(event.get("account"))
        ), None)
        if facility is not None:
            limit = _r(float(facility["limit"]))
            return {"amount": None, "reference_amount": limit, "amount_basis": "facility_limit",
                    "note": f"תוקף מסגרת של {limit:,.0f} ₪ מסתיים; אין תשלום מתועד"}
    return {"amount": None, "note": NO_AMOUNT_NOTE}


def _month_keys(start: date, end: date):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield f"{year}-{month:02d}"
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _pending_unbilled(db, account_ids: list[int]) -> dict[int, float | None]:
    """Charges not yet billed, as a positive number. PENDING rows only.

    No pending rows is 0 (a known empty set). A pending row without an amount
    makes that account unknown (None).
    """
    found: dict[int, float | None] = {account_id: 0.0 for account_id in account_ids}
    if not account_ids:
        return found
    rows = (
        db.query(BankTransaction)
        .filter(BankTransaction.account_id.in_(account_ids), BankTransaction.superseded_by_id.is_(None))
        .all()
    )
    for row in rows:
        raw = row.raw_data if isinstance(row.raw_data, dict) else {}
        if str(raw.get("status") or "").strip().upper() != "PENDING":
            continue
        if found.get(row.account_id) is None:
            continue
        if row.amount is None:
            found[row.account_id] = None
            continue
        found[row.account_id] = float(found[row.account_id]) + (-float(row.amount))
    return found


def card_open_to_buy(account, balance: float | None, pending: float | None, as_of: str | None) -> dict:
    """Open-to-buy from stored data. The bank's figure wins. Otherwise limit minus
    the statement balance and pending charges. Never written back onto the account."""
    stored = _num(getattr(account, "available_limit", None))
    if stored is not None:
        return {
            "available": _r(stored), "available_source": CARD_AVAILABLE_STORED,
            "available_as_of": as_of, "available_note": None,
        }
    limit = _num(getattr(account, "credit_limit", None))
    missing = []
    if limit is None:
        missing.append("אין מסגרת")
    if balance is None:
        missing.append("אין יתרת חיוב")
    if pending is None:
        missing.append("יש עסקה ממתינה בלי סכום")
    if missing:
        return {
            "available": None, "available_source": None, "available_as_of": as_of,
            "available_note": "פנוי לא ידוע: " + ", ".join(missing) + ". לא הומצא סכום.",
        }
    return {
        "available": _r(limit - balance - pending),
        "available_source": CARD_AVAILABLE_DERIVED,
        "available_as_of": as_of,
        "available_note": (
            "חושב מהנתונים השמורים: מסגרת פחות יתרת החיוב ופחות עסקאות PENDING. "
            "זה אינו הסכום שהבנק מסר כפנוי."
        ),
    }


def present_facilities(checking: list, evidence: dict, *, observed_at) -> list[dict]:
    """Credit lines from stored accounts, plus the cheque-discounting facility.

    The discounting limit is whatever the owner entered. It is not invented, and
    it is not labelled as provider data.
    """
    observed = str(observed_at or "")[:10] or None
    rows = []
    if checking:
        for account in checking:
            limit = _num(account.credit_limit)
            balance = _balance(account)
            as_of = account.balance_as_of.date().isoformat() if account.balance_as_of else None
            rows.append({
                "label": account.name or "מסגרת אשראי",
                "kind": "credit_line",
                "limit": limit,
                "available": None if limit is None or balance is None else _r(limit + balance),
                "source": "accounts.credit_limit" if limit is not None else None,
                "as_of": as_of,
                "owner_entered": False,
                "provider_data": getattr(account, "source", None) == "open_finance",
                "uncertainty": None if limit is not None else "מסגרת האשראי לא ידועה בנתונים השמורים",
            })
    else:
        rows.append({
            "label": "מסגרת אשראי", "kind": "credit_line", "limit": None, "available": None,
            "source": None, "as_of": None, "owner_entered": False, "provider_data": False,
            "uncertainty": "אין חשבון עו״ש, ולכן המסגרת לא ידועה",
        })
    discount = None
    for item in evidence.get("facilities") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        if kind in ("cheque_discounting", "check_discounting") or is_check_discounting(item.get("label"), kind):
            discount = item
            continue
        limit = _num(item.get("limit"))
        rows.append({
            "label": item.get("label") or "מסגרת",
            "kind": kind or "credit_line",
            "limit": limit,
            "available": None,
            "source": OWNER_EVIDENCE_SOURCE,
            "as_of": item.get("asOf") or observed,
            "owner_entered": True,
            "provider_data": False,
            "uncertainty": None if limit is not None else UNKNOWN_OWNER_AMOUNT,
        })
    limit = _num(discount.get("limit")) if isinstance(discount, dict) else None
    rows.append({
        "label": (discount.get("label") if isinstance(discount, dict) and discount.get("label") else "ניכיון שיקים"),
        "kind": "cheque_discounting",
        "limit": limit,
        "available": None,
        "source": OWNER_EVIDENCE_SOURCE if isinstance(discount, dict) else None,
        "as_of": (discount.get("asOf") if isinstance(discount, dict) else None) or observed,
        "owner_entered": isinstance(discount, dict),
        "provider_data": False,
        "uncertainty": None if limit is not None else UNKNOWN_OWNER_AMOUNT,
    })
    return rows


def present_cards(db, accounts: list) -> list[dict]:
    """One row per card: statement balance, limit, available, and the last transaction date."""
    ids = [account.id for account in accounts if getattr(account, "id", None) is not None]
    last: dict[int, date] = {}
    if ids:
        for account_id, day in (
            db.query(BankTransaction.account_id, func.max(BankTransaction.transaction_date))
            .filter(BankTransaction.account_id.in_(ids), BankTransaction.superseded_by_id.is_(None))
            .group_by(BankTransaction.account_id)
        ):
            last[account_id] = day
    pending = _pending_unbilled(db, ids)
    cards = []
    for account in accounts:
        as_of = account.balance_as_of.date().isoformat() if account.balance_as_of else None
        last_day = last.get(account.id)
        last_iso = last_day.isoformat() if last_day else None
        mismatch = bool(as_of and last_iso and as_of != last_iso)
        if mismatch:
            note = f"יתרת הכרטיס נכונה ל־{as_of}. התנועה האחרונה בכרטיס היא {last_iso}."
        elif as_of and not last_iso:
            note = f"יתרת הכרטיס נכונה ל־{as_of}. אין תנועת כרטיס שמורה להשוואה."
        else:
            note = None
        balance = None if _balance(account) is None else _r(abs(_balance(account)))
        open_to_buy = card_open_to_buy(account, balance, pending.get(account.id, 0.0), as_of)
        cards.append({
            "name": account.name,
            "bank_key": bank_key(account),
            "balance": balance,
            "credit_limit": _num(account.credit_limit),
            **open_to_buy,
            "as_of": as_of,
            "last_data": last_iso,
            "date_mismatch": mismatch,
            "date_note": note,
        })
    return cards


def card_activity(db, accounts: list, start: date, end: date) -> dict:
    """The default card-transaction bucket: BOOKED rows, including a missing status.

    PENDING rows are unbilled charges and stay out of this bucket. Any other
    status, or a row without an amount, leaves the amount unknown and says why.
    The bucket itself stays defined, so the screen does not report that it is missing.
    """
    base = {
        "key": "cards",
        "label": "עסקאות כרטיסי אשראי",
        "counts_as_debt": False,
        "counts_as_balance": False,
        "definition": CARD_ACTIVITY_DEFINITION,
        "defined": True,
        "excluded_count": 0,
    }
    if not accounts:
        return {**base, "amount": None, "count": None,
                "definition": "אין חשבונות כרטיס, ולכן אין עסקאות. לא הומצא סכום."}
    ids = [account.id for account in accounts]
    rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.account_id.in_(ids),
            BankTransaction.transaction_date >= start,
            BankTransaction.transaction_date <= end,
            BankTransaction.superseded_by_id.is_(None),
        )
        .all()
    )
    booked = []
    excluded = []
    missing_amount = False
    for row in rows:
        raw = row.raw_data if isinstance(row.raw_data, dict) else {}
        status = str(raw.get("status") or "").strip().upper()
        if row.source == "open_finance":
            if not status:
                status = "BOOKED"
            if status == "PENDING":
                continue
            if status != "BOOKED":
                excluded.append(status)
                continue
        if row.amount is None:
            missing_amount = True
            continue
        booked.append(row)
    if missing_amount or excluded:
        parts = []
        if excluded:
            parts.append(f"{len(excluded)} תנועות במצב לא מוכר ({', '.join(sorted(set(excluded)))})")
        if missing_amount:
            parts.append("תנועה בלי סכום")
        return {
            **base, "amount": None, "count": None, "excluded_count": len(excluded),
            "definition": "דלי העסקאות מוגדר (BOOKED, וסטטוס חסר נחשב BOOKED). הסכום לא ידוע: "
            + "; ".join(parts) + ". לא הוצג סכום חלקי ולא 0.",
        }
    return {**base, "amount": _r(sum(float(row.amount or 0) for row in booked)), "count": len(booked)}


def card_summary(cards: list[dict]) -> dict:
    """Card totals: a total is known only when every card's value is known;
    ``*_known`` sums the cards that are, and ``*_unknown`` counts the rest."""
    out = {}
    for key, field in (("available", "available"), ("credit_limit", "credit_limit"), ("balance", "balance")):
        values = [card.get(field) for card in cards]
        missing = sum(1 for value in values if value is None)
        out[key] = None if not values or missing else _r(sum(value for value in values if value is not None))
        out[f"{key}_known"] = _sum_or_none(values)
        out[f"{key}_unknown"] = missing
    return out


def _combine_card_activity(parts) -> dict | None:
    acts = [part.get("card_activity") for _label, part in parts if isinstance(part.get("card_activity"), dict)]
    if not acts:
        return None
    unknown = {
        "key": "cards", "label": "עסקאות כרטיסי אשראי", "defined": True,
        "amount": None, "count": None, "counts_as_debt": False, "counts_as_balance": False,
        "definition": "לחלק מהישויות סכום עסקאות הכרטיס לא ידוע, ולכן אין סכום מאוחד. לא הוצג 0.",
    }
    amounts = [act.get("amount") for act in acts]
    counts = [act.get("count") for act in acts]
    if any(act.get("defined") is False for act in acts) or any(value is None for value in amounts) or any(value is None for value in counts):
        return unknown
    return {
        "key": "cards", "label": "עסקאות כרטיסי אשראי", "defined": True,
        "amount": _r(sum(amounts)), "count": int(sum(counts)),
        "counts_as_debt": False, "counts_as_balance": False,
        "definition": CARD_ACTIVITY_DEFINITION,
    }


def _collapse_advances(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list] = {}
    order: list[str] = []
    for row in rows:
        key = re.sub(r"\s+", " ", str(row.get("name") or row.get("label") or "")).strip()
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(row)
    out = []
    for key in order:
        items = grouped[key]
        if len(items) == 1:
            out.append(items[0])
            continue
        known = [item.get("balance") for item in items if item.get("balance") is not None]
        kept = dict(items[0])
        kept["counts_as_debt"] = False
        if not known or len({_r(float(value)) for value in known}) > 1:
            kept["balance"] = None
            kept["note"] = "אותה מקדמה רשומה ביותר מישות והסכום לא ידוע. אינה חוב."
        else:
            kept["balance"] = _r(float(known[0]))
            kept["note"] = "אותה מקדמה רשומה ביותר מישות ונספרת פעם אחת. אינה חוב."
        out.append(kept)
    return out


def combine(sections: list[dict]) -> dict:
    """Combined position of several entities.

    The combined balance is the sum only when every entity's balance is known.
    Otherwise ``balance`` stays unknown and ``balance_known`` carries the sum of
    the entities that are known, with a note naming the ones that are not.
    """
    parts = [(section.get("label"), section.get("liquidity") or {}) for section in sections]
    entities = []
    for label, part in parts:
        position = part.get("position") or {}
        entities.append({
            "entity": label,
            "balance": position.get("balance"),
            "as_of": position.get("as_of"),
            "balance_source": position.get("balance_source"),
            "limit": position.get("limit"),
            "limit_source": position.get("limit_source"),
            "available_to_limit": position.get("available_to_limit"),
        })
    balances = [entity["balance"] for entity in entities]
    missing = [entity["entity"] or "ישות" for entity in entities if entity["balance"] is None]
    limits = [entity["limit"] for entity in entities]
    debts = []
    for label, part in parts:
        for debt in part.get("debts") or []:
            debts.append({**debt, "entity": label})
    upcoming = sorted(
        ({**item, "entity": label} for label, part in parts for item in part.get("upcoming") or []),
        key=lambda item: item["date"],
    )
    service: dict[str, dict] = {}
    for _label, part in parts:
        for row in part.get("debt_service") or []:
            slot = service.setdefault(row["month"], {"month": row["month"], "principal": 0.0, "interest": 0.0, "new_loans": 0.0})
            for key in ("principal", "interest", "new_loans"):
                slot[key] = _r(slot[key] + (row.get(key) or 0.0))
    cards = [{**card, "entity": label} for label, part in parts for card in part.get("cards") or []]
    facilities = [
        {**item, "entity": label}
        for label, part in parts for item in part.get("facilities") or []
        if isinstance(item, dict)
    ]
    advances = _collapse_advances(
        [{**item, "entity": label} for label, part in parts for item in part.get("advances") or [] if isinstance(item, dict)]
    )
    balance = None if missing else _r(sum(balances))
    limit = None if any(value is None for value in limits) else _r(sum(limits))
    return {
        "status": "ready" if any(part.get("status") == "ready" for _l, part in parts) else "unknown",
        "balance": balance,
        "balance_known": _sum_or_none(balances),
        "balance_note": None if not missing else (
            "יתרת העו״ש של " + ", ".join(missing) + " אינה ידועה, ולכן אין יתרה מאוחדת. "
            "הסכום החלקי כולל רק את הישויות שהיתרה שלהן ידועה."
        ),
        "as_of": min((e["as_of"] for e in entities if e["as_of"]), default=None),
        "limit": limit,
        "limit_known": _sum_or_none(limits),
        "available_to_limit": None if balance is None or limit is None else _r(limit + balance),
        "entities": entities,
        "debts": debts,
        "debts_known_total": _sum_or_none(d.get("amount") for d in debts),
        "debts_complete": all(d.get("amount") is not None for d in debts),
        "upcoming": upcoming,
        "cards": cards,
        "facilities": facilities,
        "card_summary": card_summary(cards),
        "card_activity": _combine_card_activity(parts),
        "advances": advances,
        "balance_vs_flow_note": BALANCE_VS_FLOW_NOTE,
        "debt_service": [service[key] for key in sorted(service)],
        "provider_calls": 0,
    }


def redact_public(section):
    """No account ids on /d/."""
    if not isinstance(section, dict):
        return section
    copied = dict(section)
    if isinstance(copied.get("accounts"), list):
        copied["accounts"] = [
            {key: value for key, value in account.items() if key != "account_id"}
            for account in copied["accounts"] if isinstance(account, dict)
        ]
    return copied
