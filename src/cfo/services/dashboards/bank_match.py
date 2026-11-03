"""Bank match: one bank row against its book documents, decided by the owner.

Owner actions per BOOKED row:

* אשר — one document or many (a weekly Max settlement against its sales
  invoices, an Isracard charge against its expenses). The documents' signed
  effect, less a fee the owner states, must equal the bank amount within ₪1.
* אשר לפי קטגוריה — no document: owner current account, payroll, loan,
  cheque discounting or card clearing, with the target ledger card the
  owner names.
* בדיקה / חסר מסמך / פתח מחדש.

A decision lives in ``bank_match_decisions`` (+ ``bank_match_documents``)
and is written with the bank row's match columns in one transaction: the
caller commits once, a failure rolls everything back. Nothing is posted to
SUMIT. No candidate is an empty list, not a 0.

Signed effect on the bank: a sale invoice is +, a sale credit note −, a
supplier bill or expense −, a supplier credit or refunded expense +.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..bank_reconciliation import BankTxnLite, DocLite, _score
from .filing import Txn, displayed_counterparty

STATUSES = ("approved", "check", "missing_doc")
ACTIONS = {"approve", "approve_category", "check", "missing_doc", "reopen"}
ENTITY_TYPES = {"invoice", "bill", "expense"}
CATEGORIES = {
    "owner_current": "חו״ז בעלים",
    "payroll": "שכר",
    "loan": "הלוואה (מימון)",
    "cheque_discounting": "ניכיון צ׳קים (מימון)",
    "card_clearing": "סליקת כרטיסים",
}
MULTI_MATCH = "bank_match"  # matched_entity_type when a row is explained by a decision, not one document
TOLERANCE = 1.00
MAX_NOTE = 300
MAX_DOCUMENTS = 200
MAX_CANDIDATES = 3
MIN_SCORE = 0.3
PICK_DAYS_BEFORE = 45
PICK_DAYS_AFTER = 7
ACCOUNT_RE = re.compile(r"^[0-9A-Za-z֐-׿][0-9A-Za-z֐-׿ \-/.]{0,39}$")
STATUS_HE = {
    "approved": "אושר",
    "check": "בבדיקה",
    "missing_doc": "חסר מסמך",
    "open": "ממתין להחלטה",
}
_CLOSED_INVOICE = {"paid", "void", "cancelled"}
_CLOSED_BILL = {"paid", "void"}


@dataclass
class MatchDoc:
    entity_type: str
    id: int
    amount: float  # signed effect on the bank
    date: date | None = None
    name: str = ""
    credit: bool = False  # a credit note, supplier credit or refund


def _as_date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _money(value: float) -> str:
    return f"₪{abs(value):,.2f}".replace(".00", "")


def _doc_out(doc: MatchDoc, score) -> dict:
    return {
        "entity_type": doc.entity_type,
        "entity_id": doc.id,
        "score": score,
        "amount": round(doc.amount, 2),
        "date": doc.date.isoformat() if doc.date else None,
        "name": doc.name or "",
        "credit": doc.credit,
    }


def candidates_for(txn: Txn, docs: list[MatchDoc], taken: set[tuple[str, int]]) -> list[dict]:
    """Up to three single documents whose signed effect matches the row. A taken document is not offered."""
    if not txn.amount:
        return []
    amount = float(txn.amount)
    party = displayed_counterparty(txn)
    lite = BankTxnLite(
        id=txn.id, amount=amount, date=_as_date(txn.date),
        description=" ".join(part for part in (txn.description, party) if part),
    )
    found = []
    for doc in docs:
        if (doc.entity_type, doc.id) in taken or not doc.amount or (doc.amount > 0) != (amount > 0):
            continue
        score = _score(lite, DocLite(doc.id, doc.entity_type, abs(doc.amount), doc.date, doc.name),
                       amount_tol=0.02, date_window=7)
        if score is None or score < MIN_SCORE:
            continue
        found.append(_doc_out(doc, round(score, 3)))
    found.sort(key=lambda item: (-item["score"], item["entity_type"], item["entity_id"]))
    return found[:MAX_CANDIDATES]


def pickable_documents(docs: list[MatchDoc], taken: set[tuple[str, int]], start: date, end: date) -> list[dict]:
    """Untaken documents near the window, for a 1:N pick. The owner picks; the server checks the sum."""
    low, high = start - timedelta(days=PICK_DAYS_BEFORE), end + timedelta(days=PICK_DAYS_AFTER)
    picked = [
        _doc_out(doc, None) for doc in docs
        if (doc.entity_type, doc.id) not in taken and doc.amount
        and (doc.date is None or low <= doc.date <= high)
    ]
    picked.sort(key=lambda item: (item["date"] or "", item["entity_type"], item["entity_id"]))
    return picked


def _bucket(rows: list[dict], status: str | None = None) -> dict:
    picked = rows if status is None else [row for row in rows if row["status"] == status]
    return {"count": len(picked), "amount": round(sum(row["amount"] for row in picked), 2)}


def decision_status(txn_id, recon: dict, decision: dict | None) -> str:
    """The row's status. An approval whose bank columns no longer agree is open again."""
    if not isinstance(decision, dict) or decision.get("status") not in STATUSES:
        return "open"
    if decision["status"] != "approved":
        return decision["status"]
    return "approved" if recon.get(txn_id) == expected_match(decision) else "open"


