"""Suspected bank duplicates and a card-bill check for the dashboard view.

BOOKED-only totals, future-charge PENDING rows, the sync supersede pointer,
and card-account exclusion already live in ``bank_status`` and the cash-flow
read. This module does not repeat those filters and does not write rows.

It lists suspected pairs (including העברת יומן against העברה באינטרנט), drops
only pairs an admin confirmed in ``payload.dedupePairs``, and warns when a
month's card transactions and the checking-account card bill differ by more
than 1%.

A confirmed pair is applied only when it could be a duplicate: same
organization, same account, same amount, at most five days apart. Any other
pair is refused with a warning, so a plan edit cannot erase an arbitrary
bank row. The same drops apply to the cash-basis P&L (``books``), so cash
flow and P&L read one row set.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from ...models import BankTransaction, ClientDashboard, DashboardPlan
from ..bank_coverage import cashflow_row_objects, content_fingerprint
from ..bank_status import card_account_ids

OF_SOURCE = "open_finance"
BOOKED = "BOOKED"
FUTURE_CHARGE_TEXT = "חיובים עתידיים"
REF_WINDOW_DAYS = 5
FINGERPRINT_WINDOW_DAYS = 3
BILL_TOLERANCE = Decimal("0.01")


@dataclass(frozen=True)
class Txn:
    id: int
    organization_id: int | None
    account_id: int | None
    transaction_date: date
    amount: Decimal
    description: str | None
    status: str | None
    entry_reference: str | None
    content_fingerprint: str
    superseded_by_id: int | None
    source: str | None
    is_card: bool = False


@dataclass
class Outcome:
    pairs: list[dict]
    notes: list[dict]
    warnings: list[dict]
    billing_cycles: list[dict]
    drop_ids: set[int]

    def as_view(self) -> dict:
        return {
            "notes": self.notes,
            "warnings": self.warnings,
            "billing_cycles": self.billing_cycles,
        }


def is_future_charge(description: str | None) -> bool:
    if not description:
        return False
    return FUTURE_CHARGE_TEXT in " ".join(description.split())


def is_card_bill(description: str | None) -> bool:
    """Heuristic for the monthly card settlement on the current account.

    A miss becomes an unknown billing-cycle warning. It never changes a total.
    """
    if not description or is_future_charge(description):
        return False
    text = " ".join(description.casefold().split())
    has_visa = "ויזה" in text or "visa" in text
    has_cal = "כאל" in text or "כ.א.ל" in text or _has_cal_word(text)
    has_charge = "חיוב" in text
    return (has_visa and has_cal) or (has_charge and (has_visa or has_cal))


def is_journal_transfer(description: str | None) -> bool:
    if not description:
        return False
    text = " ".join(description.split())
    return "העברת יומן" in text or "יומן זכות" in text


def is_internet_transfer(description: str | None) -> bool:
    if not description:
        return False
    return "העברה באינטרנט" in " ".join(description.split())


def parse_confirmed_pairs(payload: dict | None) -> tuple[list[tuple[int, int]], list[dict]]:
    warnings: list[dict] = []
    if not payload:
        return [], warnings
    raw = payload.get("dedupePairs")
    if raw is None:
        return [], warnings
    if not isinstance(raw, list):
        warnings.append({
            "code": "invalid_dedupe_pairs",
            "message_he": "dedupePairs אינו רשימה — זוגות שאושרו לא הוחלו.",
        })
        return [], warnings
    pairs: list[tuple[int, int]] = []
    skipped = 0
    for item in raw:
        keep = drop = None
        if isinstance(item, dict):
            keep = item.get("keepId", item.get("keep_id"))
            drop = item.get("dropId", item.get("drop_id"))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            keep, drop = item[0], item[1]
        else:
            skipped += 1
            continue
        keep_id = _as_int(keep)
        drop_id = _as_int(drop)
        if keep_id is None or drop_id is None or keep_id == drop_id:
            skipped += 1
            continue
        pairs.append((keep_id, drop_id))
    if skipped:
        warnings.append({
            "code": "invalid_dedupe_pairs",
            "message_he": f"{skipped} פריטים ב-dedupePairs בלי מזהים תקינים לא הוחלו.",
        })
    return pairs, warnings


def classify(
    txns: list[Txn],
    *,
    card_account_ids: set[int] | None = None,
    confirmed_pairs: list[tuple[int, int]] | None = None,
) -> Outcome:
    """Pair suspects and confirmed drops. Does not rebuild a cash-flow total."""
    card_ids = set(card_account_ids or ())
    confirmed = list(confirmed_pairs or ())
    by_id = {txn.id: txn for txn in txns}
    drop_ids: set[int] = set()
    missing = 0
    confirmed_rows: list[tuple[Txn, Txn]] = []
    refused = 0
    for keep_id, drop_id in confirmed:
        keep = by_id.get(keep_id)
        drop = by_id.get(drop_id)
        if keep is None or drop is None:
            missing += 1
            continue
        if not could_be_duplicates(keep, drop):
            refused += 1
            continue
        drop_ids.add(drop_id)
        confirmed_rows.append((keep, drop))

    cash = [txn for txn in txns if not _is_card_txn(txn, card_ids)]
    detected = _journal_internet_pairs(cash)
    used = {txn_id for left, right, _rule in detected for txn_id in (left.id, right.id)}
    detected.extend(_reference_pairs(cash, used))
    used = {txn_id for left, right, _rule in detected for txn_id in (left.id, right.id)}
    detected.extend(_fingerprint_pairs(cash, used))

    seen = {frozenset((left.id, right.id)) for left, right, _rule in detected}
    pairs: list[dict] = []
    warnings: list[dict] = []
    for left, right, rule in detected:
        disposition = "confirmed" if left.id in drop_ids or right.id in drop_ids else _open_disposition(left, right)
        pairs.append(_pair_row(left, right, rule, disposition))
        if disposition == "warning":
            warnings.append(_suspected_warning(left, right, rule))
    for keep, drop in confirmed_rows:
        if frozenset((keep.id, drop.id)) in seen:
            continue
        pairs.append(_pair_row(keep, drop, "confirmed", "confirmed"))

    if refused:
        warnings.append({
            "code": "refused_dedupe_pair",
            "message_he": (
                f"{refused} זוגות dedupePairs אינם באותו חשבון, באותו סכום ובטווח של חמישה ימים, "
                "ולא הוחלו."
            ),
        })
    if missing:
        warnings.append({
            "code": "unmatched_dedupe_pair",
            "message_he": f"{missing} זוגות dedupePairs מפנים לתנועה שאינה בחלון, ולא הוחלו.",
        })
    notes = []
    if drop_ids:
        notes.append({"message_he": (
            f"{len(drop_ids)} תנועות הוסרו לפי זוגות כפילות שאושרו בתוכנית הדשבורד."
        )})
    cycle_warnings, cycles = _billing_cycles(txns, card_ids)
    warnings.extend(cycle_warnings)
    return Outcome(
        pairs=pairs,
        notes=notes,
        warnings=warnings,
        billing_cycles=cycles,
        drop_ids=drop_ids,
    )


def could_be_duplicates(keep, drop) -> bool:
    """Same org, same account, same amount, at most REF_WINDOW_DAYS apart."""
    if keep.organization_id != drop.organization_id:
        return False
    if keep.account_id is None or keep.account_id != drop.account_id:
        return False
    if _q(keep.amount) != _q(drop.amount):
        return False
    return abs((keep.transaction_date - drop.transaction_date).days) <= REF_WINDOW_DAYS


def confirmed_drop_ids(rows, plan_payload: dict | None) -> set[int]:
    """Ids among ``rows`` removed by a valid confirmed pair whose keep row is also present."""
    confirmed, _warnings = parse_confirmed_pairs(plan_payload)
    if not confirmed:
        return set()
    by_id = {row.id: row for row in rows}
    drops: set[int] = set()
    for keep_id, drop_id in confirmed:
        keep = by_id.get(keep_id)
        drop = by_id.get(drop_id)
        if keep is not None and drop is not None and could_be_duplicates(keep, drop):
            drops.add(drop_id)
    return drops


def adjust_cashflow(db, organization_id: int, cashflow: dict, plan_payload: dict | None) -> dict:
    """Subtract admin-confirmed drops and attach warnings. Totals otherwise stay."""
    if not isinstance(cashflow, dict):
        return cashflow
    months = cashflow.get("months") or []
    if not months or "as_of" not in cashflow:
        return cashflow
    start = _window_start(months)
    end = date.fromisoformat(str(cashflow["as_of"]))
    confirmed, pair_warnings = parse_confirmed_pairs(plan_payload)
    cards = card_account_ids(db, organization_id)
    txns = load_txns(db, organization_id, start, end, respect_coverage=True)
    outcome = classify(txns, card_account_ids=cards, confirmed_pairs=confirmed)
    service_ids = {row.id for row in cashflow_row_objects(db, organization_id, start, end)}
    remove = [txn for txn in txns if txn.id in service_ids and txn.id in outcome.drop_ids]
    updated = dict(cashflow)
    if remove:
        updated["months"] = _subtract_rows(months, remove)
    view = outcome.as_view()
    view["warnings"] = pair_warnings + view["warnings"]
    updated["activity_quality"] = view
    return updated


def load_txns(db, organization_id: int, start: date | None, end: date | None, *,
              respect_coverage: bool) -> list[Txn]:
    query = db.query(BankTransaction).filter(BankTransaction.organization_id == organization_id)
    if start is not None:
        query = query.filter(BankTransaction.transaction_date >= start)
    if end is not None:
        query = query.filter(BankTransaction.transaction_date <= end)
    rows = query.all()
    if respect_coverage:
        rows = _coverage_keeps(db, organization_id, rows)
    return [txn_from_row(row) for row in rows]


def txn_from_row(row: BankTransaction) -> Txn:
    raw = row.raw_data if isinstance(row.raw_data, dict) else {}
    reference = _text(raw.get("entryReference")) or _text(raw.get("entry_reference"))
    stored = _text(row.content_fingerprint)
    fingerprint = stored or content_fingerprint(row.transaction_date, row.amount, row.description)
    return Txn(
        id=row.id,
        organization_id=row.organization_id,
        account_id=row.account_id,
        transaction_date=row.transaction_date,
        amount=row.amount if isinstance(row.amount, Decimal) else Decimal(str(row.amount or 0)),
        description=row.description,
        status=_status(raw.get("status")),
        entry_reference=reference,
        content_fingerprint=fingerprint,
        superseded_by_id=row.superseded_by_id,
        source=row.source,
        is_card=str(raw.get("type") or "").strip().upper() == "CARD",
    )


def confirmed_pairs_for_org(db, organization_id: int) -> list[tuple[int, int]]:
    """Union of admin pairs on this organization's dashboards. Read only."""
    rows = (
        db.query(DashboardPlan)
        .join(ClientDashboard, ClientDashboard.id == DashboardPlan.dashboard_id)
        .filter(ClientDashboard.primary_organization_id == organization_id)
        .all()
    )
    pairs: list[tuple[int, int]] = []
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else None
        parsed, _warnings = parse_confirmed_pairs(payload)
        pairs.extend(parsed)
    return pairs


