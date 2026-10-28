"""Per-entity and combined views for a dashboard that covers more than one organization.

``build_view`` stays the single-organization reader. This module calls it once
per ``dashboard_entities`` row and adds the pieces together. A viewer still has
to be allowed onto the dashboard by the route. Every entity on a multi-entity
dashboard must belong to the same office. No provider calls.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from ...models import BankTransaction, ClientDashboard, DashboardEntity, DashboardEntityAccount
from .. import bank_status
from ..office_access import classifying_office_id, office_manages
from ..read_memo import read_memo
from .service import DashboardError
from . import books_pnl, cash_forecast, cash_statement, filing, forecast, liquidity, view_model

_MARKER = ("intercompany", "בין-חברתי", "בין חברתי")
# The explicit intercompany rule (see ``_intercompany``).
IC_CATEGORIES = frozenset({"intercompany", "transfers_out", "other_in", "bank_journal"})
IC_TOLERANCE = Decimal("0.01")
IC_WINDOW_DAYS = 4
IC_MAX_WINDOW_DAYS = 10
IC_MAX_ITEMS = 200
IC_RULE_HE = (
    "קיזוז בין-חברתי: יציאה בישות אחת מול כניסה בישות אחרת, באותו סכום (±0.01 ₪), "
    "עד {days} ימים זה מזה. שתי התנועות מתויקות כהעברה (בין-חברתי, העברה יוצאת, תקבול לבירור, "
    "זיכוי יומן) ולא כמכירה, ספק או עמלה. כל תנועה מקוזזת פעם אחת."
)
_PNL_FIELDS = ("total_revenue", "total_expenses", "net_income_before_tax")


def assert_same_office(db, dashboard: ClientDashboard, entities: list) -> int | None:
    """The office shared by every entity. One entity is always the same office."""
    if len(entities) <= 1:
        return dashboard.office_organization_id
    office_id = dashboard.office_organization_id
    if office_id is None:
        inferred = [classifying_office_id(db, entity.organization_id) for entity in entities]
        if any(item is None for item in inferred) or len(set(inferred)) != 1:
            raise DashboardError(
                422, "entity_office_mismatch", "ישות בדשבורד אינה שייכת לאותו משרד",
            )
        return inferred[0]
    for entity in entities:
        if entity.organization_id == office_id:
            continue
        if not office_manages(db, office_id, entity.organization_id):
            raise DashboardError(
                422, "entity_office_mismatch", "ישות בדשבורד אינה שייכת לאותו משרד",
            )
    return office_id


def build_dashboard_view(db, dashboard: ClientDashboard, start: date, end: date,
                         *, plan: dict | None = None) -> dict:
    """Every entity reads the dashboard plan. Filing decisions and rules carry their
    own ``organizationId``. ``booksClosedMonths`` has no organization, so only the
    primary organization treats those months as closed.

    The build only reads, so the bank rows, card accounts and coverage each entity's
    sections share are read once (``read_memo``)."""
    with read_memo(db):
        return _build_dashboard_view(db, dashboard, start, end, plan=plan)


def _build_dashboard_view(db, dashboard: ClientDashboard, start: date, end: date,
                          *, plan: dict | None = None) -> dict:
    entities = (
        db.query(DashboardEntity)
        .filter_by(dashboard_id=dashboard.id)
        .order_by(DashboardEntity.id)
        .all()
    )
    if not entities:
        entities = [_Primary(dashboard)]
    office_id = assert_same_office(db, dashboard, entities)
    ordered = sorted(entities, key=lambda entity: (entity.role != "primary", entity.id or 0))
    # The plan's budget lines name no entity: with more than one entity they are the
    # group's budget, and only the combined view uses them. One entity alone with the
    # whole group's costs projected that one company far below its real trend.
    single = len(ordered) == 1
    sections = []
    for entity in ordered:
        is_primary = entity.organization_id == dashboard.primary_organization_id
        section_view = view_model.build_view(
            db, entity.organization_id, start, end,
            plan=_plan_for(plan, is_primary),
            entity_id=getattr(entity, "id", None) or None,
            with_budget=single and is_primary,
        )
        section_view["cash_forecast"]["label"] = entity.label
        sections.append({
            "organization_id": entity.organization_id,
            "label": entity.label,
            "role": entity.role,
            "accounts": _accounts(db, entity),
            "view": section_view,
        })
    primary = next(
        (section["view"] for section in sections if section["role"] == "primary"),
        sections[0]["view"],
    )
    combined = _combine(db, sections, start, end, plan=plan)
    view = dict(primary)
    view["entities"] = sections
    view["combined"] = combined
    view["office_organization_id"] = office_id
    view["provider_calls"] = 0
    return view


def _plan_for(plan: dict | None, primary: bool) -> dict | None:
    if primary or not isinstance(plan, dict):
        return plan
    return {key: value for key, value in plan.items() if key != "booksClosedMonths"}


class _Primary:
    def __init__(self, dashboard: ClientDashboard):
        self.id = 0
        self.organization_id = dashboard.primary_organization_id
        self.label = dashboard.title
        self.role = "primary"


def _accounts(db, entity) -> list[dict]:
    if not getattr(entity, "id", None):
        return []
    rows = db.query(DashboardEntityAccount).filter_by(entity_id=entity.id).all()
    return [
        {"account_id": row.account_id, "display_label": row.display_label}
        for row in rows
    ]


SHARED_NOTE = "חשבון בנק אחד רשום ביותר מישות אחת. במאוחד הוא נספר פעם אחת."
BALANCE_CONFLICT_NOTE = "אותו חשבון רשום ביותר מישות והיתרות אינן זהות, ולכן היתרה המאוחדת לא ידועה."
FLOW_CONFLICT_NOTE = "אותו חשבון רשום ביותר מישות והתנועות אינן זהות, ולכן התזרים המאוחד לא ידוע."


def _shared_groups(db, sections: list[dict]) -> tuple[list[dict], set[int]]:
    """Copies of one bank account in more than one organization of this dashboard.

    The keeper is the primary entity's copy. A missing or short account number
    is not an identity, so those accounts are never folded together.
    """
    from ...models import Account
    org_ids = [section["organization_id"] for section in sections]
    if len(org_ids) < 2:
        return [], set()
    primary = next(
        (section["organization_id"] for section in sections if section.get("role") == "primary"),
        org_ids[0],
    )
    accounts = db.query(Account).filter(Account.organization_id.in_(org_ids)).all()
    by: dict[str, list] = {}
    for account in accounts:
        ident = liquidity.account_identity(account)
        if not ident:
            continue
        by.setdefault(ident, []).append(account)
    groups = []
    drop: set[int] = set()
    for ident, group in by.items():
        if len({account.organization_id for account in group}) < 2:
            continue
        keeper = min(group, key=lambda account: (
            0 if account.organization_id == primary else 1,
            account.organization_id or 0,
            account.id or 0,
        ))
        drops = [account.id for account in group if account.id != keeper.id]
        drop.update(drops)
        groups.append({"identity": ident, "keeper": keeper, "accounts": group, "drop_ids": drops})
    return groups, drop


def _flow_signature(rows) -> dict[str, tuple[float, float]]:
    sig: dict[str, list[float]] = {}
    for row in rows:
        month = row.transaction_date.strftime("%Y-%m")
        slot = sig.setdefault(month, [0.0, 0.0])
        amount = float(row.amount or 0)
        if amount > 0:
            slot[0] += amount
        elif amount < 0:
            slot[1] += -amount
    return {month: (round(pair[0], 2), round(pair[1], 2)) for month, pair in sig.items()}


def _rows_on_accounts(db, start: date, end: date, account_ids: set[int]) -> list:
    from ..bank_coverage import cashflow_row_objects
    if not account_ids:
        return []
    org_ids = {row.organization_id for row in db.query(BankTransaction.organization_id).filter(
        BankTransaction.account_id.in_(account_ids)
    ).distinct()}
    found = []
    for org_id in org_ids:
        for row in cashflow_row_objects(db, org_id, start, end):
            if row.account_id in account_ids:
                found.append(row)
    return found


def _collapse_values(rows: list[dict], value_key: str) -> tuple[list[float], str]:
    """One value per bank_key. ``conflict`` when known copies disagree, ``unknown`` when none are known."""
    grouped: dict[str, list] = {}
    order: list[str] = []
    loose = []
    for row in rows:
        key = row.get("bank_key")
        if not key:
            loose.append(row)
            continue
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(row)
    state = "ok"
    values: list[float] = []

    def take(group: list[dict]) -> None:
        nonlocal state
        known = [item.get(value_key) for item in group if item.get(value_key) is not None]
        distinct = {round(float(value), 2) for value in known}
        if len(distinct) > 1:
            state = "conflict"
            return
        if not known:
            if state != "conflict":
                state = "unknown"
            return
        values.append(float(known[0]))

    for row in loose:
        take([row])
    for key in order:
        take(grouped[key])
    return values, state


def _shared_view_keys(sections: list[dict]) -> set[str]:
    seen: dict[str, str] = {}
    shared: set[str] = set()
    for section in sections:
        label = section.get("label") or ""
        liquidity_view = (section.get("view") or {}).get("liquidity") or {}
        rows = [
            *(liquidity_view.get("accounts") or []),
            *(liquidity_view.get("cards") or []),
            *(liquidity_view.get("loans") or []),
        ]
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = row.get("bank_key")
            if not key:
                continue
            previous = seen.get(key)
            if previous is not None and previous != label:
                shared.add(key)
            else:
                seen.setdefault(key, label)
    return shared


def _apply_shared_liquidity(position: dict, sections: list[dict]) -> dict:
    if not _shared_view_keys(sections):
        return position
    checking, cards, loans = [], [], []
    for section in sections:
        label = section.get("label")
        liquidity_view = (section.get("view") or {}).get("liquidity") or {}
        for row in liquidity_view.get("accounts") or []:
            if isinstance(row, dict) and row.get("kind") == "checking":
                checking.append({**row, "entity": label})
        for row in liquidity_view.get("cards") or []:
            if isinstance(row, dict):
                cards.append({**row, "entity": label})
        for row in liquidity_view.get("loans") or []:
            if isinstance(row, dict) and not liquidity.is_check_discounting(row.get("name")):
                loans.append({**row, "entity": label})
    balances, balance_state = _collapse_values(checking, "balance")
    limits, limit_state = _collapse_values(checking, "credit_limit")
    card_balances, card_state = _collapse_values(cards, "balance")
    position = dict(position)
    notes = [SHARED_NOTE]
    if balance_state == "conflict" or limit_state == "conflict":
        notes.append(BALANCE_CONFLICT_NOTE)
    balance = None if balance_state != "ok" else (liquidity._r(sum(balances)) if balances else None)
    limit = None if limit_state != "ok" else (liquidity._r(sum(limits)) if limits else None)
    if checking and balance_state == "ok" and not balances:
        balance = None
    position["balance"] = balance if checking else position.get("balance")
    if checking:
        position["balance_known"] = position["balance"]
    if checking:
        position["limit"] = limit
        position["limit_known"] = limit
        position["available_to_limit"] = None if position["balance"] is None or limit is None else liquidity._r(limit + position["balance"])
    kept_cards = []
    seen = set()
    for card in cards:
        key = card.get("bank_key")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        kept_cards.append(card)
    if card_state == "conflict":
        for card in kept_cards:
            if card.get("bank_key"):
                card["balance"] = None
                card["date_note"] = BALANCE_CONFLICT_NOTE
    position["cards"] = kept_cards
    position["card_summary"] = liquidity.card_summary(kept_cards)
    kept_loans = []
    seen_loans = set()
    for loan in loans:
        key = loan.get("bank_key")
        if key and key in seen_loans:
            continue
        if key:
            seen_loans.add(key)
        kept_loans.append(loan)
    position["loans"] = kept_loans
    debts = []
    if checking:
        if position["balance"] is None:
            overdraft = None
        else:
            overdraft = liquidity._r(-position["balance"]) if position["balance"] < 0 else 0.0
        debts.append({"label": "מינוס בעו״ש", "amount": overdraft, "entity": "מאוחד", "as_of": position.get("as_of"),
                      "note": SHARED_NOTE})
    elif position.get("debts"):
        debts.extend(debt for debt in position["debts"] if debt.get("label") == "מינוס בעו״ש")
    if cards:
        if card_state == "ok":
            card_amount = liquidity._r(sum(card_balances)) if card_balances else 0.0
        else:
            card_amount = None
        debts.append({"label": "כרטיסי אשראי", "amount": card_amount, "entity": "מאוחד", "note": SHARED_NOTE})
    for loan in kept_loans:
        debts.append({
            "label": f"הלוואה — {loan.get('name')}", "amount": loan.get("balance"),
            "entity": loan.get("entity"), "as_of": loan.get("as_of"), "note": SHARED_NOTE if loan.get("bank_key") else None,
        })
    if debts:
        position["debts"] = debts
        position["debts_known_total"] = liquidity._sum_or_none(debt.get("amount") for debt in debts)
        position["debts_complete"] = all(debt.get("amount") is not None for debt in debts)
    position["shared_identity_note"] = " ".join(notes)
    if card_state == "conflict" or any(card.get("bank_key") for card in cards):
        # The summed activity counted each shared card once per entity. Do not show that number.
        if any(card.get("bank_key") in _shared_view_keys(sections) for card in cards):
            position["card_activity"] = {
                "key": "cards", "label": "עסקאות כרטיסי אשראי", "defined": False,
                "amount": None, "count": None, "counts_as_debt": False, "counts_as_balance": False,
                "definition": "אותו כרטיס רשום ביותר מישות. הסכום המאוחד אינו מוצג, כדי לא לספור את העסקאות פעמיים.",
            }
    return position


def _subtract_duplicate_flows(cashflow: dict, rows) -> dict:
    if not isinstance(cashflow, dict) or cashflow.get("status") != "ready" or not rows:
        return cashflow
    extra: dict[str, dict] = {}
    for row in rows:
        month = row.transaction_date.strftime("%Y-%m")
        slot = extra.setdefault(month, {"inflows": 0.0, "outflows": 0.0})
        amount = float(row.amount or 0)
        if amount > 0:
            slot["inflows"] += amount
        elif amount < 0:
            slot["outflows"] += -amount
    cumulative = 0.0
    months = []
    for month in cashflow.get("months") or []:
        if month.get("inflows") is None:
            months.append(month)
            continue
        cut = extra.get(month["month"], {"inflows": 0.0, "outflows": 0.0})
        inflows = round(float(month["inflows"]) - cut["inflows"], 2)
        outflows = round(float(month["outflows"]) - cut["outflows"], 2)
        if inflows < -0.001 or outflows < -0.001:
            return {
                "status": "unknown", "months": [],
                "message": "קיזוז חשבון משותף חרג מהתזרים המאוחד — המשולב לא מוצג.",
            }
        net = round(inflows - outflows, 2)
        cumulative = round(cumulative + net, 2)
        months.append({**month, "inflows": inflows, "outflows": outflows, "net_flow": net, "cumulative": cumulative})
    copied = dict(cashflow)
    copied["months"] = months
    return copied


def _apply_shared_identity(db, result: dict, sections: list[dict], groups: list[dict], start: date, end: date) -> dict:
    if not groups:
        return result
    from .books import cash_basis_month
    result = dict(result)
    conflict = False
    drop_rows = []
    for group in groups:
        keeper_rows = _rows_on_accounts(db, start, end, {group["keeper"].id})
        for account in group["accounts"]:
            if account.id == group["keeper"].id:
                continue
            rows = _rows_on_accounts(db, start, end, {account.id})
            if _flow_signature(rows) != _flow_signature(keeper_rows):
                conflict = True
            drop_rows.extend(rows)
    if conflict:
        result["cashflow"] = {"status": "unknown", "months": [], "message": FLOW_CONFLICT_NOTE}
        statement = dict(result.get("cash_statement") or {})
        statement["status"] = "unknown"
        statement["message"] = FLOW_CONFLICT_NOTE
        result["cash_statement"] = statement
        note = result["liquidity"].get("shared_identity_note")
        result["liquidity"]["shared_identity_note"] = f"{note} {FLOW_CONFLICT_NOTE}".strip() if note else FLOW_CONFLICT_NOTE
        return _mask_shared_forecast(result, groups)
    result["cashflow"] = _subtract_duplicate_flows(result.get("cashflow") or {}, drop_rows)
    pairs = []
    for row in drop_rows:
        txn = filing.txn_from_row(row)
        pairs.append((txn, filing.classify(txn)))
    if pairs:
        result["cash_statement"] = cash_statement.subtract_filed(result.get("cash_statement") or {}, pairs)
        position = result.get("liquidity")
        if isinstance(position, dict):
            position["debt_service"] = _subtract_debt_service(position.get("debt_service") or [], pairs)
    pnl = result.get("pnl") or {}
    bases = {section["organization_id"]: (section["view"].get("pnl") or {}).get("basis") for section in sections}
    if pnl.get("status") == "ready" and pnl.get("total_revenue") is not None and pnl.get("total_expenses") is not None and pairs:
        eligible = True
        for group in groups:
            if bases.get(group["keeper"].organization_id) != "cash_basis":
                eligible = False
            if any(bases.get(account.organization_id) != "cash_basis" for account in group["accounts"]):
                eligible = False
        if eligible:
            impact = cash_basis_month(pairs)
            revenue = round(float(pnl["total_revenue"]) - impact["revenue"], 2)
            costs = round(float(pnl["total_expenses"]) - impact["costs"], 2)
            pnl = dict(pnl)
            pnl["total_revenue"] = revenue
            pnl["total_expenses"] = costs
            pnl["net_income_before_tax"] = round(revenue - costs, 2)
            result["pnl"] = pnl
    return _mask_shared_forecast(result, groups)


def _subtract_debt_service(rows: list[dict], pairs) -> list[dict]:
    extra: dict[str, dict] = {}
    for txn, filed in pairs:
        month = str(getattr(txn, "date", ""))[:7]
        slot = extra.setdefault(month, {"principal": 0.0, "interest": 0.0, "new_loans": 0.0})
        amount = float(txn.amount)
        if filed.category == "loans_out":
            slot["principal"] += abs(amount)
        elif filed.category == "interest":
            slot["interest"] += abs(amount)
        elif filed.category == "loans_in":
            slot["new_loans"] += amount
    if not extra:
        return rows
    out = []
    for row in rows:
        cut = extra.get(row.get("month") or "")
        if not cut:
            out.append(row)
            continue
        out.append({
            "month": row["month"],
            "principal": round(float(row.get("principal") or 0) - cut["principal"], 2),
            "interest": round(float(row.get("interest") or 0) - cut["interest"], 2),
            "new_loans": round(float(row.get("new_loans") or 0) - cut["new_loans"], 2),
        })
    return out


def _mask_shared_forecast(result: dict, groups: list[dict]) -> dict:
    """The 13-week combine adds each entity. A shared checking account would be in both.

    Liquidity and the monthly cash flow already count it once. The weekly numbers
    are left unknown rather than shown doubled.
    """
    checking = [group for group in groups if liquidity._account_kind(group["keeper"]) == "checking"]
    forecast = result.get("cash_forecast")
    if not checking or not isinstance(forecast, dict):
        return result
    note = (
        "חשבון עו״ש אחד רשום ביותר מישות. יתרת הנזילות והתזרים החודשי סופרים אותו פעם אחת. "
        "התחזית השבועית המאוחדת אינה מוצגת כמספר, כי היא נבנית מכל ישות בנפרד."
    )
    weeks = []
    for week in forecast.get("weeks") or []:
        if isinstance(week, dict):
            weeks.append({**week, "in": None, "out": None, "net": None, "closing": None, "limit": None, "headroom": None})
    position = result.get("liquidity") or {}
    result["cash_forecast"] = {
        **forecast,
        "weeks": weeks,
        "opening": {"amount": position.get("balance"), "as_of": position.get("as_of")},
        "first_breach": None,
        "shared_identity_note": note,
    }
    return result


def _uncombined_balance_sheet() -> dict:
    """Balance sheets are stocks. Adding them across entities double-counts shared accounts."""
    from .balance_sheet import unknown_balance_sheet
    return unknown_balance_sheet("המאזן מוצג לכל ישות בנפרד. החיבור המאוחד אינו מחבר מאזנים.")


def _combine(db, sections: list[dict], start: date, end: date, *, plan: dict | None = None) -> dict:
    views = [section["view"] for section in sections]
    org_ids = [section["organization_id"] for section in sections]
    labels = {section["organization_id"]: section["label"] for section in sections}
    groups, drop_ids = _shared_groups(db, sections)
    removed = _intercompany(db, org_ids, start, end, plan=plan, labels=labels, drop_ids=drop_ids)
    removed["summary"]["rule"] = IC_RULE_HE.format(days=removed["summary"]["window_days"])
    position = liquidity.combine([
        {"label": section["label"], "liquidity": section["view"].get("liquidity")} for section in sections
    ])
    position = _apply_shared_liquidity(position, sections)
    # The plan budget is the group's budget, so the combined forecast uses all of it.
    outlook = forecast.build_forecast(
        forecast.combined_pnl_months(sections), as_of=end, plan=plan,
        debt_service=position["debt_service"], budget_sums=view_model.plan_budget_sums(plan),
        opening_balance=position["balance"],
    )
    combined = {
        "pnl": _combine_pnl(views),
        "books_pnl": books_pnl.combine_books([view.get("books_pnl") or {} for view in views]),
        "cashflow": _combine_cashflow(sections, removed),
        "budget_vs_actual": _combine_budget(views),
        "liquidity": position,
        "forecast": outlook,
        "cash_forecast": cash_forecast.combine([section["view"]["cash_forecast"] for section in sections]),
        "cash_statement": cash_statement.combine(sections, outlook, removed["by_month"]),
        "intercompany_removed": removed["summary"],
        "sources": _combine_sources(sections),
        "balance_sheet": _uncombined_balance_sheet(),
        "provider_calls": 0,
    }
    return _apply_shared_identity(db, combined, sections, groups, start, end)


def _combine_sources(sections: list[dict]) -> dict:
    """Every entity's sources in one table, each row naming its entity."""
    items = []
    rule = None
    for section in sections:
        own = (section["view"] or {}).get("sources") or {}
        rule = rule or own.get("rule")
        items.extend({**item, "entity": section["label"]} for item in own.get("items") or [])
    return {
        "status": "ready" if items else "unknown",
        "items": items,
        "stale_count": sum(1 for item in items if item.get("status") == "stale"),
        "aging_count": sum(1 for item in items if item.get("status") == "aging"),
        "rule": rule,
        "provider_calls": 0,
    }