def expected_match(decision: dict) -> tuple[str, int]:
    """What the bank row's match columns hold for an approved decision."""
    documents = decision.get("documents") or []
    if decision.get("kind") == "documents" and len(documents) == 1 and not decision.get("fee"):
        return documents[0]["entity_type"], documents[0]["entity_id"]
    return MULTI_MATCH, decision.get("id")


def build_report(paired, recon: dict, decisions: dict | None, docs: list[MatchDoc],
                 taken: set[tuple[str, int]] | None = None, start: date | None = None,
                 end: date | None = None) -> dict:
    """Rows, candidates and a signed summary.

    ``recon`` maps txn id → (matched_entity_type, matched_entity_id) for
    reconciled rows. ``decisions`` maps txn id → decision dict.
    ``taken`` is every document already explaining a bank row in the
    organization; a row's own match stays offered on that row.
    """
    decisions = decisions if isinstance(decisions, dict) else {}
    taken = set(taken or ())
    for decision in decisions.values():
        for line in (decision or {}).get("documents") or []:
            taken.add((line["entity_type"], line["entity_id"]))
    by_key = {(doc.entity_type, doc.id): doc for doc in docs}
    rows = []
    for txn, filed in paired:
        decision = decisions.get(txn.id)
        status = decision_status(txn.id, recon, decision)
        auto = recon.get(txn.id) if status != "approved" else None
        if auto and auto[0] not in ENTITY_TYPES:
            auto = None
        row = {
            "id": txn.id,
            "date": txn.date,
            "amount": round(float(txn.amount), 2),
            "counterparty": displayed_counterparty(txn),
            "description": txn.description or "",
            "category": filed.category,
            "status": status,
            "status_he": STATUS_HE[status],
            "note": (decision or {}).get("note") or None if status != "open" else None,
            "matched": None,
            "auto_match": {"entity_type": auto[0], "entity_id": auto[1]} if auto else None,
            "candidates": [],
        }
        if status == "approved":
            lines = decision.get("documents") or []
            row["matched"] = {
                "kind": decision.get("kind"),
                "documents": [dict(line) for line in lines],
                "fee": decision.get("fee"),
                "category": decision.get("category"),
                "category_he": CATEGORIES.get(decision.get("category")),
                "target_account": decision.get("target_account"),
            }
        elif status == "open":
            own_taken = taken - {auto} if auto else taken
            row["candidates"] = candidates_for(txn, docs, own_taken)
            doc = by_key.get(auto) if auto else None
            if doc is not None and not any(
                (item["entity_type"], item["entity_id"]) == auto for item in row["candidates"]
            ):
                row["candidates"].insert(0, _doc_out(doc, None))
        rows.append(row)
    summary = {status: _bucket(rows, status) for status in (*STATUSES, "open")}
    summary["total"] = _bucket(rows)
    parts = [summary[status] for status in (*STATUSES, "open")]
    summary["coverage_ok"] = (
        sum(part["count"] for part in parts) == summary["total"]["count"]
        and abs(sum(part["amount"] for part in parts) - summary["total"]["amount"]) < 0.01
    )
    summary["missing_doc"]["abs_amount"] = round(
        sum(abs(row["amount"]) for row in rows if row["status"] == "missing_doc"), 2)
    summary["decided"] = summary["total"]["count"] > 0 and summary["open"]["count"] == 0
    # Balanced: every row is explained — by documents or by a category.
    # A row in check or missing a document is decided, not balanced.
    summary["balanced"] = summary["total"]["count"] > 0 and summary["approved"]["count"] == summary["total"]["count"]
    summary["done"] = summary["balanced"]
    report = {"rows": rows, "summary": summary, "status_labels": STATUS_HE, "categories": CATEGORIES}
    if start is not None and end is not None:
        report["documents"] = pickable_documents(docs, taken, start, end)
    return report