def duplicate_pairs(db, organization_id: int | None = None) -> list[dict]:
    """Suspected, already-excluded, and admin-confirmed pairs. Read only."""
    if organization_id is not None:
        org_ids = [organization_id]
    else:
        org_ids = [
            row[0]
            for row in db.query(BankTransaction.organization_id).distinct().order_by(
                BankTransaction.organization_id
            )
        ]
    found: list[dict] = []
    for org_id in org_ids:
        txns = load_txns(db, org_id, None, None, respect_coverage=False)
        outcome = classify(
            txns,
            card_account_ids=card_account_ids(db, org_id),
            confirmed_pairs=confirmed_pairs_for_org(db, org_id),
        )
        found.extend(outcome.pairs)
    found.sort(key=lambda item: (
        item.get("organization_id") or 0,
        item.get("account_id") or 0,
        item.get("month") or "",
        item.get("left_id") or 0,
        item.get("right_id") or 0,
        item.get("rule") or "",
    ))
    return found


def _journal_internet_pairs(txns: list[Txn]) -> list[tuple[Txn, Txn, str]]:
    journals = [txn for txn in txns if is_journal_transfer(txn.description) and txn.account_id is not None]
    internets = [txn for txn in txns if is_internet_transfer(txn.description) and txn.account_id is not None]
    used: set[int] = set()
    pairs = []
    for journal in sorted(journals, key=lambda txn: (txn.transaction_date, txn.id)):
        if journal.id in used:
            continue
        best = None
        best_key = None
        for other in internets:
            if other.id in used or other.id == journal.id or other.account_id != journal.account_id:
                continue
            if _q(other.amount) != _q(journal.amount):
                continue
            delta = abs((other.transaction_date - journal.transaction_date).days)
            if delta > REF_WINDOW_DAYS:
                continue
            key = (delta, other.id)
            if best_key is None or key < best_key:
                best = other
                best_key = key
        if best is not None:
            used.add(journal.id)
            used.add(best.id)
            pairs.append((journal, best, "journal_vs_internet"))
    return pairs