def _combine_pnl(views: list[dict]) -> dict:
    parts = [view.get("pnl") or {} for view in views]
    unknown = {
        "status": "unknown",
        "basis": "unknown",
        "total_revenue": None,
        "total_expenses": None,
        "net_income_before_tax": None,
        "tax_expense": None,
        "message": "רווח והפסד משולב לא ידוע — לא לכל ישות יש ספרים בתקופה.",
    }
    if any(part.get("status") != "ready" for part in parts):
        return unknown
    totals = {}
    for field in _PNL_FIELDS:
        values = [part.get(field) for part in parts]
        if any(value is None for value in values):
            return unknown
        totals[field] = round(sum(float(value) for value in values), 2)
    bases = {part.get("basis") for part in parts}
    totals.update({
        "status": "ready",
        "basis": bases.pop() if len(bases) == 1 else "mixed",
        "tax_expense": None,
        "message": "סכום הרווח וההפסד של ישויות הדשבורד (כל ישות לפי המקור שלה בכל חודש). מס לא חושב.",
    })
    return totals


def _combine_cashflow(sections: list[dict], removed: dict) -> dict:
    """Each month labels which entities it sums (``scope_label``): a month only the chef
    has bank rows in is the chef's alone, and a month no entity has rows in is unknown,
    not the zeros a single entity's cash flow fills in."""
    views = [section["view"] for section in sections]
    labels = [section["label"] for section in sections]
    slots: dict[str, dict] = {}
    reported = 0
    for view in views:
        months = (view.get("cashflow") or {}).get("months") or []
        if not months:
            continue
        reported += 1
        for month in months:
            slot = slots.setdefault(month["month"], {"inflows": 0.0, "outflows": 0.0})
            slot["inflows"] += float(month.get("inflows") or 0)
            slot["outflows"] += float(month.get("outflows") or 0)
    if reported == 0:
        return {
            "status": "unknown",
            "months": [],
            "message": "אין תנועות בנק בישויות הדשבורד בחלון הזה.",
        }
    known_by = cash_statement.known_entities(sections, sorted(slots))
    scope = cash_statement.scope_of(known_by, labels)
    with_statement = any((view.get("cash_statement") or {}).get("months") for view in views)
    cumulative = 0.0
    months_out = []
    for month in sorted(slots):
        if with_statement and not known_by[month]:
            months_out.append({
                "month": month, "inflows": None, "outflows": None, "net_flow": None,
                "cumulative": cumulative, "scope_label": "אין תנועות בנק",
            })
            continue
        cut = removed["by_month"].get(month, {"inflows": 0.0, "outflows": 0.0})
        inflows = round(slots[month]["inflows"] - cut["inflows"], 2)
        outflows = round(slots[month]["outflows"] - cut["outflows"], 2)
        if inflows < -0.001 or outflows < -0.001:
            return {
                "status": "unknown",
                "months": [],
                "message": "קיזוז בין-חברתי חרג מסכום התזרים — המשולב לא מוצג.",
            }
        net = round(inflows - outflows, 2)
        cumulative = round(cumulative + net, 2)
        months_out.append({
            "month": month,
            "inflows": inflows,
            "outflows": outflows,
            "net_flow": net,
            "cumulative": cumulative,
            "scope_label": scope[month]["label"] if month in scope else None,
        })
    return {"status": "ready", "months": months_out, "message": None}