def closing_state(summary: dict, bank_as_of: str | None, end: str) -> dict:
    """Whether the window is balanced, and up to which bank date. No rows is not balanced."""
    total = summary["total"]["count"]
    open_count = summary["open"]["count"]
    if total == 0:
        return {"done": False, "label_he": "אין תנועות בנק שמורות בטווח. זה לא מאוזן — זה חסר."}
    if open_count:
        return {"done": False, "label_he": f"עדיין לא מאוזן — {open_count} תנועות ממתינות להחלטה"}
    missing = summary["missing_doc"]
    check = summary["check"]
    if missing["count"] or check["count"]:
        parts = []
        if missing["count"]:
            parts.append(f"חסרים {missing['count']} מסמכים {_money(missing.get('abs_amount', missing['amount']))}")
        if check["count"]:
            parts.append(f"{check['count']} בבדיקה")
        return {"done": False, "label_he": "הוכרע, לא מאוזן — " + " · ".join(parts)}
    if not bank_as_of:
        return {"done": True, "label_he": "מאוזן — כל התנועות השמורות הוסברו. תאריך הבנק חסר."}
    if bank_as_of < end:
        ddmm = f"{bank_as_of[8:10]}.{bank_as_of[5:7]}"
        return {"done": True, "label_he": f"מאוזן עד {ddmm} — הבנק לא מעודכן אחרי התאריך הזה"}
    return {"done": True, "label_he": "מאוזן — כל התנועות בטווח הוסברו"}


# ---------------------------------------------------------------------- #
# Database
# ---------------------------------------------------------------------- #
def _status_value(row) -> str:
    status = getattr(row, "status", None)
    return str(getattr(status, "value", status) or "").lower()


def _is_credit_invoice(row) -> bool:
    raw = row.raw_data if isinstance(row.raw_data, dict) else {}
    return raw.get("document_type") in {"credit_note", "credit_invoice"} or float(row.total or 0) < 0


def _open_amount(row) -> float:
    """The amount still to settle: the balance of a partly paid document, else its total."""
    total = float(row.total or 0)
    balance = float(row.balance or 0)
    if _status_value(row) == "partially_paid" and 0 < balance < total:
        return balance
    return total


def invoice_doc(row) -> MatchDoc | None:
    """A sale invoice (+) or credit note (−). A paid, void or cancelled invoice is not open."""
    from ..bank_reconciliation import _contact_name
    credit = _is_credit_invoice(row)
    status = _status_value(row)
    if status in {"void", "cancelled"} or (status == "paid" and not credit):
        return None
    amount = -abs(float(row.total or 0)) if credit else _open_amount(row)
    return MatchDoc("invoice", row.id, amount, row.issue_date or row.due_date, _contact_name(row), credit)


def bill_doc(row) -> MatchDoc | None:
    """A supplier bill (−) or supplier credit (+). A paid or void bill is not open."""
    from ..bank_reconciliation import _vendor_name
    if _status_value(row) in _CLOSED_BILL:
        return None
    total = float(row.total or 0)
    amount = abs(total) if total < 0 else -_open_amount(row)
    return MatchDoc("bill", row.id, amount, row.issue_date or row.due_date, _vendor_name(row), total < 0)


def expense_doc(row) -> MatchDoc:
    """An expense (−, its total with VAT) or a refund (+)."""
    total = float(row.total or 0) or float(row.amount or 0)
    return MatchDoc("expense", row.id, -total, row.expense_date,
                    row.supplier_name or row.description or "", total < 0)


def document_for(entity_type: str, row) -> MatchDoc | None:
    return {"invoice": invoice_doc, "bill": bill_doc, "expense": expense_doc}[entity_type](row)


