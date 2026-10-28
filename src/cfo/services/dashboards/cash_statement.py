"""Cash flow by line item × month: a port of the Eliav tool's ``cashStatement``.

Actual months: the BOOKED rows the view already filed (``books.classified_bank``),
summed per filing category, signed, with VAT (it is cash). Categories are grouped
as in the tool: operating in, operating out, finance, financing, internal (with
taxes). A month without bank rows is unknown (``None``), not 0.

Forecast months: the view's forecast (budget, else the trend), as three lines:
operating in = forecast revenue, operating out = forecast costs, financing =
principal. The forecast is ex-VAT, so it is labelled as an approximation and is
never added to the actual lines. No provider calls.
"""
from __future__ import annotations

from datetime import date

from . import filing
from .books import month_windows

GROUPS = (
    ("operating_in", "תפעולי — כניסות"),
    ("operating_out", "תפעולי — יציאות"),
    ("finance", "מימון שוטף (עמלות וריבית)"),
    ("financing", "מימון (הלוואות ובעלים)"),
    ("internal", "פנימי ומסים"),
)
NETTING_LINES = (
    ("intercompany_netting_in", "inflows", -1, "קיזוז בין-חברתי — כניסות שקוזזו (מאוחד)"),
    ("intercompany_netting_out", "outflows", 1, "קיזוז בין-חברתי — יציאות שקוזזו (מאוחד)"),
)
NETTING_IDS = frozenset(line_id for line_id, *_ in NETTING_LINES)
NETTING_NOTE = (
    "העברות בין-חברתיות שקוזזו כבר הוסרו מהכניסות ומהיציאות של התזרים המאוחד. "
    "שתי שורות הקיזוז מראות כמה הוסר בכל חודש; בנטו הן מתקזזות, כמו ההעברות עצמן."
)
FORECAST_NOTE = "תחזית: תקציב אם יש, אחרת מגמה. ללא מע״מ — קירוב, לא מצטרף לביצוע."
FORECAST_LINE_NOTE = (
    "התחזית מחושבת לפי קבוצה בלבד: כניסות תפעוליות (הכנסות), יציאות תפעוליות (הוצאות) והחזרי קרן. "
    "אין לה פירוט לפי סעיף, ולכן תאי הסעיפים בעמודות התחזית ריקים (—). מימון שוטף ופנימי לא נחזים."
)


def _r(value: float) -> float:
    return round(value + 0.0, 2)


def _group(category: str, total: float) -> str:
    group = filing.CATEGORIES.get(category, {}).get("group", "operating")
    if group == "operating":
        return "operating_in" if total > 0 else "operating_out"
    if group == "tax":
        return "internal"
    return group


def build_cash_statement(filed, start: date, end: date, forecast: dict | None = None) -> dict:
    months = [key for key, _lo, _hi in month_windows(start, end)]
    sums: dict[str, dict[str, float]] = {}
    seen: set[str] = set()
    for txn, result in filed or []:
        key = txn.date[:7]
        if key not in months:
            continue
        seen.add(key)
        slot = sums.setdefault(result.category, {})
        slot[key] = slot.get(key, 0.0) + txn.amount

    def value(category: str, month: str):
        return None if month not in seen else _r(sums.get(category, {}).get(month, 0.0))

    lines = []
    for category, values in sums.items():
        total = _r(sum(values.values()))
        meta = filing.CATEGORIES.get(category, {})
        lines.append({
            "id": category,
            "label": meta.get("label", category),
            "group": _group(category, total),
            "review": bool(meta.get("review")),
            "values": {month: value(category, month) for month in months},
            "total": total,
        })
    lines.sort(key=lambda line: ([g for g, _ in GROUPS].index(line["group"]), -abs(line["total"])))

    def group_total(group: str) -> dict:
        rows = [line for line in lines if line["group"] == group]
        return {month: None if month not in seen else _r(sum(line["values"][month] or 0.0 for line in rows))
                for month in months}

    totals = {group: group_total(group) for group, _label in GROUPS}

    def combine(*names):
        return {month: None if month not in seen else _r(sum(totals[name][month] for name in names))
                for month in months}

    totals["operating"] = combine("operating_in", "operating_out")
    totals["after_finance"] = combine("operating_in", "operating_out", "finance")
    totals["net"] = combine(*[group for group, _label in GROUPS])
    return {
        "status": "ready" if seen else "unknown",
        "months": months,
        "groups": [{"id": group, "label": label} for group, label in GROUPS],
        "lines": lines,
        "totals": totals,
        "forecast": _forecast_columns(forecast),
        "basis": "booked_only",
        "message": (
            "ביצוע: תנועות בנק BOOKED מתויקות, כולל מע״מ, לפי סעיף וחודש. חודש בלי תנועות בנק אינו ידוע."
        ),
        "provider_calls": 0,
    }