def _reference_pairs(txns: list[Txn], used: set[int]) -> list[tuple[Txn, Txn, str]]:
    pending = [
        txn for txn in txns
        if txn.id not in used and txn.source == OF_SOURCE and txn.status != BOOKED
        and txn.entry_reference and txn.account_id is not None
    ]
    booked = [
        txn for txn in txns
        if txn.status == BOOKED and txn.entry_reference and txn.account_id is not None
    ]
    pairs = []
    claimed = set(used)
    for left in sorted(pending, key=lambda txn: (txn.transaction_date, txn.id)):
        if left.id in claimed:
            continue
        candidates = [
            txn for txn in booked
            if txn.id not in claimed and txn.account_id == left.account_id
            and txn.entry_reference == left.entry_reference and _q(txn.amount) == _q(left.amount)
            and abs((txn.transaction_date - left.transaction_date).days) <= REF_WINDOW_DAYS
        ]
        if not candidates:
            continue
        right = min(candidates, key=lambda txn: (abs((txn.transaction_date - left.transaction_date).days), txn.id))
        claimed.add(left.id)
        claimed.add(right.id)
        pairs.append((left, right, "entry_reference"))
    groups: dict[tuple, list[Txn]] = {}
    for txn in booked:
        if txn.id in claimed:
            continue
        groups.setdefault((txn.account_id, txn.entry_reference, _q(txn.amount)), []).append(txn)
    for group in groups.values():
        ordered = sorted(group, key=lambda txn: (txn.transaction_date, txn.id))
        for index, left in enumerate(ordered):
            if left.id in claimed:
                continue
            for right in ordered[index + 1:]:
                if right.id in claimed:
                    continue
                if abs((right.transaction_date - left.transaction_date).days) > REF_WINDOW_DAYS:
                    continue
                claimed.add(left.id)
                claimed.add(right.id)
                pairs.append((left, right, "duplicate_booked_reference"))
                break
    return pairs