def load_match_docs(db, organization_id: int) -> list[MatchDoc]:
    """Open documents of the organization with their signed effect on the bank."""
    from ...models import Bill, Expense, Invoice
    docs = []
    for model, entity_type in ((Invoice, "invoice"), (Bill, "bill"), (Expense, "expense")):
        for row in db.query(model).filter(model.organization_id == organization_id).all():
            doc = document_for(entity_type, row)
            if doc is not None:
                docs.append(doc)
    return docs


def taken_documents(db, organization_id: int) -> dict[tuple[str, int], int | None]:
    """Every document that already explains a bank row in the organization → that row's id.

    Read from the whole organization, not the window: a reconciled bank row,
    a bank match line, or an active receipt allocation.
    """
    from ...models import BankMatchDocument, BankTransaction, CollectionPaymentAllocation
    taken: dict[tuple[str, int], int | None] = {}
    for row in db.query(BankTransaction.id, BankTransaction.matched_entity_type, BankTransaction.matched_entity_id).filter(
        BankTransaction.organization_id == organization_id,
        BankTransaction.is_reconciled.is_(True),
        BankTransaction.matched_entity_type.in_(tuple(ENTITY_TYPES)),
    ):
        taken[(row.matched_entity_type, row.matched_entity_id)] = row.id
    for row in db.query(BankMatchDocument).filter(BankMatchDocument.organization_id == organization_id):
        taken[(row.entity_type, row.entity_id)] = row.bank_transaction_id
    for row in db.query(CollectionPaymentAllocation).filter(
        CollectionPaymentAllocation.organization_id == organization_id,
        CollectionPaymentAllocation.status == "active",
    ):
        taken.setdefault(("invoice", row.invoice_id), row.bank_transaction_id)
    return taken


def _decision_dict(decision, lines) -> dict:
    return {
        "id": decision.id,
        "status": decision.status,
        "kind": decision.kind,
        "category": decision.category,
        "target_account": decision.target_account,
        "fee": float(decision.fee_amount) if decision.fee_amount is not None else None,
        "note": decision.note,
        "documents": [
            {"entity_type": line.entity_type, "entity_id": line.entity_id, "amount": float(line.amount)}
            for line in lines
        ],
    }


def load_decisions(db, organization_id: int, txn_ids: list[int]) -> dict[int, dict]:
    from ...models import BankMatchDecision, BankMatchDocument
    if not txn_ids:
        return {}
    decisions = db.query(BankMatchDecision).filter(
        BankMatchDecision.organization_id == organization_id,
        BankMatchDecision.bank_transaction_id.in_(txn_ids),
    ).all()
    lines: dict[int, list] = {}
    if decisions:
        for line in db.query(BankMatchDocument).filter(
            BankMatchDocument.decision_id.in_([decision.id for decision in decisions])
        ).order_by(BankMatchDocument.id):
            lines.setdefault(line.decision_id, []).append(line)
    return {decision.bank_transaction_id: _decision_dict(decision, lines.get(decision.id, []))
            for decision in decisions}


def load_report(db, organization_id: int, start, end, plan: dict | None) -> dict:
    """Stored rows only. No provider call."""
    from ...models import BankTransaction
    from .books import classified_bank
    from .money_screens import org_partial_banner

    paired = classified_bank(db, organization_id, start, end, plan)
    ids = [txn.id for txn, _ in paired if txn.id is not None]
    recon = {}
    if ids:
        for row in (
            db.query(BankTransaction.id, BankTransaction.matched_entity_type, BankTransaction.matched_entity_id)
            .filter(
                BankTransaction.organization_id == organization_id,
                BankTransaction.id.in_(ids),
                BankTransaction.is_reconciled.is_(True),
            )
        ):
            if row.matched_entity_type and row.matched_entity_id is not None:
                recon[row.id] = (row.matched_entity_type, row.matched_entity_id)
    docs = load_match_docs(db, organization_id)
    open_keys = {(doc.entity_type, doc.id) for doc in docs}
    from ..manual_reconciliation import ManualReconciliationService
    service = ManualReconciliationService(db, organization_id=organization_id)
    for entity_type, entity_id in set(recon.values()):
        # A row's own auto match stays offered on it even when that document is now paid.
        if entity_type in ENTITY_TYPES and (entity_type, entity_id) not in open_keys:
            row = service.get_document(entity_type, entity_id)
            if row is not None:
                closed = document_for(entity_type, row) or MatchDoc(
                    entity_type, entity_id, _closed_effect(entity_type, row))
                closed.date = closed.date or getattr(row, "issue_date", None) or getattr(row, "expense_date", None)
                docs.append(closed)
    report = build_report(
        paired, recon, load_decisions(db, organization_id, ids), docs,
        taken=set(taken_documents(db, organization_id)), start=start, end=end,
    )
    report["start"] = start.isoformat()
    report["end"] = end.isoformat()
    report["partial_banner"] = org_partial_banner(db, organization_id)
    report["closing"] = closing_state(report["summary"], report["partial_banner"].get("bank_as_of"), report["end"])
    report["provider_calls"] = 0
    return report


