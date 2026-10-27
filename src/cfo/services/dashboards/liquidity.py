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
    rows = [
        {"name": item.get("label"), "balance": _num(item.get("balance")), "as_of": item.get("asOf"),
         "maturity": item.get("maturity"), "source": "evidence"}
        for item in evidence
    ]
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
    live_names = {_name_key(loan["name"]) for loan in live}
    merged += [
        row for i, row in enumerate(rows)
        if i not in used_rows and _name_key(row["name"]) not in live_names
    ]
    return merged


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
    cards = [
        {"name": a.name, "balance": None if _balance(a) is None else _r(abs(_balance(a))),
         "credit_limit": _num(a.credit_limit), "available": _num(a.available_limit),
         "as_of": a.balance_as_of.date().isoformat() if a.balance_as_of else None}
        for a in by_kind.get("card", [])
    ]
    loans = [
        {"name": a.name, "balance": None if _balance(a) is None else _r(abs(_balance(a))),
         "as_of": a.balance_as_of.date().isoformat() if a.balance_as_of else None, "source": "accounts"}
        for a in by_kind.get("loan", [])
    ]
    loans = merge_loan_evidence(loans, evidence["loans"])
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
    debts += [{"label": f"הלוואה — {loan['name']}", "amount": loan["balance"], "as_of": loan["as_of"]} for loan in loans]

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
            {"account_id": a.id, "name": a.name, "kind": _account_kind(a),
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


def card_summary(cards: list[dict]) -> dict:
    """Card totals: a total is known only when every card's value is known;
    ``*_known`` sums the cards that are."""
    out = {}
    for key, field in (("available", "available"), ("credit_limit", "credit_limit")):
        values = [card.get(field) for card in cards]
        out[key] = None if not values or any(v is None for v in values) else _r(sum(values))
        out[f"{key}_known"] = _sum_or_none(values)
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
        "card_summary": card_summary(cards),
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