def _combine_budget(views: list[dict]) -> dict:
    sections = [view.get("budget_vs_actual") or {} for view in views]
    if any(section.get("status") != "ready" for section in sections):
        return {
            "status": "unknown",
            "has_budget": any(bool(section.get("has_budget")) for section in sections),
            "months": [],
            "message": "ביצוע משולב לא ידוע — לא לכל ישות יש ספרים בתקופה.",
        }
    index: dict[str, dict] = {}
    meta: dict[str, dict] = {}
    for section in sections:
        for month in section.get("months") or []:
            key = month.get("month")
            slot_meta = meta.setdefault(key, {
                "period_start": month.get("period_start"),
                "period_end": month.get("period_end"),
                "sources": set(),
                "labels": [],
                "blocked": False,
            })
            if month.get("source"):
                slot_meta["sources"].add(month["source"])
            if month.get("source_label") and month["source_label"] not in slot_meta["labels"]:
                slot_meta["labels"].append(month["source_label"])
            slot_meta["blocked"] = slot_meta["blocked"] or bool(month.get("blocked"))
            bucket = index.setdefault(key, {})
            for line in month.get("categories") or []:
                ident = (line.get("kind"), line.get("category"))
                slot = bucket.setdefault(ident, {
                    "kind": line.get("kind"),
                    "category": line.get("category"),
                    "category_he": line.get("category_he"),
                    "budgets": [],
                    "actuals": [],
                })
                if line.get("budget") is not None:
                    slot["budgets"].append(float(line["budget"]))
                if line.get("actual") is not None:
                    slot["actuals"].append(float(line["actual"]))
    months = []
    for month in sorted(index | meta):
        lines = []
        for ident in sorted(index.get(month, {}), key=lambda ident: tuple(str(part) for part in ident)):
            slot = index[month][ident]
            budget = round(sum(slot["budgets"]), 2) if slot["budgets"] else None
            actual = round(sum(slot["actuals"]), 2) if slot["actuals"] else None
            variance = None if budget is None or actual is None else round(actual - budget, 2)
            variance_pct = None
            if variance is not None and budget:
                variance_pct = round(variance / budget * 100, 1)
            lines.append({
                "kind": slot["kind"],
                "category": slot["category"],
                "category_he": slot["category_he"],
                "budget": budget,
                "actual": actual,
                "variance": variance,
                "variance_pct": variance_pct,
            })
        sources = meta[month]["sources"]
        months.append({
            "month": month,
            "period_start": meta[month]["period_start"],
            "period_end": meta[month]["period_end"],
            "source": (next(iter(sources)) if len(sources) == 1 else "mixed") if sources else None,
            "source_label": " / ".join(meta[month]["labels"]) or None,
            "blocked": meta[month]["blocked"],
            "categories": lines,
            # The totals of the combined month, the same shape as one entity's month.
            "totals": {
                "revenue": _total(lines, "revenue"),
                "costs": _total(lines, "cost"),
            },
        })
    return {
        "status": "ready",
        "has_budget": any(bool(section.get("has_budget")) for section in sections),
        "months": months,
        "message": "סכום התקציב והביצוע של ישויות הדשבורד.",
    }