def _scope_note(scope: dict[str, dict]) -> str | None:
    if not scope:
        return None
    parts = []
    for month, item in sorted(scope.items()):
        parts.append(f"{month}: {item['label']} ({', '.join(str(label) for label in item['missing'])} — אין תנועות בנק)")
    return (
        "חודש שמסומן \"בלבד\" הוא סכום הישויות שיש להן תנועות בנק באותו חודש, לא של כל הקבוצה. "
        + "; ".join(parts) + "."
    )


def _forecast_columns(forecast: dict | None) -> dict | None:
    if not isinstance(forecast, dict) or not forecast.get("months"):
        return None
    totals = forecast.get("totals") or {}
    rows = {"operating_in": {}, "operating_out": {}, "financing": {}, "net": {}}
    for month in forecast["months"]:
        cell = totals.get(month) or {}
        revenue, costs, principal = cell.get("revenue"), cell.get("costs"), cell.get("principal")
        rows["operating_in"][month] = revenue
        rows["operating_out"][month] = None if costs is None else _r(-costs)
        rows["financing"][month] = None if principal is None else _r(-principal)
        rows["net"][month] = cell.get("cash_flow")
    return {
        "status": forecast.get("status"),
        "months": list(forecast["months"]),
        "rows": rows,
        "note": FORECAST_NOTE,
        "line_items": False,
        "line_note": FORECAST_LINE_NOTE,
    }


def subtract_filed(statement: dict, pairs) -> dict:
    """Remove filed rows that belong to a duplicate copy of a bank account.

    A month the statement does not know stays unknown. Netting lines are left
    alone: the duplicate rows were not paired.
    """
    if not isinstance(statement, dict) or not pairs or not statement.get("months"):
        return statement
    months = statement["months"]
    known = {month for month in months if ((statement.get("totals") or {}).get("net") or {}).get(month) is not None}
    lines = [{**line, "values": dict(line.get("values") or {})} for line in statement.get("lines") or []]
    index = {line["id"]: line for line in lines}
    for txn, result in pairs:
        month = str(getattr(txn, "date", ""))[:7]
        if month not in known:
            continue
        line = index.get(getattr(result, "category", None))
        if line is None or line["id"] in NETTING_IDS:
            continue
        current = line["values"].get(month)
        if current is None:
            continue
        line["values"][month] = _r(current - float(txn.amount))
    for line in lines:
        line["total"] = _r(sum(line["values"].get(month) or 0.0 for month in months))
        if line["id"] not in NETTING_IDS:
            line["group"] = _group(line["id"], line["total"])
    totals = {}
    for name, _label in GROUPS:
        rows = [line for line in lines if line["group"] == name]
        totals[name] = {
            month: None if month not in known else _r(sum(line["values"].get(month) or 0.0 for line in rows))
            for month in months
        }
    for name, parts_of in (("operating", ("operating_in", "operating_out")),
                           ("after_finance", ("operating_in", "operating_out", "finance")),
                           ("net", tuple(group for group, _label in GROUPS))):
        totals[name] = {
            month: None if month not in known else _r(sum(totals[part][month] for part in parts_of))
            for month in months
        }
    copied = dict(statement)
    copied["lines"] = lines
    copied["totals"] = totals
    return copied


