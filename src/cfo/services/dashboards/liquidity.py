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
  loan maturities). Each item may name an ``organizationId``.

Unknown is ``None``, never 0. A loan account whose name says it is the credit
line ("מסגרת") mirrors the overdraft and is not added to the debts again.
No provider calls.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from ...models import Account, BankTransaction, DashboardEntityAccount

CHECKING_TYPES = {"CHECKING", "CURRENT", "SAVINGS"}
CARD = "CARD"
LOAN = "LOAN"
CREDIT_LINE_TEXT = "מסגרת"
CHECK_TEXT = re.compile(r"שיק|צ'ק|צ׳ק|צ\"ק")
CHECK_HORIZON_DAYS = 120
EVENT_HORIZON_DAYS = 400
EVIDENCE_KINDS = ("facilities", "loans", "checks", "events")


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


def _balance(account: Account) -> float | None:
    """A balance counts only with its date. A local import leaves 0 without a date: unknown."""
    if account.balance_as_of is None:
        return None
    return _num(account.balance)


def _account_kind(account: Account) -> str:
    raw = str(account.raw_account_type or "").strip().upper()
    if raw == CARD:
        return "card"
    if raw == LOAN:
        return "credit_line_mirror" if CREDIT_LINE_TEXT in (account.name or "") else "loan"
    if raw in CHECKING_TYPES:
        return "checking"
    return "other"


def entity_accounts(db, organization_id: int, entity_id: int | None) -> list[Account]:
    bound: list[int] = []
    if entity_id:
        bound = [row.account_id for row in db.query(DashboardEntityAccount).filter_by(entity_id=entity_id).all()]
    query = db.query(Account).filter(Account.organization_id == organization_id)
    if bound:
        query = query.filter(Account.id.in_(bound))
    else:
        query = query.filter(Account.source == "open_finance")
    return query.order_by(Account.id).all()


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
    by_month: dict[str, dict] = {}
    for day in days:
        month = day["date"][:7]
        slot = by_month.setdefault(month, {
            "month": month, "days": 0, "min": None, "negative_days": 0,
            "beyond_limit_days": None if limit is None else 0, "last": None,
        })
        balance = day["balance"]
        slot["days"] += 1
        slot["min"] = balance if slot["min"] is None else min(slot["min"], balance)
        if balance < 0:
            slot["negative_days"] += 1
        if limit is not None and balance < -limit:
            slot["beyond_limit_days"] += 1
        slot["last"] = balance
    return [by_month[key] for key in sorted(by_month)]


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
    balances = [_balance(account) for account in checking]
    balance = None if not checking or any(value is None for value in balances) else _r(sum(balances))
    as_of = max((a.balance_as_of for a in checking if a.balance_as_of), default=None)
    limits = [_num(account.credit_limit) for account in checking]
    limit = None if not checking or any(value is None for value in limits) else _r(sum(limits))
    limit_source = "accounts.credit_limit" if limit is not None else None
    facility = next((item for item in evidence["facilities"] if _num(item.get("limit")) is not None), None)
    if limit is None and facility is not None:
        limit = _r(float(facility["limit"]))
        limit_source = "plan.liquidityEvidence"

    days, conflicts = _daily_balances(db, [a.id for a in checking], start, end)
    month_keys = list(_month_keys(start, end))

    cards = [
        {"name": a.name, "balance": None if _balance(a) is None else _r(abs(_balance(a))),
         "as_of": a.balance_as_of.date().isoformat() if a.balance_as_of else None}
        for a in by_kind.get("card", [])
    ]
    loans = [
        {"name": a.name, "balance": None if _balance(a) is None else _r(abs(_balance(a))),
         "as_of": a.balance_as_of.date().isoformat() if a.balance_as_of else None, "source": "accounts"}
        for a in by_kind.get("loan", [])
    ]
    loans += [
        {"name": item.get("label"), "balance": _num(item.get("balance")), "as_of": item.get("asOf"),
         "maturity": item.get("maturity"), "source": "evidence"}
        for item in evidence["loans"]
    ]
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
    for event in evidence["events"]:
        when = date.fromisoformat(event["date"])
        if today <= when <= today + timedelta(days=EVENT_HORIZON_DAYS):
            upcoming.append({
                "date": event["date"], "label": event.get("label"), "kind": event.get("kind") or "event",
                "amount": _num(event.get("amount")),
                "note": None if _num(event.get("amount")) is not None else "הסכום לא מתועד",
            })
    for loan in loans:
        if loan.get("maturity") and today <= date.fromisoformat(loan["maturity"]) <= today + timedelta(days=EVENT_HORIZON_DAYS):
            upcoming.append({"date": loan["maturity"], "label": f"{loan['name']} · סיום הלוואה",
                             "kind": "loan_maturity", "amount": None, "note": "הסכום לא מתועד"})
    upcoming.sort(key=lambda item: item["date"])

    debts = []
    if checking:
        debts.append({
            "label": "מינוס בעו״ש",
            "amount": None if balance is None else (_r(-balance) if balance < 0 else 0.0),
            "as_of": as_of.date().isoformat() if as_of else None,
        })
    else:
        debts.append({"label": "מינוס בעו״ש", "amount": None, "as_of": None,
                      "note": "אין חשבון עו״ש עם יתרה ידועה"})
    if cards:
        debts.append({"label": "כרטיסי אשראי", "amount": _sum_or_none(c["balance"] for c in cards),
                      "as_of": cards[0]["as_of"]})
    debts += [{"label": f"הלוואה — {loan['name']}", "amount": loan["balance"], "as_of": loan["as_of"]} for loan in loans]

    if classified is None:
        from .books import classified_bank
        classified = classified_bank(db, organization_id, start, end, plan)
    status = "ready" if accounts or evidence["loans"] or evidence["checks"] else "unknown"
    return {
        "status": status,
        "position": {
            "balance": balance,
            "as_of": as_of.date().isoformat() if as_of else None,
            "limit": limit,
            "limit_source": limit_source,
            "available_to_limit": None if balance is None or limit is None else _r(limit + balance),
        },
        "accounts": [
            {"account_id": a.id, "name": a.name, "kind": _account_kind(a),
             "balance": _balance(a), "credit_limit": _num(a.credit_limit),
             "as_of": a.balance_as_of.date().isoformat() if a.balance_as_of else None}
            for a in accounts
        ],
        "cards": cards,
        "loans": loans,
        "credit_line_mirrors": mirrors,
        "months": _months(days, limit),
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


def _month_keys(start: date, end: date):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield f"{year}-{month:02d}"
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def combine(sections: list[dict]) -> dict:
    """Combined position of several entities. A missing balance keeps the sum unknown."""
    parts = [(section.get("label"), section.get("liquidity") or {}) for section in sections]
    balances = [(part.get("position") or {}).get("balance") for _label, part in parts]
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
    return {
        "status": "ready" if any(part.get("status") == "ready" for _l, part in parts) else "unknown",
        "balance": None if any(value is None for value in balances) else _r(sum(balances)),
        "balance_note": None if all(value is not None for value in balances) else
            "יתרת העו״ש של לפחות ישות אחת אינה ידועה, ולכן היתרה המאוחדת אינה מוצגת.",
        "debts": debts,
        "debts_known_total": _sum_or_none(d.get("amount") for d in debts),
        "debts_complete": all(d.get("amount") is not None for d in debts),
        "upcoming": upcoming,
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