def _total(lines: list[dict], kind: str) -> dict:
    rows = [line for line in lines if line["kind"] == kind]
    budgets = [line["budget"] for line in rows if line["budget"] is not None]
    actuals = [line["actual"] for line in rows if line["actual"] is not None]
    budget = round(sum(budgets), 2) if budgets else None
    actual = round(sum(actuals), 2) if actuals else None
    variance = None if budget is None or actual is None else round(actual - budget, 2)
    return {
        "budget": budget,
        "actual": actual,
        "variance": variance,
        "variance_pct": round(variance / budget * 100, 1) if variance is not None and budget else None,
    }


def _marked(description: str | None) -> bool:
    text = (description or "").casefold()
    return any(marker.casefold() in text for marker in _MARKER)


def intercompany_settings(plan: dict | None) -> dict:
    """``plan.intercompany``: ``windowDays`` (0–10, default 4) and ``accountIds``."""
    raw = (plan or {}).get("intercompany") if isinstance(plan, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    window = raw.get("windowDays", IC_WINDOW_DAYS)
    if isinstance(window, bool) or not isinstance(window, int) or not 0 <= window <= IC_MAX_WINDOW_DAYS:
        window = IC_WINDOW_DAYS
    accounts = raw.get("accountIds")
    accounts = {a for a in accounts if isinstance(a, int) and not isinstance(a, bool)} if isinstance(accounts, list) else set()
    return {"window_days": window, "account_ids": accounts}


def _candidates(db, org_ids: list[int], start: date, end: date, plan: dict | None, account_ids: set[int],
                drop_ids: set[int] | None = None):
    """The rows each entity's cash flow sums, filed, and limited to the configured accounts."""
    from ..bank_coverage import cashflow_row_objects
    from .activity_quality import confirmed_drop_ids
    plan = plan if isinstance(plan, dict) else {}
    decisions = plan.get("statusDecisions") if isinstance(plan.get("statusDecisions"), dict) else None
    rules = plan.get("statusRules") if isinstance(plan.get("statusRules"), list) else None
    out = []
    for org_id in dict.fromkeys(org_ids):
        rows = cashflow_row_objects(db, org_id, start, end)
        dropped = confirmed_drop_ids(rows, plan)
        rows = [row for row in rows if row.id not in dropped]
        # An organization none of whose accounts is configured keeps all its accounts.
        if account_ids and any(row.account_id in account_ids for row in rows):
            rows = [row for row in rows if row.account_id in account_ids]
        dropped_accounts = drop_ids or set()
        for row in rows:
            if row.account_id in dropped_accounts:
                continue
            txn = filing.txn_from_row(row)
            category = filing.classify(txn, decisions=decisions, custom_rules=rules).category
            raw = row.raw_data if isinstance(row.raw_data, dict) else {}
            party = " ".join(part for part in (
                row.description or "", str(raw.get("debtorName") or ""), str(raw.get("creditorName") or ""),
            ) if part)
            if category in IC_CATEGORIES or _marked(row.description) or filing.is_intercompany_counterparty(party):
                out.append((row, Decimal(str(row.amount)), category))
    return out


def _intercompany(db, org_ids: list[int], start: date, end: date, plan: dict | None = None,
                  labels: dict | None = None, drop_ids: set[int] | None = None) -> dict:
    """Intercompany netting of the combined cash flow, an explicit rule:

    1. rows: what each entity's cash flow sums (BOOKED, not superseded, no card rows,
       confirmed duplicates dropped), on ``plan.intercompany.accountIds`` when the
       entity has rows on those accounts;
    2. eligible: the row is filed as a transfer (``IC_CATEGORIES``: intercompany,
       transfers_out, other_in, bank_journal), not as sales, supplier, fee, ...; or
       its description carries an intercompany marker;
    3. a pair: two entities, opposite signs, the same absolute amount (±0.01), dates at
       most ``windowDays`` apart (default 4, the tool's match);
    4. deterministic: outflows in (date, id) order each take the free inflow with the
       smallest date gap, then the lowest id. A row is used once.

    Each side is removed from its own month (an outflow on 31.8 paired with an
    inflow on 2.9 removes 31.8 from August's outflows and 2.9 from September's inflows).
    """
    settings = intercompany_settings(plan)
    empty = {
        "summary": {"pairs": 0, "inflows": 0.0, "outflows": 0.0, "amount": 0.0,
                    "window_days": settings["window_days"], "rule": IC_RULE_HE, "items": [],
                    "by_month": {}},
        "by_month": {},
    }
    if len(set(org_ids)) < 2:
        return empty
    labels = labels or {}
    rows = _candidates(db, org_ids, start, end, plan, settings["account_ids"], drop_ids)
    outs = sorted((item for item in rows if item[1] < 0), key=lambda item: (item[0].transaction_date, item[0].id))
    ins = [item for item in rows if item[1] > 0]
    used: set[int] = set()
    by_month: dict[str, dict] = {}
    items = []
    total = Decimal(0)
    for out_row, out_amount, out_category in outs:
        best = None
        for in_row, in_amount, in_category in ins:
            if in_row.id in used or in_row.organization_id == out_row.organization_id:
                continue
            if abs(abs(out_amount) - in_amount) > IC_TOLERANCE:
                continue
            gap = abs((in_row.transaction_date - out_row.transaction_date).days)
            if gap > settings["window_days"]:
                continue
            key = (gap, in_row.id)
            if best is None or key < best[0]:
                best = (key, in_row, in_amount)
        if best is None:
            continue
        _, in_row, in_amount = best
        used.add(in_row.id)
        out_month = out_row.transaction_date.strftime("%Y-%m")
        in_month = in_row.transaction_date.strftime("%Y-%m")
        by_month.setdefault(in_month, {"inflows": 0.0, "outflows": 0.0})["inflows"] += float(in_amount)
        by_month.setdefault(out_month, {"inflows": 0.0, "outflows": 0.0})["outflows"] += float(-out_amount)
        total += in_amount
        if len(items) < IC_MAX_ITEMS:
            items.append({
                "from": labels.get(out_row.organization_id),
                "to": labels.get(in_row.organization_id),
                "out_date": out_row.transaction_date.isoformat(),
                "in_date": in_row.transaction_date.isoformat(),
                "amount": float(in_amount),
                "days_apart": abs((in_row.transaction_date - out_row.transaction_date).days),
            })
    for slot in by_month.values():
        slot["inflows"] = round(slot["inflows"], 2)
        slot["outflows"] = round(slot["outflows"], 2)
    pairs = len(used)
    summary = dict(empty["summary"])
    summary.update({
        "pairs": pairs,
        "inflows": round(float(total), 2),
        "outflows": round(float(total), 2),
        "amount": round(float(total), 2),
        "items": items,
        "by_month": {month: dict(by_month[month]) for month in sorted(by_month)},
    })
    return {"summary": summary, "by_month": by_month}