# ---------------------------------------------------------------------- #
# Decide (one transaction; the caller commits)
# ---------------------------------------------------------------------- #
def _int_id(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _requested_documents(item: dict) -> list[tuple[str, int]]:
    raw = item.get("documents")
    if raw is None and item.get("entity_type") is not None:
        raw = [{"entity_type": item.get("entity_type"), "entity_id": item.get("entity_id")}]
    if not isinstance(raw, list) or not raw:
        raise ValueError("אישור דורש לפחות מסמך אחד: חשבונית, חשבון ספק או הוצאה")
    if len(raw) > MAX_DOCUMENTS:
        raise ValueError(f"עד {MAX_DOCUMENTS} מסמכים לתנועה")
    keys = []
    for line in raw:
        if not isinstance(line, dict) or line.get("entity_type") not in ENTITY_TYPES \
                or not _int_id(line.get("entity_id")):
            raise ValueError("אישור דורש מסמך: חשבונית, חשבון ספק או הוצאה")
        key = (line["entity_type"], line["entity_id"])
        if key in keys:
            raise ValueError("אותו מסמך נבחר פעמיים")
        keys.append(key)
    return keys


def _fee(item: dict) -> float | None:
    fee = item.get("fee")
    if fee is None:
        return None
    if isinstance(fee, bool) or not isinstance(fee, (int, float)) or fee < 0 or fee > 1e7:
        raise ValueError("עמלה חייבת להיות סכום אי-שלילי")
    return round(float(fee), 2) or None


def _release(db, service, txn, decision) -> None:
    """Undo an approval: delete its lines and clear the bank columns it wrote."""
    from ...models import BankMatchDocument
    lines = db.query(BankMatchDocument).filter(BankMatchDocument.decision_id == decision.id).all()
    as_dict = _decision_dict(decision, lines)
    if decision.status == "approved" and txn.is_reconciled \
            and (txn.matched_entity_type, txn.matched_entity_id) == expected_match(as_dict):
        service.assert_not_allocated(txn)
        service.clear_reconciled(txn)
    for line in lines:
        db.delete(line)
    db.flush()


def decide(db, organization_id: int, user_id: int | None, item: dict) -> dict:
    """Validate and stage one owner action. Flushes; the caller commits once or rolls back.

    The bank row's date and amount come from the database, not the client.
    Leaving an approved row undoes its bank match, but only when the bank
    row still holds what that approval wrote.
    """
    from ...models import BankMatchDecision, BankMatchDocument, BankTransaction
    from ..manual_reconciliation import ManualReconciliationService

    action = item.get("action")
    if action not in ACTIONS:
        raise ValueError("פעולה לא מוכרת")
    txn_id = item.get("transaction_id")
    if not _int_id(txn_id):
        raise ValueError("חסרה תנועת בנק")
    txn = db.get(BankTransaction, txn_id)
    if txn is None or txn.organization_id != organization_id:
        raise ValueError("התנועה לא נמצאה בארגון הזה")
    note = item.get("note")
    if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE):
        raise ValueError(f"הערה עד {MAX_NOTE} תווים")
    note = note.strip() if isinstance(note, str) and note.strip() else None

    service = ManualReconciliationService(db, organization_id=organization_id)
    decision = db.query(BankMatchDecision).filter(
        BankMatchDecision.organization_id == organization_id,
        BankMatchDecision.bank_transaction_id == txn.id,
    ).first()

    # Validate the new approval before touching anything.
    lines: list[MatchDoc] = []
    fee = None
    category = target = None
    if action in {"approve", "approve_category"}:
        service.assert_matchable(txn)
    if action == "approve":
        keys = _requested_documents(item)
        fee = _fee(item)
        own = {(line.entity_type, line.entity_id) for line in (
            db.query(BankMatchDocument).filter(BankMatchDocument.decision_id == decision.id).all()
            if decision is not None else []
        )}
        if txn.is_reconciled and txn.matched_entity_type in ENTITY_TYPES:
            own.add((txn.matched_entity_type, txn.matched_entity_id))
        taken = taken_documents(db, organization_id)
        for entity_type, entity_id in keys:
            row = service.get_document(entity_type, entity_id)
            if row is None:
                raise ValueError("המסמך לא נמצא בארגון הזה")
            if (entity_type, entity_id) in taken and (entity_type, entity_id) not in own:
                raise ValueError(f"המסמך {entity_type} #{entity_id} כבר מותאם לתנועת בנק אחרת")
            doc = document_for(entity_type, row)
            if doc is None and (entity_type, entity_id) not in own:
                raise ValueError(f"המסמך {entity_type} #{entity_id} סגור (שולם, בוטל או מבוטל)")
            if doc is None:
                doc = MatchDoc(entity_type, entity_id, _closed_effect(entity_type, row))
            lines.append(doc)
        bank = round(float(txn.amount), 2)
        explained = round(sum(doc.amount for doc in lines) - (fee or 0), 2)
        if abs(bank - explained) > TOLERANCE:
            raise ValueError(
                f"סכום המסמכים פחות העמלה ({explained:,.2f}) לא שווה לתנועת הבנק ({bank:,.2f}); "
                f"הפרש {bank - explained:,.2f}. הגדר עמלה או בחר מסמכים אחרים."
            )
    elif action == "approve_category":
        category = item.get("category")
        if category not in CATEGORIES:
            raise ValueError("קטגוריה לא מוכרת")
        target = item.get("target_account")
        target = target.strip() if isinstance(target, str) else ""
        if not ACCOUNT_RE.match(target):
            raise ValueError("אישור לפי קטגוריה דורש כרטיס יעד (מספר או שם כרטיס)")

    if decision is not None:
        _release(db, service, txn, decision)
    if action == "reopen":
        if decision is not None:
            db.delete(decision)
            db.flush()
        return {"status": "open"}

    if decision is None:
        decision = BankMatchDecision(organization_id=organization_id, bank_transaction_id=txn.id)
        db.add(decision)
    decision.status = "approved" if action in {"approve", "approve_category"} else action
    decision.kind = {"approve": "documents", "approve_category": "category"}.get(action)
    decision.category = category
    decision.target_account = target
    decision.fee_amount = fee
    decision.note = note
    decision.decided_by_user_id = user_id
    decision.decided_at = datetime.utcnow()
    db.flush()

    if action == "approve":
        for doc in lines:
            db.add(BankMatchDocument(
                organization_id=organization_id, decision_id=decision.id, bank_transaction_id=txn.id,
                entity_type=doc.entity_type, entity_id=doc.id, amount=round(doc.amount, 2),
            ))
        if len(lines) == 1 and not fee:
            service.mark_reconciled(txn, lines[0].entity_type, lines[0].id)
        else:
            service.mark_reconciled(txn, MULTI_MATCH, decision.id)
    elif action == "approve_category":
        service.mark_reconciled(txn, MULTI_MATCH, decision.id)
    db.flush()
    return {"status": decision.status, "decision_id": decision.id}


def _closed_effect(entity_type: str, row) -> float:
    """The signed effect of the row's own, now closed, document (re-approving its auto match)."""
    total = float(getattr(row, "total", 0) or 0) or float(getattr(row, "amount", 0) or 0)
    if entity_type == "invoice":
        return -abs(total) if _is_credit_invoice(row) else total
    return abs(total) if total < 0 else -total


def reject_plan_decisions(value) -> str | None:
    """Match decisions live in their own table. A plan never carries them."""
    if value in (None, {}, []):
        return None
    return "החלטות התאמת בנק נשמרות בטבלת ההתאמות, לא בתוכנית הדשבורד"
