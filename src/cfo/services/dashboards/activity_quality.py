"""View-layer quality for dashboard cash flow. Reads books; writes nothing.

Open Finance often stores a PENDING row and a later BOOKED copy. They share
``entryReference`` but not id, and the description can change. This module
decides which rows a dashboard may sum. It does not update ``superseded_by_id``
and it does not call a provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
import re

from ...models import BankTransaction, Category, ClientDashboard, DashboardPlan
from ..bank_coverage import cashflow_row_objects, content_fingerprint
from ..bank_status import card_account_ids

OF_SOURCE = "open_finance"
BOOKED = "BOOKED"
FUTURE_CHARGE_TEXT = "חיובים עתידיים"
PAIR_WINDOW_DAYS = 3
BILL_TOLERANCE = Decimal("0.01")
_CAL_WORD = re.compile(r"(?<![a-z])cal(?![a-z])")

EXCLUSION_KEYS = (
    "pending_superseded",
    "future_charge",
    "superseded_by_id",
    "non_booked",
    "detail_account",
    "confirmed_pair",
)


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
    category_name: str | None
    merchant_name: str | None


@dataclass
class Outcome:
    counted: list[Txn]
    detail: list[Txn]
    pairs: list[dict]
    notes: list[dict]
    warnings: list[dict]
    billing_cycles: list[dict]
    excluded_counts: dict[str, int]
    detail_enabled: bool

    def as_view(self) -> dict:
        detail = None
        if self.detail_enabled:
            detail = {
                "merchants": _buckets(self.detail, lambda txn: txn.merchant_name, "merchant", "לא ידוע"),
                "categories": _buckets(self.detail, lambda txn: txn.category_name, "category", "לא מסווג"),
            }
        return {
            "booked_only": True,
            "excluded_counts": self.excluded_counts,
            "notes": self.notes,
            "warnings": self.warnings,
            "billing_cycles": self.billing_cycles,
            "detail": detail,
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
    has_cal = "כאל" in text or "כ.א.ל" in text or _CAL_WORD.search(text) is not None
    has_charge = "חיוב" in text
    return (has_visa and has_cal) or (has_charge and (has_visa or has_cal))


def parse_id_list(value) -> tuple[set[int], bool]:
    """Return ids and whether the payload shape was invalid."""
    if value is None:
        return set(), False
    if not isinstance(value, list):
        return set(), True
    ids: set[int] = set()
    invalid = False
    for item in value:
        parsed = _as_int(item)
        if parsed is None:
            invalid = True
            continue
        ids.add(parsed)
    return ids, invalid


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


def parse_detail_account_ids(payload: dict | None) -> tuple[set[int], list[dict]]:
    if not payload or "detailAccountIds" not in payload:
        return set(), []
    ids, invalid = parse_id_list(payload.get("detailAccountIds"))
    if not invalid:
        return ids, []
    return ids, [{
        "code": "invalid_detail_accounts",
        "message_he": "detailAccountIds אינו רשימת מזהים תקינה — ערכים לא תקינים דולגו.",
    }]


def classify(
    txns: list[Txn],
    *,
    detail_account_ids: set[int] | None = None,
    confirmed_pairs: list[tuple[int, int]] | None = None,
) -> Outcome:
    detail_ids = set(detail_account_ids or ())
    confirmed = list(confirmed_pairs or ())
    by_id = {txn.id: txn for txn in txns}
    drop_ids: set[int] = set()
    missing_pairs = 0
    confirmed_rows: list[dict] = []
    for keep_id, drop_id in confirmed:
        keep = by_id.get(keep_id)
        drop = by_id.get(drop_id)
        if keep is None or drop is None:
            missing_pairs += 1
            continue
        drop_ids.add(drop_id)
        confirmed_rows.append(_pair_row(keep, drop, "confirmed", "confirmed"))

    links = _pending_links(txns)
    superseded_ids = {pending.id for pending, _booked, _rule in links}
    amount_diffs = sum(
        1 for pending, booked, rule in links
        if rule == "entry_reference" and _q(pending.amount) != _q(booked.amount)
    )

    suspected = []
    suspected.extend(_duplicate_booked_references(txns, drop_ids))
    suspected.extend(_duplicate_booked_fingerprints(txns, drop_ids))
    suspected.extend(_ambiguous_pending(txns, superseded_ids, drop_ids))

    counted: list[Txn] = []
    detail: list[Txn] = []
    counts = {key: 0 for key in EXCLUSION_KEYS}
    for txn in txns:
        reason = _reason(txn, drop_ids, superseded_ids, detail_ids)
        if reason == "counted":
            counted.append(txn)
        elif reason == "detail":
            detail.append(txn)
            counts["detail_account"] += 1
        else:
            counts[reason] += 1

    pairs = [_pair_row(pending, booked, rule, "excluded") for pending, booked, rule in links]
    pairs.extend(_pair_row(left, right, rule, "warning") for left, right, rule in suspected)
    pairs.extend(confirmed_rows)

    notes = _notes(counts, amount_diffs)
    warnings = [_suspected_warning(left, right, rule) for left, right, rule in suspected]
    if missing_pairs:
        warnings.append({
            "code": "unmatched_dedupe_pair",
            "message_he": (
                f"{missing_pairs} זוגות dedupePairs מפנים לתנועה שאינה בחלון, ולא הוחלו."
            ),
        })
    cycles: list[dict] = []
    if detail_ids:
        cycle_warnings, cycles = _billing_cycles(detail, counted)
        warnings.extend(cycle_warnings)
    return Outcome(
        counted=counted,
        detail=detail,
        pairs=pairs,
        notes=notes,
        warnings=warnings,
        billing_cycles=cycles,
        excluded_counts=counts,
        detail_enabled=bool(detail_ids),
    )


def adjust_cashflow(db, organization_id: int, cashflow: dict, plan_payload: dict | None) -> dict:
    """Attach quality notes and subtract only rows the cash-flow total already summed.

    BOOKED-only, future-charge, and card-account rules already live in the
    cash-flow read. This step does not rebuild those months. It removes an
    admin-confirmed duplicate and a payload detail account (not already a card
    account) from the existing inflows and outflows, then records warnings.
    """
    if not isinstance(cashflow, dict):
        return cashflow
    months = cashflow.get("months") or []
    if not months or "as_of" not in cashflow:
        return cashflow
    start = _window_start(months)
    end = date.fromisoformat(str(cashflow["as_of"]))
    detail_ids, detail_warnings = parse_detail_account_ids(plan_payload)
    confirmed, pair_warnings = parse_confirmed_pairs(plan_payload)
    card_ids = card_account_ids(db, organization_id)
    txns = load_txns(db, organization_id, start, end, respect_coverage=True)
    outcome = classify(
        txns,
        detail_account_ids=detail_ids | card_ids,
        confirmed_pairs=confirmed,
    )
    service_ids = {row.id for row in cashflow_row_objects(db, organization_id, start, end)}
    drop_ids = {drop_id for _keep_id, drop_id in confirmed}
    remove = [
        txn for txn in txns
        if txn.id in service_ids and (
            txn.id in drop_ids
            or txn.superseded_by_id is not None
            or (txn.account_id in detail_ids and txn.account_id not in card_ids)
        )
    ]
    updated = dict(cashflow)
    if remove:
        updated["months"] = _subtract_rows(months, remove)
    view = outcome.as_view()
    extra_detail = [
        txn for txn in outcome.detail
        if txn.account_id in detail_ids and txn.account_id not in card_ids
    ]
    if extra_detail:
        view["detail"] = {
            "merchants": _buckets(extra_detail, lambda txn: txn.merchant_name, "merchant", "לא ידוע"),
            "categories": _buckets(extra_detail, lambda txn: txn.category_name, "category", "לא מסווג"),
        }
    elif not detail_ids:
        view["detail"] = None
    view["warnings"] = detail_warnings + pair_warnings + view["warnings"]
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
    names = _category_names(db, rows)
    return [txn_from_row(row, names.get(row.category_id)) for row in rows]


def txn_from_row(row: BankTransaction, category_name: str | None) -> Txn:
    raw = row.raw_data if isinstance(row.raw_data, dict) else {}
    status = _status(raw.get("status"))
    reference = _text(raw.get("entryReference"))
    if reference is None:
        reference = _text(raw.get("entry_reference"))
    merchant = _text(raw.get("merchantName")) or _text(row.description)
    category = _text(category_name) or _category_from_raw(raw)
    stored = _text(row.content_fingerprint)
    fingerprint = stored or content_fingerprint(row.transaction_date, row.amount, row.description)
    return Txn(
        id=row.id,
        organization_id=row.organization_id,
        account_id=row.account_id,
        transaction_date=row.transaction_date,
        amount=row.amount if isinstance(row.amount, Decimal) else Decimal(str(row.amount or 0)),
        description=row.description,
        status=status,
        entry_reference=reference,
        content_fingerprint=fingerprint,
        superseded_by_id=row.superseded_by_id,
        source=row.source,
        category_name=category,
        merchant_name=merchant,
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
    """Suspected and auto-excluded pairs. Does not apply card netting."""
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
            detail_account_ids=set(),
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


def rebuild_months(months: list[dict], counted: list[Txn]) -> list[dict]:
    flows = [(txn.transaction_date, txn.amount) for txn in counted]
    cumulative = 0.0
    rebuilt = []
    for month in months:
        year, mon = (int(part) for part in str(month["month"]).split("-"))
        m_start = date(year, mon, 1)
        m_end = _add_months(m_start, 1) - timedelta(days=1)
        inflow, outflow = _sum_flows(flows, m_start, m_end)
        net = round(inflow - outflow, 2)
        cumulative = round(cumulative + net, 2)
        copied = dict(month)
        copied["inflows"] = inflow
        copied["outflows"] = outflow
        copied["net_flow"] = net
        copied["cumulative"] = cumulative
        rebuilt.append(copied)
    return rebuilt


def _pending_links(txns: list[Txn]) -> list[tuple[Txn, Txn, str]]:
    booked_by_ref: dict[tuple[int, str], list[Txn]] = {}
    booked_rows = []
    for txn in txns:
        if txn.status != BOOKED:
            continue
        booked_rows.append(txn)
        if txn.entry_reference and txn.account_id is not None:
            booked_by_ref.setdefault((txn.account_id, txn.entry_reference), []).append(txn)
    links = []
    for txn in sorted(txns, key=lambda item: (item.transaction_date, item.id)):
        if txn.source != OF_SOURCE or txn.status == BOOKED or txn.account_id is None:
            continue
        match = None
        rule = None
        if txn.entry_reference:
            candidates = booked_by_ref.get((txn.account_id, txn.entry_reference)) or []
            if candidates:
                match = min(candidates, key=lambda item: item.id)
                rule = "entry_reference"
        if match is None:
            match = _fallback_booked(txn, booked_rows)
            rule = "fingerprint" if match is not None else None
        if match is not None and rule is not None:
            links.append((txn, match, rule))
    return links


def _fallback_booked(pending: Txn, booked_rows: list[Txn]) -> Txn | None:
    best = None
    best_delta = None
    for booked in booked_rows:
        if booked.account_id != pending.account_id:
            continue
        if _q(booked.amount) != _q(pending.amount):
            continue
        if booked.content_fingerprint != pending.content_fingerprint:
            continue
        delta = abs((booked.transaction_date - pending.transaction_date).days)
        if delta > PAIR_WINDOW_DAYS:
            continue
        if best is None or delta < best_delta or (delta == best_delta and booked.id < best.id):
            best = booked
            best_delta = delta
    return best


def _duplicate_booked_references(txns: list[Txn], drop_ids: set[int]) -> list[tuple[Txn, Txn, str]]:
    groups: dict[tuple[int, str], list[Txn]] = {}
    for txn in txns:
        if txn.id in drop_ids or txn.status != BOOKED or txn.superseded_by_id is not None:
            continue
        if txn.account_id is None or not txn.entry_reference:
            continue
        groups.setdefault((txn.account_id, txn.entry_reference), []).append(txn)
    return _keeper_pairs(groups, "duplicate_booked_reference")


def _duplicate_booked_fingerprints(txns: list[Txn], drop_ids: set[int]) -> list[tuple[Txn, Txn, str]]:
    grouped_refs = {
        (left.account_id, left.entry_reference)
        for left, _right, rule in _duplicate_booked_references(txns, drop_ids)
        if rule == "duplicate_booked_reference" and left.entry_reference
    }
    groups: dict[tuple[int, str, Decimal], list[Txn]] = {}
    for txn in txns:
        if txn.id in drop_ids or txn.status != BOOKED or txn.superseded_by_id is not None:
            continue
        if txn.account_id is None or not txn.content_fingerprint:
            continue
        if txn.entry_reference and (txn.account_id, txn.entry_reference) in grouped_refs:
            continue
        groups.setdefault((txn.account_id, txn.content_fingerprint, _q(txn.amount)), []).append(txn)
    pairs = []
    for group in groups.values():
        ordered = sorted(group, key=lambda txn: (txn.transaction_date, txn.id))
        used: set[int] = set()
        for index, left in enumerate(ordered):
            if left.id in used:
                continue
            for right in ordered[index + 1:]:
                if right.id in used:
                    continue
                if abs((right.transaction_date - left.transaction_date).days) > PAIR_WINDOW_DAYS:
                    continue
                used.add(right.id)
                pairs.append((left, right, "duplicate_booked_fingerprint"))
                break
    return pairs


def _ambiguous_pending(txns: list[Txn], superseded_ids: set[int], drop_ids: set[int]):
    pendings = [
        txn for txn in txns
        if txn.source == OF_SOURCE and txn.status == "PENDING" and txn.id not in superseded_ids
        and txn.id not in drop_ids and txn.account_id is not None
        and not is_future_charge(txn.description)
    ]
    booked_rows = [
        txn for txn in txns
        if txn.status == BOOKED and txn.superseded_by_id is None and txn.id not in drop_ids
        and txn.account_id is not None
    ]
    pairs = []
    for pending in pendings:
        match = None
        best_delta = None
        for booked in booked_rows:
            if booked.account_id != pending.account_id:
                continue
            if _q(booked.amount) != _q(pending.amount):
                continue
            delta = abs((booked.transaction_date - pending.transaction_date).days)
            if delta > PAIR_WINDOW_DAYS:
                continue
            if pending.entry_reference and pending.entry_reference == booked.entry_reference:
                continue
            if pending.content_fingerprint == booked.content_fingerprint:
                continue
            if best_delta is None or delta < best_delta or (delta == best_delta and booked.id < match.id):
                match = booked
                best_delta = delta
        if match is not None:
            pairs.append((match, pending, "ambiguous_pending"))
    return pairs


def _reason(txn: Txn, drop_ids: set[int], superseded_ids: set[int], detail_ids: set[int]) -> str:
    if txn.id in drop_ids:
        return "confirmed_pair"
    if txn.superseded_by_id is not None:
        return "superseded_by_id"
    if txn.id in superseded_ids:
        return "pending_superseded"
    if txn.source == OF_SOURCE and txn.status != BOOKED and is_future_charge(txn.description):
        return "future_charge"
    if txn.source == OF_SOURCE and txn.status != BOOKED:
        return "non_booked"
    if txn.account_id in detail_ids:
        return "detail"
    return "counted"


def _billing_cycles(detail: list[Txn], counted: list[Txn]) -> tuple[list[dict], list[dict]]:
    by_month: dict[str, list[Txn]] = {}
    for txn in detail:
        by_month.setdefault(_month(txn.transaction_date), []).append(txn)
    warnings = []
    cycles = []
    for month in sorted(by_month):
        card = sum((_q(txn.amount) for txn in by_month[month]), Decimal("0"))
        bills = [
            txn for txn in counted
            if _month(txn.transaction_date) == month and is_card_bill(txn.description)
        ]
        if not bills:
            warnings.append({
                "code": "card_bill_unknown",
                "month": month,
                "card_total": _money(card),
                "bill_total": None,
                "status": "unknown",
                "message_he": (
                    f"ב-{month} יש עסקאות בחשבון פירוט ({_money(card)}) ואין חיוב כרטיס "
                    "מזוהה בחשבון העובר ושב באותו חודש. ההשוואה לא ידועה והסכומים לא שונו."
                ),
            })
            cycles.append({
                "month": month,
                "card_total": _money(card),
                "bill_total": None,
                "status": "unknown",
                "tolerance": "0.01",
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
            "month": month,
            "card_total": _money(card),
            "bill_total": _money(bill),
            "status": status,
            "tolerance": "0.01",
        })
    return warnings, cycles


def _notes(counts: dict[str, int], amount_diffs: int) -> list[dict]:
    notes = []
    if counts["pending_superseded"]:
        notes.append({"message_he": (
            f"{counts['pending_superseded']} תנועות ממתינות הוחלפו בתנועה סגורה (BOOKED) "
            "עם אותו חשבון ואסמכתא או טביעת תוכן, ולא נספרו בתזרים."
        )})
    if amount_diffs:
        notes.append({"message_he": (
            f"{amount_diffs} זוגות PENDING ו-BOOKED עם אותה אסמכתא נבדלים בסכום. "
            "נספר הסכום הסגור בלבד."
        )})
    if counts["future_charge"]:
        notes.append({"message_he": (
            f"{counts['future_charge']} שורות חיוב עתידי לא נספרו בתזרים."
        )})
    if counts["non_booked"]:
        notes.append({"message_he": (
            f"{counts['non_booked']} תנועות Open Finance שאינן BOOKED לא נספרו."
        )})
    if counts["superseded_by_id"]:
        notes.append({"message_he": (
            f"{counts['superseded_by_id']} תנועות שסומנו כבר ככפולות לא נספרו."
        )})
    if counts["confirmed_pair"]:
        notes.append({"message_he": (
            f"{counts['confirmed_pair']} תנועות הוסרו לפי זוגות כפילות שאושרו בתוכנית הדשבורד."
        )})
    if counts["detail_account"]:
        notes.append({"message_he": (
            f"{counts['detail_account']} תנועות מחשבונות פירוט לא נכנסו לסיכום התזרים "
            "ומופיעות רק בפירוט בתי העסק."
        )})
    return notes


def _suspected_warning(left: Txn, right: Txn, rule: str) -> dict:
    amount = _money(_q(left.amount))
    month = _month(left.transaction_date)
    if rule == "ambiguous_pending":
        message = (
            f"ב-{month} יש תנועה ממתינה ותנועה סגורה על סכום {amount} בטווח של שלושה ימים, "
            "בלי אסמכתא זהה ובלי טביעת תוכן זהה. התנועה הממתינה לא נספרה כי היא אינה BOOKED. "
            "התנועה הסגורה נספרה. הזוג לא הוסר ככפילות."
        )
    else:
        why = "אותה אסמכתא" if rule == "duplicate_booked_reference" else "אותה טביעת תוכן"
        message = (
            f"ב-{month} שתי תנועות BOOKED על סכום {amount} נראות ככפילות ({why}). "
            "שתיהן נספרות עד אישור ב-dedupePairs."
        )
    return {
        "code": "suspected_pair",
        "rule": rule,
        "month": month,
        "amount": amount,
        "message_he": message,
    }


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


def _keeper_pairs(groups: dict, rule: str) -> list[tuple[Txn, Txn, str]]:
    pairs = []
    for group in groups.values():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda txn: txn.id)
        keeper = ordered[0]
        for other in ordered[1:]:
            pairs.append((keeper, other, rule))
    return pairs


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


def _category_names(db, rows: list[BankTransaction]) -> dict[int, str]:
    ids = {row.category_id for row in rows if row.category_id}
    if not ids:
        return {}
    return {
        row.id: row.name
        for row in db.query(Category).filter(Category.id.in_(ids)).all()
    }


def _buckets(rows: list[Txn], keyfn, field: str, missing: str) -> list[dict]:
    groups: dict[str, list[Txn]] = {}
    for txn in rows:
        groups.setdefault(keyfn(txn) or missing, []).append(txn)
    items = []
    for name, grouped in groups.items():
        amounts = [_q(txn.amount) for txn in grouped]
        inflow = sum((amount for amount in amounts if amount > 0), Decimal("0"))
        outflow = sum((-amount for amount in amounts if amount < 0), Decimal("0"))
        net = sum(amounts, Decimal("0"))
        items.append({
            field: name,
            "inflows": _money(inflow),
            "outflows": _money(outflow),
            "net": _money(net),
            "count": len(grouped),
        })
    items.sort(key=lambda item: (Decimal(item["net"]), item[field]))
    return items


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


def _category_from_raw(raw: dict) -> str | None:
    category = raw.get("category")
    if isinstance(category, dict):
        return _text(category.get("main"))
    return _text(category)


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
