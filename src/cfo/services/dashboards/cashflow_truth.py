"""Per-organization cash-flow source of truth.

One chain, one direction: inputs, budget drivers, a 13-week forecast, actuals,
alerts. Every organization starts from the same defaults. An override lives on
``plan.cashflowSettings`` (and per organization under ``organizations``).
Nothing here is named for a particular business, and a missing number stays
missing.

No database and no provider calls. Amounts are shekels, two decimals, inflow
positive and outflow negative.
"""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

WEEKS = 13
LAYER_BANK, LAYER_BOOKS, LAYER_ASSUMPTION = 1, 2, 3
CERTAIN, LIKELY, RISKY, ESTIMATE = "מאושר", "סביר", "מסוכן", "הערכה"
MISSING, ASSUMPTION, CONFIRMED = "missing", "assumption", "confirmed"
STATUSES = frozenset({MISSING, ASSUMPTION, CONFIRMED})
TERM_TYPES = frozenset({
    "eom_plus_days", "fixed_day_of_month", "days_from_invoice", "on_receipt", "per_order", "other_text",
})
INQUIRY_TERMS = frozenset({"per_order", "other_text"})
VAT_EXEMPT = frozenset({"payroll", "national_insurance", "pension", "fees", "interest", "arnona"})

UNKNOWN_LABEL = "חסר"
INQUIRY_LABEL = "נדרש בירור"
MANUAL_LABEL = "נדרש סכום, מקור ותאריך"
SHARED_LABEL = "משותף — לא מוקצה"
UNCLASSIFIED_LABEL = "לא מסווג"
PAST_CHEQUE_LABEL = "מועד שחלף ומצב לא ידוע"

# Standing rows every organization shows, even when every amount is unknown.
SCAFFOLD_ROWS = (
    ("opening", "יתרת פתיחה (עו״ש בלבד)", LAYER_BANK, CERTAIN),
    ("credit_facility", "מסגרת אשראי (בנפרד מהיתרה)", LAYER_BANK, CERTAIN),
    ("income", "הכנסות עתידיות", LAYER_ASSUMPTION, ESTIMATE),
    ("risky_income", "תקבולים מסוכנים", LAYER_ASSUMPTION, RISKY),
    ("suppliers_provision", "ספקים — הפרשה לתשלום", LAYER_BOOKS, LIKELY),
    ("suppliers_future", "ספקים עתידיים", LAYER_ASSUMPTION, ESTIMATE),
    ("payroll", "שכר", LAYER_ASSUMPTION, ESTIMATE),
    ("shared_costs", SHARED_LABEL, LAYER_ASSUMPTION, ESTIMATE),
    ("vat", "מע״מ נטו לתשלום", LAYER_BOOKS, LIKELY),
    ("financing", "מימון (הלוואות וניכיון)", LAYER_BANK, CERTAIN),
    ("cards", "כרטיסי אשראי (מחוץ לעו״ש)", LAYER_BANK, CERTAIN),
    ("unclassified", UNCLASSIFIED_LABEL, LAYER_BANK, CERTAIN),
)

DRIVER_TEMPLATES = (
    {"line_key": "revenue", "driver_type": "quantity_price", "label": "הכנסות"},
    {"line_key": "payroll", "driver_type": "payroll", "label": "שכר"},
    {"line_key": "suppliers", "driver_type": "quantity_price", "label": "ספקים"},
    {"line_key": "vehicle", "driver_type": "vehicle", "label": "רכב"},
    {"line_key": "shared", "driver_type": "shared_cost", "label": SHARED_LABEL},
)


class CashflowSettingsError(ValueError):
    def __init__(self, message_he: str):
        self.message_he = message_he
        super().__init__(message_he)


@dataclass(frozen=True)
class CashflowSettings:
    week_start: str = "sunday"
    week_end: str = "friday"
    saturday_cash: str = "next_sunday"
    payroll_day: int = 10
    supplier_terms: dict | None = None
    opening_accounts: str = "checking_only"
    credit_facility: str = "separate_headroom"
    shared_costs: str = "unallocated_row"
    cheque_discount: str = "short_loan_closes_on_maturity"
    near_limit_pct: float = 0.90
    low_headroom_amt: float = 2000.0
    stale_balance_days: int = 2
    match_tolerance: float = 1.0
    match_window_days: int = 7
    loss_cap: float | None = None
    funding_source: str | None = None
    supplier_overrides: dict | None = None
    allocation_rule: dict | None = None
    overridden: tuple = ()

    def terms(self) -> dict:
        return dict(self.supplier_terms or {"type": "eom_plus_days", "days": 30})

    def as_dict(self) -> dict:
        terms = self.terms()
        return {
            "week_start": self.week_start,
            "week_end": self.week_end,
            "saturday_cash": self.saturday_cash,
            "payroll_day": self.payroll_day,
            "supplier_terms": terms,
            "opening_accounts": self.opening_accounts,
            "credit_facility": self.credit_facility,
            "shared_costs": self.shared_costs,
            "cheque_discount": self.cheque_discount,
            "near_limit_pct": self.near_limit_pct,
            "low_headroom_amt": self.low_headroom_amt,
            "stale_balance_days": self.stale_balance_days,
            "match_tolerance": self.match_tolerance,
            "match_window_days": self.match_window_days,
            "loss_cap": self.loss_cap,
            "funding_source": self.funding_source,
            "allocation_rule": self.allocation_rule,
            "supplier_override_count": len(self.supplier_overrides or {}),
            "overridden": list(self.overridden),
        }


def _settings_error(message_he: str) -> CashflowSettingsError:
    return CashflowSettingsError(message_he)