def _fingerprint_pairs(txns: list[Txn], used: set[int]) -> list[tuple[Txn, Txn, str]]:
    groups: dict[tuple, list[Txn]] = {}
    for txn in txns:
        if txn.id in used or txn.status != BOOKED or txn.account_id is None or not txn.content_fingerprint:
            continue
        groups.setdefault((txn.account_id, txn.content_fingerprint, _q(txn.amount)), []).append(txn)
    pairs = []
    for group in groups.values():
        ordered = sorted(group, key=lambda txn: (txn.transaction_date, txn.id))
        claimed: set[int] = set()
        for index, left in enumerate(ordered):
            if left.id in claimed:
                continue
            for right in ordered[index + 1:]:
                if right.id in claimed:
                    continue
                if abs((right.transaction_date - left.transaction_date).days) > FINGERPRINT_WINDOW_DAYS:
                    continue
                claimed.add(left.id)
                claimed.add(right.id)
                pairs.append((left, right, "duplicate_booked_fingerprint"))
                break
    return pairs


def _open_disposition(left: Txn, right: Txn) -> str:
    if left.status == BOOKED and right.status == BOOKED:
        return "warning"
    return "excluded"


def _billing_cycles(txns: list[Txn], card_ids: set[int]) -> tuple[list[dict], list[dict]]:
    by_month: dict[str, list[Txn]] = {}
    for txn in txns:
        if txn.status != BOOKED or not _is_card_txn(txn, card_ids):
            continue
        by_month.setdefault(_month(txn.transaction_date), []).append(txn)
    warnings = []
    cycles = []
    for month in sorted(by_month):
        card = sum((_q(txn.amount) for txn in by_month[month]), Decimal("0"))
        bills = [
            txn for txn in txns
            if _month(txn.transaction_date) == month and not _is_card_txn(txn, card_ids)
            and _counts_like_cash(txn) and is_card_bill(txn.description)
        ]
        if not bills:
            warnings.append({
                "code": "card_bill_unknown",
                "month": month,
                "card_total": _money(card),
                "bill_total": None,
                "status": "unknown",
                "message_he": (
                    f"ב-{month} יש עסקאות כרטיס ({_money(card)}) ואין חיוב כרטיס מזוהה "
                    "בחשבון העובר ושב באותו חודש. ההשוואה לא ידועה והסכומים לא שונו."
                ),
            })
            cycles.append({
                "month": month, "card_total": _money(card), "bill_total": None,
                "status": "unknown", "tolerance": "0.01",
            })
            continue
        bill = sum((_q(txn.amount) for txn in bills), Decimal("0"))
        status = "ok" if _within_tolerance(card, bill) else "mismatch"
        if status == "mismatch":
            warnings.append({
                "code": "card_bill_mismatch",
                "month": month,
                "card_total": _money(card),
                "bill_total": _money(bill),
                "status": status,
                "message_he": (
                    f"ב-{month} סכום עסקאות הכרטיס {_money(card)} והחיוב בחשבון {_money(bill)} "
                    "חורגים מטווח של 1%. הסכומים לא שונו."
                ),
            })
        cycles.append({
            "month": month, "card_total": _money(card), "bill_total": _money(bill),
            "status": status, "tolerance": "0.01",
        })
    return warnings, cycles