def known_entities(sections: list[dict], months: list[str]) -> dict[str, list]:
    """Per month, the labels of the entities whose statement knows it (has bank rows in it)."""
    out: dict[str, list] = {month: [] for month in months}
    for section in sections:
        net = (((section.get("view") or {}).get("cash_statement") or {}).get("totals") or {}).get("net") or {}
        for month in months:
            if net.get(month) is not None:
                out[month].append(section.get("label"))
    return out


def scope_of(known_by: dict[str, list], labels: list) -> dict[str, dict]:
    """Months only some entities know: who is in the sum and who is missing (the tool's "chef_only")."""
    scope = {}
    for month, present in known_by.items():
        if present and len(present) < len(labels):
            scope[month] = {
                "label": " + ".join(str(label) for label in present) + " בלבד",
                "entities": list(present),
                "missing": [label for label in labels if label not in present],
            }
    return scope


def combine(sections: list[dict], forecast: dict | None = None, netted: dict | None = None) -> dict:
    """The entities' statements summed per line and month.

    A month no entity knows is unknown. A month only some entities know (Food Group's
    bank import starts in July) is the sum of those entities, labelled in ``scope``
    ("שף בלבד"), as the Eliav tool shows it; it is never presented as the whole group."""
    sections = [section for section in sections
                if ((section.get("view") or {}).get("cash_statement") or {}).get("months")]
    parts = [section["view"]["cash_statement"] for section in sections]
    if not parts:
        return {"status": "unknown", "months": [], "lines": [], "totals": {}, "forecast": None,
                "groups": [{"id": g, "label": label} for g, label in GROUPS], "provider_calls": 0}
    months = parts[0]["months"]
    known_by = known_entities(sections, months)
    known = {month for month in months if known_by[month]}
    scope = scope_of(known_by, [section.get("label") for section in sections])
    index: dict[str, dict] = {}
    for part in parts:
        for line in part.get("lines") or []:
            slot = index.setdefault(line["id"], {**line, "values": {m: None for m in months}, "total": 0.0})
            for month in months:
                cell = line["values"].get(month)
                if month in known:
                    slot["values"][month] = _r((slot["values"][month] or 0.0) + (cell or 0.0))
    # The intercompany netting of the combined cash flow, as two internal lines: the netted
    # inflows (minus) and the netted outflows (plus). One line of outflows - inflows read 0
    # whenever both sides of a pair fell in the same month, so the netting looked absent.
    # Together they keep the statement's net equal to the combined cash flow.
    if netted and any(netted.get(month) for month in months):
        for line_id, side, sign, label in NETTING_LINES:
            index[line_id] = {
                "id": line_id, "label": label, "group": "internal", "review": False, "total": 0.0,
                "values": {month: None if month not in known else _r(sign * float((netted.get(month) or {}).get(side) or 0))
                           for month in months},
            }
    # A line's group follows the combined sign (an operating line may flip).
    lines = []
    for line in index.values():
        line["total"] = _r(sum(line["values"][month] or 0.0 for month in months))
        if line["id"] not in NETTING_IDS:
            line["group"] = _group(line["id"], line["total"])
        lines.append(line)
    lines.sort(key=lambda line: ([g for g, _ in GROUPS].index(line["group"]), -abs(line["total"])))
    totals = {}
    for name, _label in GROUPS:
        rows = [line for line in lines if line["group"] == name]
        totals[name] = {month: None if month not in known else _r(sum(line["values"][month] or 0.0 for line in rows))
                        for month in months}
    for name, parts_of in (("operating", ("operating_in", "operating_out")),
                           ("after_finance", ("operating_in", "operating_out", "finance")),
                           ("net", tuple(g for g, _ in GROUPS))):
        totals[name] = {month: None if month not in known else _r(sum(totals[p][month] for p in parts_of))
                        for month in months}
    return {
        "status": "ready" if known else "unknown",
        "months": months,
        "groups": [{"id": g, "label": label} for g, label in GROUPS],
        "lines": lines,
        "totals": totals,
        "forecast": _forecast_columns(forecast),
        "basis": "booked_only",
        "message": parts[0].get("message"),
        "netting_note": NETTING_NOTE if any(line["id"] in NETTING_IDS for line in lines) else None,
        "scope": scope,
        "scope_note": _scope_note(scope),
        "provider_calls": 0,
    }