def _date(value) -> date | None:
    if isinstance(value, date):
        return value
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _num(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or abs(number) == float("inf"):
        return None
    return number


def _dec(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not number.is_finite():
        return None
    return number


def _money(value) -> float | None:
    number = _num(value)
    return None if number is None else round(number, 2)


def _q(number: Decimal) -> Decimal:
    return number.quantize(Decimal("0.01"))


def end_of_month(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def roll_saturday(day: date) -> date:
    """Saturday cash is taken on the next Sunday, once.

    A forecast week is Sunday–Friday. Saturday is not a bucket. Friday stays
    Friday. The same calendar day is not also left on Saturday.
    """
    if day.weekday() == 5:
        return day + timedelta(days=1)
    return day


def week_windows(today: date, weeks: int = WEEKS) -> list[tuple[date, date]]:
    """Sunday-to-Friday windows, the first being the week that contains ``today``."""
    start = today - timedelta(days=(today.weekday() + 1) % 7)
    return [(start + timedelta(weeks=i), start + timedelta(weeks=i, days=5)) for i in range(weeks)]


def payroll_date(year: int, month: int, payroll_day: int = 10) -> date:
    """The cash date of that month's payroll. The 10th, rolled off Saturday."""
    last = monthrange(year, month)[1]
    return roll_saturday(date(year, month, min(int(payroll_day), last)))


def supplier_due(doc_date: date, terms: dict | None) -> date | None:
    """When a supplier document is paid.

    Default is end of the document's month plus 30 days (שוטף+30), the same
    date for every document in that month. Free-text and per-order terms are
    not guessed.
    """
    kind = "eom_plus_days" if not isinstance(terms, dict) else str(terms.get("type") or "eom_plus_days")
    if kind == "eom_plus_days":
        days = 30 if not isinstance(terms, dict) or terms.get("days") is None else int(terms["days"])
        return end_of_month(doc_date.year, doc_date.month) + timedelta(days=days)
    if kind == "fixed_day_of_month":
        day = int(terms["day_of_month"])
        year, month = doc_date.year, doc_date.month + 1
        if month == 13:
            year, month = year + 1, 1
        return date(year, month, min(day, monthrange(year, month)[1]))
    if kind == "days_from_invoice":
        return doc_date + timedelta(days=int(terms["days"]))
    if kind == "on_receipt":
        return doc_date
    return None


def _check_terms(terms, *, where: str) -> None:
    if not isinstance(terms, dict) or terms.get("type") not in TERM_TYPES:
        raise _settings_error(f"תנאי ספק לא תקינים ({where})")
    kind = terms["type"]
    if kind == "eom_plus_days" and not _int_in(terms.get("days", 30), 0, 365):
        raise _settings_error("ימי שוטף חייבים להיות 0 עד 365")
    if kind == "fixed_day_of_month" and not _int_in(terms.get("day_of_month"), 1, 31):
        raise _settings_error("יום קבוע בחודש חייב להיות 1 עד 31")
    if kind == "days_from_invoice" and not _int_in(terms.get("days"), 0, 365):
        raise _settings_error("ימים מחשבונית חייבים להיות 0 עד 365")
    if kind == "other_text" and not (isinstance(terms.get("free_text"), str) and terms["free_text"].strip()):
        raise _settings_error("תנאי ספק בטקסט חופשי דורשים את הטקסט, בלי תאריך משוער")
    if set(terms) - {"type", "days", "day_of_month", "free_text"}:
        raise _settings_error(f"תנאי ספק לא תקינים ({where})")


def _int_in(value, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _partial_settings(value: dict, *, allow_nested: bool) -> None:
    allowed = {
        "payroll_day", "supplier_terms", "near_limit_pct", "low_headroom_amt",
        "stale_balance_days", "match_tolerance", "match_window_days", "loss_cap",
        "funding_source", "allocation_rule", "suppliers",
    }
    if allow_nested:
        allowed |= {"organizations"}
    if set(value) - allowed:
        raise _settings_error("הגדרות התזרים מכילות שדה לא מוכר")
    if "payroll_day" in value and not _int_in(value["payroll_day"], 1, 28):
        raise _settings_error("יום השכר חייב להיות 1 עד 28")
    if "supplier_terms" in value:
        _check_terms(value["supplier_terms"], where="ברירת מחדל")
    if "near_limit_pct" in value:
        number = _num(value["near_limit_pct"])
        if number is None or not 0 < number <= 1:
            raise _settings_error("סף ההתקרבות למסגרת חייב להיות בין 0 ל-1")
    if "low_headroom_amt" in value:
        number = _num(value["low_headroom_amt"])
        if number is None or number < 0:
            raise _settings_error("סף הראש הפנוי לא תקין")
    if "stale_balance_days" in value and not _int_in(value["stale_balance_days"], 1, 30):
        raise _settings_error("גיל יתרה חייב להיות 1 עד 30 ימים")
    if "match_tolerance" in value:
        number = _num(value["match_tolerance"])
        if number is None or not 0 <= number <= 100:
            raise _settings_error("סבילות ההתאמה לא תקינה")
    if "match_window_days" in value and not _int_in(value["match_window_days"], 0, 31):
        raise _settings_error("חלון ההתאמה חייב להיות 0 עד 31 ימים")
    if "loss_cap" in value and value["loss_cap"] is not None:
        number = _num(value["loss_cap"])
        if number is None or number < 0:
            raise _settings_error("תקרת ההפסד לא תקינה")
    if "funding_source" in value and value["funding_source"] is not None:
        text = value["funding_source"]
        if not isinstance(text, str) or not text.strip() or len(text) > 120:
            raise _settings_error("מקור המימון לא תקין")
    if "allocation_rule" in value and value["allocation_rule"] is not None:
        raise _settings_error("מפתח הקצאה להוצאות משותפות עדיין לא מוגדר. השורה נשארת לא מוקצית")
    suppliers = value.get("suppliers")
    if suppliers is not None:
        if not isinstance(suppliers, dict) or len(suppliers) > 500:
            raise _settings_error("תנאי הספקים חייבים להיות מפה של עד 500 ספקים")
        for key, terms in suppliers.items():
            if not isinstance(key, str) or not key.strip() or len(key) > 64:
                raise _settings_error("מזהה ספק לא תקין")
            _check_terms(terms, where=key)


def validate_settings(value) -> None:
    """Reject a plan block that is not the settings object. ``None`` is the defaults."""
    if value is None:
        return
    if not isinstance(value, dict):
        raise _settings_error("הגדרות התזרים חייבות להיות אובייקט")
    _partial_settings(value, allow_nested=True)
    orgs = value.get("organizations")
    if orgs is None:
        return
    if not isinstance(orgs, dict) or len(orgs) > 100:
        raise _settings_error("הגדרות לפי ארגון חייבות להיות מפה")
    for key, block in orgs.items():
        if isinstance(key, bool) or not str(key).isdigit():
            raise _settings_error("מזהה ארגון בהגדרות חייב להיות מספר")
        if not isinstance(block, dict):
            raise _settings_error("הגדרות הארגון חייבות להיות אובייקט")
        _partial_settings(block, allow_nested=False)


def _block(raw: dict | None) -> dict:
    return raw if isinstance(raw, dict) else {}


def resolve_settings(plan: dict | None, organization_id: int | None = None) -> CashflowSettings:
    """Defaults, then the plan, then the block for this organization."""
    raw = _block(plan).get("cashflowSettings") if isinstance(plan, dict) else None
    if raw is not None:
        validate_settings(raw)
    base = _block(raw)
    org_block: dict = {}
    if organization_id is not None:
        orgs = base.get("organizations")
        if isinstance(orgs, dict):
            org_block = _block(orgs.get(str(organization_id)))
    overridden = tuple(key for key in org_block if key in {
        "payroll_day", "supplier_terms", "near_limit_pct", "low_headroom_amt",
        "stale_balance_days", "match_tolerance", "match_window_days", "loss_cap",
        "funding_source",
    })
    terms = org_block.get("supplier_terms") or base.get("supplier_terms") or {"type": "eom_plus_days", "days": 30}
    suppliers = {}
    for source in (base.get("suppliers"), org_block.get("suppliers")):
        if isinstance(source, dict):
            suppliers.update(source)
    loss = org_block["loss_cap"] if "loss_cap" in org_block else base.get("loss_cap")
    funding = org_block["funding_source"] if "funding_source" in org_block else base.get("funding_source")
    return CashflowSettings(
        payroll_day=int(org_block.get("payroll_day", base.get("payroll_day", 10))),
        supplier_terms=dict(terms),
        near_limit_pct=float(org_block.get("near_limit_pct", base.get("near_limit_pct", 0.90))),
        low_headroom_amt=float(org_block.get("low_headroom_amt", base.get("low_headroom_amt", 2000))),
        stale_balance_days=int(org_block.get("stale_balance_days", base.get("stale_balance_days", 2))),
        match_tolerance=float(org_block.get("match_tolerance", base.get("match_tolerance", 1))),
        match_window_days=int(org_block.get("match_window_days", base.get("match_window_days", 7))),
        loss_cap=None if loss is None else float(loss),
        funding_source=None if funding is None else str(funding).strip(),
        supplier_overrides=suppliers,
        overridden=overridden,
    )


def terms_for(settings: CashflowSettings, supplier_id) -> dict:
    overrides = settings.supplier_overrides or {}
    if supplier_id is not None and str(supplier_id) in overrides:
        return dict(overrides[str(supplier_id)])
    return settings.terms()


def _line(line_key: str, label: str, layer: int, certainty: str, *, status: str = MISSING,
          amount=None, source_id: str | None = None, **extra) -> dict:
    row = {
        "line_key": line_key,
        "label": label,
        "layer": layer,
        "certainty": ESTIMATE if layer == LAYER_ASSUMPTION else certainty,
        "status": status,
        "amount": _money(amount) if status != MISSING else None,
        "source_id": source_id or line_key,
        "scenario": extra.pop("scenario", "base"),
    }
    row.update(extra)
    if status == MISSING:
        row["amount"] = None
        row["unknown_label"] = extra.get("unknown_label") or UNKNOWN_LABEL
    return row


def _add_months(year: int, month: int, step: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + step
    return index // 12, index % 12 + 1


def _months_touching(first: date, last: date):
    year, month = first.year, first.month
    while date(year, month, 1) <= last:
        yield year, month
        year, month = _add_months(year, month, 1)


def document_key(document: dict) -> tuple:
    """One supplier document, one key. The same key cannot sit in two layers."""
    gross = _money(document.get("gross"))
    return (str(document.get("supplier_id") or ""), str(document.get("doc_ref") or ""), gross)


def _names_match(document: dict, txn: dict) -> bool:
    supplier = document.get("supplier_id")
    if supplier is not None and txn.get("supplier_id") is not None:
        return str(supplier) == str(txn.get("supplier_id"))
    left = str(document.get("supplier_name") or "").strip().casefold()
    right = str(txn.get("counterparty") or "").strip().casefold()
    return bool(left) and left in right or (bool(right) and right in left and len(right) >= 3)


def _in_window(doc_date: date | None, txn_date: date | None, days: int) -> bool:
    if doc_date is None or txn_date is None:
        return False
    return abs((txn_date - doc_date).days) <= days


def match_candidates(documents: list[dict], bank_txns: list[dict], settings: CashflowSettings) -> list[dict]:
    """Candidates only. Nothing here confirms a match."""
    found = []
    for document in documents:
        gross = _money(document.get("gross"))
        if gross is None:
            continue
        ref = str(document.get("doc_ref") or "").strip()
        doc_day = _date(document.get("doc_date"))
        for txn in bank_txns:
            if txn.get("is_internal_transfer") or txn.get("status") == "PENDING":
                continue
            amount = _money(txn.get("amount"))
            if amount is None or amount >= 0:
                continue
            if abs(abs(amount) - gross) > settings.match_tolerance:
                continue
            description = str(txn.get("description") or "")
            referenced = bool(ref) and ref in description
            if not _names_match(document, txn):
                continue
            if not referenced and not _in_window(doc_day, _date(txn.get("booking_date")), settings.match_window_days):
                continue
            found.append({
                "document_id": document.get("id"),
                "bank_txn_id": txn.get("id"),
                "amount": abs(amount),
                "match_state": "candidate",
                "by": "reference" if referenced else "date_window",
            })
    return found


def _confirmed_paid(document: dict, bank_txns: list[dict]) -> tuple[float, list]:
    """Cash already confirmed against the document. A candidate does not reduce it."""
    payments = document.get("payments") if isinstance(document.get("payments"), list) else []
    confirmed = [
        item for item in payments
        if isinstance(item, dict) and item.get("match_state") == "confirmed" and _money(item.get("amount")) is not None
    ]
    if confirmed:
        return round(sum(_money(item["amount"]) for item in confirmed), 2), [item.get("txn_id") for item in confirmed]
    matched = document.get("matched_bank_txn_id")
    if matched is not None:
        txn = next((row for row in bank_txns if str(row.get("id")) == str(matched)), None)
        amount = _money(txn.get("amount")) if isinstance(txn, dict) else None
        if amount is not None:
            return round(abs(amount), 2), [matched]
    paid = _money(document.get("paid_gross"))
    if paid is None:
        return 0.0, []
    return round(paid, 2), []


def provision_of(document: dict, bank_txns: list[dict]) -> dict:
    """Open amount of one document: gross minus cash already confirmed in the bank."""
    gross = _money(document.get("gross"))
    if gross is None:
        return {"amount": None, "status": MISSING, "label": UNKNOWN_LABEL}
    paid, links = _confirmed_paid(document, bank_txns)
    remaining = round(gross - paid, 2)
    if remaining < 0:
        remaining = 0.0
    return {
        "amount": remaining,
        "paid": paid,
        "status": CONFIRMED if links or document.get("paid_gross") is not None else ASSUMPTION,
        "fully_matched": document.get("matched_bank_txn_id") is not None and remaining == 0,
        "links": links,
    }


def remaining_budget(budget, bank_actual, books_provision) -> float | None:
    """Layer 3 keeps only what layers 1 and 2 have not already taken.

    A missing budget stays missing. A missing bank or books figure is not
    treated as zero, so the remainder stays missing too. A real zero is only
    the part of a known budget that was fully used.
    """
    if _num(budget) is None:
        return None
    if bank_actual is None or books_provision is None:
        return None
    return round(max(0.0, float(budget) - float(bank_actual) - float(books_provision)), 2)


def detect_duplicates(documents, bank_txns, forecast_lines=None, *, settings: CashflowSettings | None = None) -> dict:
    """The hard check from section 0.2. A violation blocks publication.

    ``None`` inputs were not loaded. An empty list was loaded and is empty.
    """
    settings = settings or CashflowSettings()
    if documents is None or bank_txns is None:
        return {
            "status": MISSING,
            "blocks_publish": False,
            "violations": [],
            "candidates": [],
            "provisions": [],
            "label": "אין נתוני בנק או אין מסמכי ספרים להצלבה. זה אינו אישור שאין כפל.",
            "provider_calls": 0,
        }
    violations = []
    seen: dict[tuple, list] = {}
    for document in documents:
        if not isinstance(document, dict):
            continue
        key = document_key(document)
        seen.setdefault(key, []).append(document.get("id"))
    for key, ids in seen.items():
        if key[0] and key[1] and key[2] is not None and len(ids) > 1:
            violations.append({
                "code": "duplicate_document_key",
                "message_he": "מסמך ספק נספר יותר מפעם אחת.",
                "source_id": f"doc:{key[0]}:{key[1]}:{key[2]}",
            })
    candidates = match_candidates([d for d in documents if isinstance(d, dict)], bank_txns, settings)
    provisions = []
    layer2 = 0.0
    open_ap = 0.0
    for document in documents:
        if not isinstance(document, dict) or document.get("kind", "AP") != "AP":
            continue
        row = provision_of(document, bank_txns)
        row["document_id"] = document.get("id")
        row["key"] = list(document_key(document))
        provisions.append(row)
        if row["amount"] is None:
            continue
        open_ap += row["amount"]
        if document.get("matched_bank_txn_id") is not None and row["amount"] > 0:
            violations.append({
                "code": "provision_on_fully_matched",
                "message_he": "מסמך שותאם לבנק ועדיין מחזיק הפרשה.",
                "source_id": f"doc:{document.get('id')}",
            })
        if document.get("card_purchase") and row["amount"] > 0:
            charge_ids = {
                f"bank:{txn.get('id')}" for txn in bank_txns
                if txn.get("is_card_charge") and _same_amount(txn, document)
            }
            line_ids = {line.get("source_id") for line in forecast_lines or []}
            if f"doc:{document.get('id')}" in line_ids and charge_ids & line_ids:
                violations.append({
                    "code": "card_double_count",
                    "message_he": "רכישת אשראי שכבר נרשמה וגם חיוב הכרטיס בבנק נספרים שניהם.",
                    "source_id": f"doc:{document.get('id')}",
                })
    for txn in bank_txns:
        if txn.get("is_internal_transfer"):
            for line in forecast_lines or []:
                if line.get("source_id") == f"bank:{txn.get('id')}" and line.get("line_key") in {"income", "suppliers_future"}:
                    violations.append({
                        "code": "internal_transfer_as_income",
                        "message_he": "העברה פנימית נספרת כהכנסה או כהוצאה.",
                        "source_id": f"bank:{txn.get('id')}",
                    })
        if txn.get("is_financing") and txn.get("amount", 0) > 0:
            for line in forecast_lines or []:
                if line.get("source_id") == f"bank:{txn.get('id')}" and line.get("line_key") == "income":
                    violations.append({
                        "code": "financing_as_income",
                        "message_he": "מימון נספר כהכנסה תפעולית.",
                        "source_id": f"bank:{txn.get('id')}",
                    })
    for line in forecast_lines or []:
        if line.get("layer") == LAYER_BOOKS and line.get("line_key") == "suppliers_provision" and _num(line.get("amount")) is not None:
            layer2 += abs(float(line["amount"]))
    if documents and layer2 - open_ap > 0.01:
        violations.append({
            "code": "layer2_exceeds_open_ap",
            "message_he": "הפרשת הספקים בתחזית גדולה מיתרת הספקים הפתוחה.",
            "source_id": "suppliers_provision",
        })
    return {
        "status": "blocked" if violations else "clear",
        "blocks_publish": bool(violations),
        "violations": violations,
        "candidates": candidates,
        "provisions": provisions,
        "open_ap": round(open_ap, 2),
        "layer2_supplier": round(layer2, 2),
        "label": "נמצא כפל בין הבנק לספרים." if violations else "אין כפל בין הבנק לספרים במטען שנבדק.",
        "provider_calls": 0,
    }


def _same_amount(txn: dict, document: dict) -> bool:
    amount = _money(txn.get("amount"))
    gross = _money(document.get("gross"))
    return amount is not None and gross is not None and abs(abs(amount) - gross) <= 1


def coverage(bank_rows) -> dict:
    """Every bank movement sits in one bucket, and the buckets add up to the total.

    A row marked unclassified (or with no category) is the visible unclassified
    line. It is not dropped and it is not called zero unless the feed was loaded
    and really had no such rows.
    """
    if bank_rows is None:
        return {
            "status": MISSING,
            "blocks_publish": False,
            "ok": None,
            "charges_total": None,
            "classified_total": None,
            "unclassified": {"label": UNCLASSIFIED_LABEL, "amount": None, "status": MISSING},
            "label": "אין תנועות בנק לבדיקת כיסוי.",
            "provider_calls": 0,
        }
    unclassified = 0.0
    classified = 0.0
    unclassified_count = 0
    seen_ids = set()
    for row in bank_rows:
        ident = row.get("id")
        if ident is not None:
            if ident in seen_ids:
                return {
                    "status": CONFIRMED,
                    "blocks_publish": True,
                    "ok": False,
                    "charges_total": None,
                    "classified_total": None,
                    "unclassified": {"label": UNCLASSIFIED_LABEL, "amount": None, "status": MISSING},
                    "label": "תנועת בנק נספרה פעמיים. אי אפשר לפרסם.",
                    "provider_calls": 0,
                }
            seen_ids.add(ident)
        amount = _money(row.get("amount"))
        if amount is None:
            return {
                "status": MISSING,
                "blocks_publish": True,
                "ok": False,
                "charges_total": None,
                "classified_total": None,
                "unclassified": {"label": UNCLASSIFIED_LABEL, "amount": None, "status": MISSING},
                "label": "תנועת בנק בלי סכום. הכיסוי לא חושב, ולא הוזן 0.",
                "provider_calls": 0,
            }
        if row.get("unclassified") or not row.get("category"):
            unclassified += amount
            unclassified_count += 1
        else:
            classified += amount
    total = round(classified + unclassified, 2)
    classified = round(classified, 2)
    unclassified = round(unclassified, 2)
    ok = abs(total - (classified + unclassified)) < 0.01
    return {
        "status": CONFIRMED,
        "blocks_publish": not ok,
        "ok": ok,
        "charges_total": total,
        "classified_total": classified,
        "unclassified": {
            "label": UNCLASSIFIED_LABEL,
            "amount": unclassified,
            "count": unclassified_count,
            "status": CONFIRMED,
        },
        "label": (
            "סכום הסיווגים שווה לסך התנועות."
            if ok else
            "סכום הסיווגים אינו שווה לסך התנועות. אי אפשר לפרסם."
        ) if bank_rows else "אין תנועות בנק בחלון. הסכום 0 הוא תוצאת ספירה, לא מילוי של נתון חסר.",
        "provider_calls": 0,
    }


def cheque_verification(*, when: date, today: date, state: str | None = None, status: str | None = None) -> dict:
    """A cheque whose date has passed and whose fate is unknown is not open."""
    terminal = status in {"cleared", "bounced", "verified"} or state == "cleared"
    if terminal:
        label = {"bounced": "חזר", "verified": "אומת"}.get(status or "", "נפרע")
        code = status or "cleared"
        return {"status": code, "label": label, "counts_as_open": False, "certainty": CERTAIN}
    future = state == "future" or when > today
    if future:
        return {
            "status": "unverified",
            "label": "עתידי, לא מאומת",
            "counts_as_open": False,
            "certainty": LIKELY,
        }
    return {
        "status": "past_maturity_unknown",
        "label": PAST_CHEQUE_LABEL,
        "counts_as_open": False,
        "certainty": None,
    }


def liquidity_position(*, balance, limit, balance_date, report_date: date, settings: CashflowSettings) -> dict:
    """Checking balance and the facility are separate. Headroom is derived."""
    balance_day = _date(balance_date)
    age = None if balance_day is None else (report_date - balance_day).days
    stale = age is None or age > settings.stale_balance_days
    if _num(balance) is None or _num(limit) is None:
        return {
            "balance": _money(balance),
            "limit": _money(limit),
            "headroom": None,
            "credit_used": None,
            "utilization": None,
            "state": "לא ידוע",
            "balance_age_days": age,
            "stale": stale,
            "stale_label": "יתרה ישנה" if stale and balance_day is not None else (
                "תאריך היתרה לא ידוע" if balance_day is None else None
            ),
            "status": MISSING if _num(balance) is None else ASSUMPTION,
        }
    balance = float(balance)
    limit = float(limit)
    used = max(0.0, -balance)
    headroom = balance + limit
    breach = max(0.0, used - limit)
    utilization = None if limit <= 0 else used / limit
    if breach > 0:
        state = "חריגה"
    elif (utilization is not None and utilization >= settings.near_limit_pct) or headroom < settings.low_headroom_amt:
        state = "קרוב למסגרת"
    else:
        state = "בתוך המסגרת"
    return {
        "balance": round(balance, 2),
        "limit": round(limit, 2),
        "headroom": round(headroom, 2),
        "credit_used": round(used, 2),
        "utilization": None if utilization is None else round(utilization, 4),
        "breach": round(breach, 2),
        "state": state,
        "balance_age_days": age,
        "stale": stale,
        "stale_label": "יתרה ישנה" if stale else None,
        "status": CONFIRMED,
    }


def funding_need(closings, opening, credit_limit, weekly_nets) -> dict:
    """Trough of the cumulative change, plus the sum of negative weeks beside it."""
    if opening is None or not closings or any(value is None for value in closings):
        return {
            "status": MISSING,
            "amount": None,
            "after_credit": None,
            "sum_of_negative_weeks": None,
            "label": "בלי יתרות סגירה ידועות אין צורך מימון. לא הוזן 0.",
        }
    changes = [float(closing) - float(opening) for closing in closings]
    trough = max(0.0, -min(changes))
    after = None if credit_limit is None else round(max(0.0, trough - float(credit_limit)), 2)
    if weekly_nets is None or any(value is None for value in weekly_nets):
        negative = None
    else:
        negative = round(sum(value for value in weekly_nets if value < 0), 2)
    return {
        "status": CONFIRMED,
        "amount": round(trough, 2),
        "after_credit": after,
        "sum_of_negative_weeks": negative,
        "label": "צורך המימון הוא השפל המצטבר. סכום השבועות השליליים הוא מדד נפרד.",
    }


def accept_manual(amount, source, ref_date, verified_by=None) -> dict:
    """A filled-in hole counts only with an amount, a source and a date.

    Zero is allowed only when someone verified it.
    """
    number = _num(amount)
    day = _date(ref_date)
    named = isinstance(source, str) and bool(source.strip())
    verified = isinstance(verified_by, str) and bool(verified_by.strip())
    if number is None or not named or day is None or (number == 0 and not verified):
        return {"ok": False, "amount": None, "status": MISSING, "label": MANUAL_LABEL}
    return {
        "ok": True,
        "amount": round(number, 2),
        "status": CONFIRMED,
        "source": source.strip(),
        "ref_date": day.isoformat(),
        "verified_by": verified_by.strip() if verified else None,
        "label": None,
    }


def _component(present: bool, value: Decimal | None, missing_label: str) -> tuple[Decimal | None, str | None]:
    if not present or value is None:
        return None, missing_label
    return value, None


def evaluate_driver(row: dict, settings: CashflowSettings | None = None) -> dict:
    """One budget driver. A blank component is missing, not zero."""
    settings = settings or CashflowSettings()
    kind = row.get("driver_type") or "quantity_price"
    status = row.get("status") if row.get("status") in STATUSES else MISSING
    base = {
        "line_key": row.get("line_key"),
        "label": row.get("label") or row.get("line_key"),
        "driver_type": kind,
        "month": row.get("month"),
        "status": MISSING,
        "amount_net": None,
        "amount_gross": None,
        "certainty": ESTIMATE,
        "layer": LAYER_ASSUMPTION,
        "parts": {},
    }
    if kind == "quantity_price":
        qty, price = _dec(row.get("qty")), _dec(row.get("unit_price_net"))
        if qty is None or price is None:
            base["label_he"] = "חסרים כמות ומחיר"
            return base
        if status == MISSING:
            base["label_he"] = UNKNOWN_LABEL
            return base
        net = _q(qty * price)
        vat = _dec(row.get("vat_pct"))
        exempt = row.get("line_key") in VAT_EXEMPT or row.get("vat_exempt") is True
        if exempt:
            gross = net
        elif vat is None:
            gross = None
            base["gross_label"] = "שיעור המע״מ חסר. הברוטו לא חושב."
        else:
            gross = _q(net * (1 + vat))
        base.update(status=status, amount_net=float(net), amount_gross=None if gross is None else float(gross))
        return base
    if kind == "payroll":
        rate, qty, uplift = _dec(row.get("rate")), _dec(row.get("qty")), _dec(row.get("employer_uplift_pct"))
        if rate is None or qty is None:
            base["label_he"] = "חסר היקף"
            return base
        if uplift is None:
            base["label_he"] = "חסרים היקף או עלויות מעסיק"
            return base
        if status == MISSING:
            base["label_he"] = UNKNOWN_LABEL
            return base
        cost = _q(rate * qty * (1 + uplift))
        year, month = _month_parts(row.get("month"))
        base.update(
            status=status, amount_net=float(cost), amount_gross=float(cost),
            pay_date=None if year is None else payroll_date(year, month, settings.payroll_day).isoformat(),
        )
        return base
    if kind == "vehicle":
        km, per_km = _dec(row.get("km")), _dec(row.get("fuel_per_km"))
        fuel, fuel_label = _component(km is not None and per_km is not None, None if km is None or per_km is None else _q(km * per_km), "חסרים ק״מ או דלק לק״מ")
        insurance = _dec(row.get("insurance_annual"))
        insurance_m = None if insurance is None else _q(insurance / 12)
        maintenance, rent = _dec(row.get("maintenance")), _dec(row.get("rent"))
        interest, principal = _dec(row.get("interest")), _dec(row.get("principal"))
        parts = {
            "fuel": None if fuel is None else float(fuel),
            "insurance": None if insurance_m is None else float(insurance_m),
            "maintenance": None if maintenance is None else float(maintenance),
            "rent": None if rent is None else float(rent),
            "interest": None if interest is None else float(interest),
            "principal": None if principal is None else float(principal),
        }
        operating_parts = (fuel, insurance_m, maintenance, rent)
        if any(part is None for part in operating_parts):
            base["parts"] = parts
            base["label_he"] = fuel_label or "חסר רכיב רכב"
            return base
        operating = _q(sum(operating_parts, Decimal("0")))
        cash = None
        if interest is not None and principal is not None:
            cash = _q(operating + interest + principal)
        cost, residual, life = _dec(row.get("cost")), _dec(row.get("residual")), _dec(row.get("life_months"))
        depreciation = None
        if cost is not None and residual is not None and life not in (None, 0) and row.get("source") and _date(row.get("in_service_date")):
            depreciation = _q((cost - residual) / life)
        base["parts"] = parts
        base["operating"] = float(operating)
        base["depreciation"] = None if depreciation is None else float(depreciation)
        base["cash"] = None if cash is None else float(cash)
        base["status"] = status if cash is not None else MISSING
        base["amount_net"] = None if cash is None else float(cash)
        if cash is None:
            base["label_he"] = "חסרים ריבית או קרן"
        return base
    if kind == "shared_cost":
        amount = _dec(row.get("amount"))
        if amount is None or status == MISSING:
            base["label_he"] = UNKNOWN_LABEL
            base["allocated"] = False
            return base
        base.update(status=status, amount_net=float(_q(amount)), allocated=False)
        return base
    base["label_he"] = INQUIRY_LABEL
    return base


def _month_parts(value) -> tuple[int | None, int | None]:
    if not isinstance(value, str) or len(value) < 7:
        return None, None
    try:
        return int(value[:4]), int(value[5:7])
    except ValueError:
        return None, None


def evaluate_drivers(rows: list[dict] | None, settings: CashflowSettings | None = None) -> dict:
    """Templates when nothing was entered. Totals only when every row is complete."""
    settings = settings or CashflowSettings()
    if not rows:
        evaluated = [
            evaluate_driver({**template, "status": MISSING}, settings) for template in DRIVER_TEMPLATES
        ]
        return {
            "status": MISSING,
            "rows": evaluated,
            "complete": 0,
            "total": len(evaluated),
            "amount_net": None,
            "label": "חסרים נתוני תקציב",
            "profit_rate": None,
        }
    evaluated = [evaluate_driver(row, settings) for row in rows if isinstance(row, dict)]
    blocked = any(row.get("classification") == "unclassified" for row in rows)
    complete = [row for row in evaluated if row["status"] != MISSING and row["amount_net"] is not None]
    amount = None
    if not blocked and len(complete) == len(evaluated) and evaluated:
        amount = round(sum(row["amount_net"] for row in complete), 2)
    return {
        "status": CONFIRMED if amount is not None else MISSING,
        "rows": evaluated,
        "complete": len(complete),
        "total": len(evaluated),
        "amount_net": amount,
        "label": None if amount is not None else ("יש שורות לסיווג" if blocked else "חסרים נתוני תקציב"),
        "classification_blocks_total": blocked,
    }


def profit_rate(part, revenue) -> float | None:
    """A margin only when revenue is known and not zero."""
    numerator, denominator = _num(part), _num(revenue)
    if numerator is None or denominator in (None, 0):
        return None
    return round(numerator / denominator, 4)


def _favorable(kind: str, variance: Decimal | None) -> bool | None:
    if variance is None:
        return None
    if kind == "cost":
        return variance < 0
    return variance > 0


def variance_line(*, kind: str, budget_qty, budget_price, actual_qty, actual_price) -> dict:
    """Quantity and price split of actual minus budget. Missing stays missing."""
    bq, bp, aq, ap = _dec(budget_qty), _dec(budget_price), _dec(actual_qty), _dec(actual_price)
    if None in (bq, bp, aq, ap) or bq == 0 and bp is None:
        return {
            "status": MISSING, "variance": None, "quantity_variance": None, "price_variance": None,
            "favorable": None, "label": "לא הושלם",
        }
    budget_amount = _q(bq * bp)
    actual_amount = _q(aq * ap)
    total = _q(actual_amount - budget_amount)
    quantity = _q((aq - bq) * bp)
    price = _q((ap - bp) * aq)
    return {
        "status": CONFIRMED,
        "budget_amount": float(budget_amount),
        "actual_amount": float(actual_amount),
        "variance": float(total),
        "quantity_variance": float(quantity),
        "price_variance": float(price),
        "mix_variance": 0.0,
        "favorable": _favorable(kind, total),
        "identity": float(_q(quantity + price - total)) == 0.0,
    }


def _weighted_price(qty_price: list[tuple[Decimal, Decimal]]) -> Decimal | None:
    qty = sum((pair[0] for pair in qty_price), Decimal("0"))
    if qty == 0:
        return None
    return _q(sum((pair[0] * pair[1] for pair in qty_price), Decimal("0")) / qty)


def variance_set(lines: list[dict], *, kind: str) -> dict:
    """YTD actual against YTD budget, and what is left of the annual target.

    The price is revenue (or cost) divided by quantity. A simple average of
    monthly prices is not used. Mix appears when more than one line shares
    the period.
    """
    ytd = [row for row in lines if row.get("in_ytd")]
    annual = [row for row in lines if row.get("in_annual", True)]
    ytd_result = _aggregate(ytd, kind)
    annual_budget_qty = _sum_field(annual, "budget_qty")
    annual_budget_amount = _product_sum(annual, "budget_qty", "budget_price")
    remaining = None
    if ytd_result["status"] == CONFIRMED and annual_budget_qty is not None and annual_budget_amount is not None:
        remaining = {
            "qty": float(_q(annual_budget_qty - _dec(ytd_result["actual_qty"]))),
            "amount": float(_q(annual_budget_amount - _dec(ytd_result["actual_amount"]))),
            "label": "נותר ליעד השנתי. זה אינו חריגה מתקציב השנה עד היום.",
        }
    mix = _mix(ytd, kind) if len(ytd) > 1 else None
    return {
        "ytd": ytd_result,
        "remaining_to_annual": remaining,
        "mix": mix,
        "budget_price_is_weighted": True,
    }


def _sum_field(rows, name) -> Decimal | None:
    values = [_dec(row.get(name)) for row in rows]
    if any(value is None for value in values):
        return None
    return sum(values, Decimal("0"))


def _product_sum(rows, qty_name, price_name) -> Decimal | None:
    total = Decimal("0")
    for row in rows:
        qty, price = _dec(row.get(qty_name)), _dec(row.get(price_name))
        if qty is None or price is None:
            return None
        total += qty * price
    return total


def _aggregate(rows: list[dict], kind: str) -> dict:
    if not rows:
        return {"status": MISSING, "variance": None, "label": "לא הושלם"}
    fields = ("budget_qty", "budget_price", "actual_qty", "actual_price")
    if any(_dec(row.get(name)) is None for row in rows for name in fields):
        return {"status": MISSING, "variance": None, "quantity_variance": None, "price_variance": None,
                "favorable": None, "label": "לא הושלם"}
    budget_qty = sum((_dec(row["budget_qty"]) for row in rows), Decimal("0"))
    actual_qty = sum((_dec(row["actual_qty"]) for row in rows), Decimal("0"))
    budget_amount = sum((_dec(row["budget_qty"]) * _dec(row["budget_price"]) for row in rows), Decimal("0"))
    actual_amount = sum((_dec(row["actual_qty"]) * _dec(row["actual_price"]) for row in rows), Decimal("0"))
    budget_price = None if budget_qty == 0 else budget_amount / budget_qty
    actual_price = None if actual_qty == 0 else actual_amount / actual_qty
    simple = sum((_dec(row["budget_price"]) for row in rows), Decimal("0")) / len(rows)
    if budget_price is None or actual_price is None:
        return {"status": MISSING, "variance": None, "label": "לא הושלם"}
    total = _q(actual_amount - budget_amount)
    quantity = _q((actual_qty - budget_qty) * budget_price)
    price = _q(total - quantity)
    return {
        "status": CONFIRMED,
        "budget_qty": float(budget_qty),
        "actual_qty": float(actual_qty),
        "budget_amount": float(_q(budget_amount)),
        "actual_amount": float(_q(actual_amount)),
        "budget_price_weighted": float(_q(budget_price)),
        "actual_price_weighted": float(_q(actual_price)),
        "budget_price_simple_average": float(_q(simple)),
        "variance": float(total),
        "quantity_variance": float(quantity),
        "price_variance": float(price),
        "favorable": _favorable(kind, total),
        "label": None,
    }


def _mix(rows: list[dict], kind: str) -> dict:
    """Volume, mix and price. The three add up to the total variance."""
    aggregated = _aggregate(rows, kind)
    if aggregated["status"] != CONFIRMED:
        return {"status": MISSING, "label": "לא הושלם"}
    budget_qty = _dec(aggregated["budget_qty"])
    actual_qty = _dec(aggregated["actual_qty"])
    budget_price = _dec(aggregated["budget_price_weighted"])
    volume = _q((actual_qty - budget_qty) * budget_price)
    price = Decimal("0")
    mix = Decimal("0")
    for row in rows:
        bq, bp = _dec(row["budget_qty"]), _dec(row["budget_price"])
        aq, ap = _dec(row["actual_qty"]), _dec(row["actual_price"])
        price += aq * (ap - bp)
        budget_share = Decimal("0") if budget_qty == 0 else bq / budget_qty
        actual_share = Decimal("0") if actual_qty == 0 else aq / actual_qty
        mix += (actual_share - budget_share) * actual_qty * bp
    price, mix = _q(price), _q(mix)
    total = _dec(aggregated["variance"])
    # Rounding can leave one agora. The reported mix absorbs it so the identity holds,
    # and the unadjusted mix stays visible.
    residual = _q(total - volume - price - mix)
    return {
        "status": CONFIRMED,
        "volume_variance": float(volume),
        "mix_variance": float(_q(mix + residual)),
        "mix_variance_unadjusted": float(mix),
        "price_variance": float(price),
        "variance": float(total),
        "identity": float(_q(volume + mix + residual + price - total)) == 0.0,
        "favorable": _favorable(kind, total),
    }


def _place(events: list[dict]) -> list[dict]:
    """Roll Saturday to the next Sunday and keep one row per source."""
    seen = set()
    placed = []
    for event in events:
        raw = _date(event.get("due_date_raw") or event.get("date"))
        if raw is None:
            placed.append(event)
            continue
        adjusted = roll_saturday(raw)
        source = event.get("source_id")
        ident = (source, adjusted.isoformat(), event.get("amount"), event.get("line_key"))
        if source and ident in seen:
            continue
        if source:
            seen.add(ident)
        nxt = dict(event)
        nxt["due_date_raw"] = raw.isoformat()
        nxt["due_date_adjusted"] = adjusted.isoformat()
        nxt["date"] = adjusted.isoformat()
        nxt["saturday_rolled"] = adjusted != raw
        placed.append(nxt)
    return placed


def _week_amount(events: list[dict], start: date, end: date) -> dict:
    inside = []
    for event in events:
        day = _date(event.get("date"))
        if day is not None and start <= day <= end:
            inside.append(event)
    missing = [
        event for event in inside
        if event.get("status") == MISSING and event.get("scenario", "base") == "base"
        and event.get("line_key") not in {"risky_income", "shared_costs", "credit_facility"}
    ]
    if missing:
        return {"in": None, "out": None, "net": None, "unknown": [event["label"] for event in missing]}
    inflow = outflow = 0.0
    for event in inside:
        if event.get("scenario") == "full" or event.get("is_internal_transfer"):
            continue
        amount = _num(event.get("amount"))
        if amount is None or event.get("status") == MISSING:
            continue
        if amount > 0:
            inflow += amount
        elif amount < 0:
            outflow += amount
    return {
        "in": round(inflow, 2), "out": round(outflow, 2), "net": round(inflow + outflow, 2),
        "unknown": [],
    }


def _daily_min(opening, events, start: date, end: date, week_known: bool):
    if opening is None or not week_known:
        return None
    by_day: dict[date, float] = {}
    for event in events:
        day = _date(event.get("date"))
        amount = _num(event.get("amount"))
        if day is None or amount is None or not start <= day <= end:
            continue
        if event.get("scenario") == "full" or event.get("is_internal_transfer") or event.get("status") == MISSING:
            continue
        by_day[day] = by_day.get(day, 0.0) + amount
    closing = float(opening)
    lowest = closing
    day = start
    while day <= end:
        closing = round(closing + by_day.get(day, 0.0), 2)
        lowest = min(lowest, closing)
        day += timedelta(days=1)
    return lowest


def discounted_cheque_lines(checks, *, today: date, settings: CashflowSettings) -> list[dict]:
    """Each discounted cheque is a short loan that closes on that cheque's date.

    The repayment and the receipt that settles it are one pair. Net cash is
    zero, and neither leg is operating income or an operating expense.
    """
    lines = []
    for check in checks or []:
        if not isinstance(check, dict) or not check.get("discounted"):
            continue
        when = _date(check.get("date"))
        amount = _money(check.get("amount"))
        if when is None:
            continue
        verification = cheque_verification(when=when, today=today, status=check.get("status") or "unverified")
        if amount is None:
            lines.append(_line(
                "financing", f"ניכיון צ׳ק {check.get('check') or ''}".strip(),
                LAYER_BANK, LIKELY, status=MISSING, source_id=f"cheque-discount:{check.get('check')}",
                due_date_raw=when.isoformat(),
            ))
            continue
        source = f"cheque-discount:{check.get('check') or when.isoformat()}"
        common = {
            "due_date_raw": when.isoformat(),
            "is_financing": True,
            "offsets": source,
            "verification": verification,
        }
        lines.append(_line(
            "financing", f"צ׳ק {check.get('check')} · פירעון ניכיון" if check.get("check") else "שיק מנוכה · פירעון",
            LAYER_BANK, CERTAIN, status=CONFIRMED, amount=-abs(amount), source_id=f"{source}:close", **common,
        ))
        lines.append(_line(
            "financing", f"צ׳ק {check.get('check')} · תקבול שסוגר את הניכיון" if check.get("check") else "שיק מנוכה · תקבול סוגר",
            LAYER_BANK, CERTAIN, status=CONFIRMED, amount=abs(amount), source_id=f"{source}:receipt", **common,
        ))
    return lines


def _scaffold_events(settings: CashflowSettings, today: date, horizon_end: date, drivers: dict) -> list[dict]:
    events = []
    for year, month in _months_touching(today, horizon_end):
        pay = payroll_date(year, month, settings.payroll_day)
        if today <= pay <= horizon_end:
            driven = next((
                row for row in drivers["rows"]
                if row.get("line_key") == "payroll" and row.get("month") == f"{year:04d}-{month:02d}"
                and row.get("amount_gross") is not None and row.get("status") != MISSING
            ), None)
            if driven is None:
                events.append(_line(
                    "payroll", "שכר", LAYER_ASSUMPTION, ESTIMATE, status=MISSING,
                    source_id=f"payroll:{year:04d}-{month:02d}", due_date_raw=pay.isoformat(),
                    unknown_label="השכר לא ידוע: אין דרייבר שכר לחודש הזה. לא הוזן 0.",
                ))
            else:
                events.append(_line(
                    "payroll", "שכר", LAYER_ASSUMPTION, ESTIMATE, status=driven["status"],
                    amount=-abs(driven["amount_gross"]), source_id=f"payroll:{year:04d}-{month:02d}",
                    due_date_raw=pay.isoformat(),
                ))
        due = supplier_due(date(year, month, 1), settings.terms())
        if due is not None:
            adjusted = roll_saturday(due)
            if today <= adjusted <= horizon_end:
                events.append(_line(
                    "suppliers_future", f"ספקים שוטף+{settings.terms().get('days', 30)} (אספקה {year:04d}-{month:02d})",
                    LAYER_ASSUMPTION, ESTIMATE, status=MISSING,
                    source_id=f"suppliers:{year:04d}-{month:02d}", due_date_raw=due.isoformat(),
                    unknown_label="תשלום הספקים לא ידוע: אין דרייבר ספקים לחודש האספקה. לא הוזן 0.",
                ))
    return events


def scaffold(
    *,
    as_of: date,
    plan: dict | None = None,
    organization_id: int | None = None,
    opening=None,
    opening_as_of=None,
    credit_limit=None,
    documents=None,
    bank_txns=None,
    checks=None,
    drivers=None,
    weeks: int = WEEKS,
) -> dict:
    """The forecast a brand-new organization gets before any figure is known."""
    settings = resolve_settings(plan, organization_id)
    windows = week_windows(as_of, weeks)
    horizon_end = windows[-1][1]
    driver_rows = drivers if drivers is not None else (plan or {}).get("budgetDrivers") if isinstance(plan, dict) else None
    evaluated = evaluate_drivers(driver_rows if isinstance(driver_rows, list) else None, settings)
    covered = coverage(bank_txns)
    position = liquidity_position(
        balance=opening, limit=credit_limit, balance_date=opening_as_of,
        report_date=as_of, settings=settings,
    )
    standing = []
    for key, label, layer, certainty in SCAFFOLD_ROWS:
        extra = {}
        status = MISSING
        amount = None
        if key == "opening" and position["balance"] is not None and position["status"] == CONFIRMED:
            status, amount = CONFIRMED, position["balance"]
        elif key == "credit_facility" and position["limit"] is not None:
            status, amount = CONFIRMED, position["limit"]
        elif key == "unclassified":
            bucket = covered["unclassified"]
            status = bucket["status"]
            amount = bucket["amount"]
        elif key == "shared_costs":
            extra["allocated"] = False
        standing.append(_line(key, label, layer, certainty, status=status, amount=amount, source_id=key, **extra))
    events = _scaffold_events(settings, as_of, horizon_end, evaluated)
    events.extend(discounted_cheque_lines(checks, today=as_of, settings=settings))
    events.extend(_provision_events(documents, bank_txns, settings, as_of))
    events = _place(events)
    duplicate = detect_duplicates(documents, bank_txns, events, settings=settings)
    income_known = any(
        row.get("line_key") == "revenue" and row.get("status") != MISSING and row.get("amount_gross") is not None
        for row in evaluated["rows"]
    )
    horizon_gap = (not income_known) or any(
        event.get("status") == MISSING and event.get("scenario", "base") == "base"
        and event.get("line_key") not in {"risky_income", "shared_costs", "credit_facility"}
        for event in events
    )
    week_rows = []
    closing = position["balance"] if position["status"] == CONFIRMED else None
    for start, end in windows:
        flows = _week_amount(events, start, end)
        if horizon_gap:
            flows = {
                "in": None, "out": None, "net": None,
                "unknown": flows["unknown"] or ["ההכנסה הצפויה לא ידועה. לא הוזן 0."],
            }
        known = flows["net"] is not None and closing is not None
        if flows["net"] is None or closing is None:
            closing = None
            headroom = None
        else:
            closing = round(closing + flows["net"], 2)
            headroom = None if position["limit"] is None else round(closing + position["limit"], 2)
        week_rows.append({
            "week_start": start.isoformat(),
            "week_end": end.isoformat(),
            "in": flows["in"],
            "out": flows["out"],
            "net": flows["net"],
            "closing": closing,
            "headroom": headroom,
            "daily_min": _daily_min(position["balance"] if known else None, events, start, end, known),
            "credit_limit": position["limit"],
            "unknown": flows["unknown"],
        })
    closings = [row["closing"] for row in week_rows]
    nets = [row["net"] for row in week_rows]
    blockers = []
    if duplicate["blocks_publish"]:
        blockers.extend(duplicate["violations"])
    if covered["blocks_publish"]:
        blockers.append({"code": "coverage", "message_he": covered["label"], "source_id": "unclassified"})
    return {
        "as_of": as_of.isoformat(),
        "settings": settings.as_dict(),
        "lines": standing,
        "events": events,
        "weeks": week_rows,
        "drivers": evaluated,
        "duplicates": duplicate,
        "coverage": covered,
        "liquidity": position,
        "funding_need": funding_need(
            closings, position["balance"] if position["status"] == CONFIRMED else None,
            position["limit"], nets,
        ),
        "variance": {"status": MISSING, "label": "אין כמות ומחיר בפועל מול תקציב. לא הוזן 0."},
        "shared_costs": {"label": SHARED_LABEL, "allocated": False, "amount": None, "status": MISSING},
        "cheques": [
            cheque_verification(when=_date(check["date"]), today=as_of, state=check.get("state"), status=check.get("status"))
            | {"check": check.get("check"), "date": check.get("date")}
            for check in checks or [] if isinstance(check, dict) and _date(check.get("date"))
        ],
        "publish_blockers": blockers,
        "publishable": not blockers,
        "provider_calls": 0,
    }


def _provision_events(documents, bank_txns, settings: CashflowSettings, today: date) -> list[dict]:
    if not documents or bank_txns is None:
        return []
    events = []
    for document in documents:
        if not isinstance(document, dict) or document.get("kind", "AP") != "AP":
            continue
        if document.get("card_purchase"):
            continue
        row = provision_of(document, bank_txns)
        if row["amount"] is None:
            events.append(_line(
                "suppliers_provision", "ספקים — הפרשה לתשלום", LAYER_BOOKS, LIKELY, status=MISSING,
                source_id=f"doc:{document.get('id')}",
            ))
            continue
        if row["amount"] == 0:
            continue
        doc_day = _date(document.get("doc_date"))
        if doc_day is None:
            continue
        terms = terms_for(settings, document.get("supplier_id"))
        due = supplier_due(doc_day, terms)
        if due is None:
            events.append(_line(
                "suppliers_provision", INQUIRY_LABEL, LAYER_BOOKS, LIKELY, status=MISSING,
                source_id=f"doc:{document.get('id')}",
                unknown_label=INQUIRY_LABEL,
            ))
            continue
        if roll_saturday(due) < today:
            continue
        events.append(_line(
            "suppliers_provision", "ספקים — הפרשה לתשלום", LAYER_BOOKS, LIKELY,
            status=ASSUMPTION, amount=-abs(row["amount"]),
            source_id=f"doc:{document.get('id')}", due_date_raw=due.isoformat(),
        ))
    return events


def attach_variance(report: dict, lines: list[dict], *, kind: str = "revenue") -> dict:
    """Put a computed variance set on a scaffold. The lines are the caller's actuals."""
    nxt = dict(report)
    nxt["variance"] = variance_set(lines, kind=kind)
    return nxt