def _suspected_warning(left: Txn, right: Txn, rule: str) -> dict:
    amount = _money(_q(left.amount))
    month = _month(left.transaction_date)
    if rule == "journal_vs_internet":
        message = (
            f"ב-{month} שתי תנועות שנרשמו בבנק על סכום {amount} — העברת יומן והעברה באינטרנט — "
            "נראות ככפילות. שתיהן נספרות עד אישור ב-dedupePairs."
        )
    elif rule == "duplicate_booked_reference":
        message = (
            f"ב-{month} שתי תנועות BOOKED על סכום {amount} חולקות אסמכתא. "
            "שתיהן נספרות עד אישור ב-dedupePairs."
        )
    else:
        message = (
            f"ב-{month} שתי תנועות BOOKED על סכום {amount} עם אותה טביעת תוכן "
            "בטווח של שלושה ימים. שתיהן נספרות עד אישור ב-dedupePairs."
        )
    return {"code": "suspected_pair", "rule": rule, "month": month, "amount": amount, "message_he": message}


def _pair_row(left: Txn, right: Txn, rule: str, disposition: str) -> dict:
    return {
        "organization_id": left.organization_id,
        "account_id": left.account_id,
        "month": _month(left.transaction_date),
        "left_id": left.id,
        "right_id": right.id,
        "amount": _money(_q(left.amount)),
        "left_date": left.transaction_date.isoformat(),
        "right_date": right.transaction_date.isoformat(),
        "left_status": left.status,
        "right_status": right.status,
        "left_description": left.description,
        "right_description": right.description,
        "entry_reference": left.entry_reference or right.entry_reference,
        "rule": rule,
        "disposition": disposition,
    }


def _counts_like_cash(txn: Txn) -> bool:
    if txn.source == OF_SOURCE:
        return txn.status == BOOKED
    return True


def _is_card_txn(txn: Txn, card_ids: set[int]) -> bool:
    return txn.is_card or (txn.account_id is not None and txn.account_id in card_ids)


def _coverage_keeps(db, organization_id: int, rows: list[BankTransaction]) -> list[BankTransaction]:
    from ..bank_coverage import (
        _classification_context,
        _decision,
        _org_has_reviewed_local_import,
    )
    if not rows or not _org_has_reviewed_local_import(db, organization_id):
        return rows
    context = _classification_context(db, organization_id)
    return [row for row in rows if _decision(row, context)[0]]


def _subtract_rows(months: list[dict], remove: list[Txn]) -> list[dict]:
    flows = [(txn.transaction_date, txn.amount) for txn in remove]
    cumulative = 0.0
    adjusted = []
    for month in months:
        year, mon = (int(part) for part in str(month["month"]).split("-"))
        m_start = date(year, mon, 1)
        m_end = _add_months(m_start, 1) - timedelta(days=1)
        inflow, outflow = _sum_flows(flows, m_start, m_end)
        copied = dict(month)
        copied["inflows"] = round(float(month.get("inflows") or 0) - inflow, 2)
        copied["outflows"] = round(float(month.get("outflows") or 0) - outflow, 2)
        net = round(copied["inflows"] - copied["outflows"], 2)
        cumulative = round(cumulative + net, 2)
        copied["net_flow"] = net
        copied["cumulative"] = cumulative
        adjusted.append(copied)
    return adjusted


def _window_start(months: list[dict]) -> date:
    first = min(str(item["month"]) for item in months)
    year, mon = (int(part) for part in first.split("-"))
    return date(year, mon, 1)


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _sum_flows(rows: list[tuple[date, Decimal]], start: date, end: date) -> tuple[float, float]:
    inflow = 0.0
    outflow = 0.0
    for tx_date, amount in rows:
        if not (start <= tx_date <= end):
            continue
        value = float(amount or 0)
        if value > 0:
            inflow += value
        elif value < 0:
            outflow += abs(value)
    return round(inflow, 2), round(outflow, 2)


def _within_tolerance(card: Decimal, bill: Decimal) -> bool:
    if bill == 0:
        return card == 0
    return abs(card - bill) / abs(bill) <= BILL_TOLERANCE


def _has_cal_word(text: str) -> bool:
    padded = f" {text} "
    return " cal " in padded


def _status(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().upper()
    return text or None


def _text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
        return number if number > 0 else None
    return None


def _q(amount: Decimal) -> Decimal:
    return Decimal(str(amount or 0)).quantize(Decimal("0.01"))


def _money(amount: Decimal) -> str:
    return format(_q(amount), "f")


def _month(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"
