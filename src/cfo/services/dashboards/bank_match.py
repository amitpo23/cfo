"""Bank match: one bank row against one book document, decided by the owner.

Three owner actions per BOOKED row: אשר (approve a document), בדיקה (check)
and חסר מסמך (missing document). A candidate document is a suggestion. A row
the nightly auto-reconcile matched still waits for the owner's אשר.

אשר writes the existing ``BankTransaction`` match columns through
``ManualReconciliationService``. The plan keeps the decision itself under
``bankMatchDecisions``, with the date and amount bound from the bank row.
Nothing is posted to SUMIT. No candidate is an empty list, not a 0.
"""
from __future__ import annotations

from ..bank_reconciliation import BankTxnLite, DocLite, _score
from .filing import Txn, displayed_counterparty

STATUSES = ("approved", "check", "missing_doc")
ACTIONS = {"approve", "check", "missing_doc", "reopen"}
ENTITY_TYPES = {"invoice", "bill", "expense"}
MAX_NOTE = 300
MAX_CANDIDATES = 3
MIN_SCORE = 0.3
STATUS_HE = {
    "approved": "אושר",
    "check": "בבדיקה",
    "missing_doc": "חסר מסמך",
    "open": "ממתין להחלטה",
}


def _types_for(amount: float) -> set[str]:
    return {"invoice"} if amount > 0 else {"bill", "expense"}


def _status(txn_id, recon: dict, decisions: dict) -> tuple[str, dict | None]:
    decision = decisions.get(str(txn_id))
    matched = recon.get(txn_id)
    if isinstance(decision, dict):
        status = decision.get("status")
        if status == "approved":
            if matched == (decision.get("entity_type"), decision.get("entity_id")):
                return "approved", decision
            return "open", None
        if status in STATUSES:
            return status, decision
    return "open", None


def candidates_for(txn: Txn, docs: list[DocLite], taken: set[tuple[str, int]]) -> list[dict]:
    """Up to three scored documents in the row's direction. A taken document is not offered."""
    if not txn.amount:
        return []
    party = displayed_counterparty(txn)
    lite = BankTxnLite(
        id=txn.id, amount=float(txn.amount), date=_as_date(txn.date),
        description=" ".join(part for part in (txn.description, party) if part),
    )
    wanted = _types_for(txn.amount)
    found = []
    for doc in docs:
        if doc.entity_type not in wanted or (doc.entity_type, doc.id) in taken:
            continue
        score = _score(lite, doc, amount_tol=0.02, date_window=7)
        if score is None or score < MIN_SCORE:
            continue
        found.append({
            "entity_type": doc.entity_type,
            "entity_id": doc.id,
            "score": round(score, 3),
            "amount": round(doc.amount, 2),
            "date": doc.date.isoformat() if doc.date else None,
            "name": doc.name or "",
        })
    found.sort(key=lambda item: (-item["score"], item["entity_type"], item["entity_id"]))
    return found[:MAX_CANDIDATES]


def _as_date(value):
    from datetime import date
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _bucket(rows: list[dict], status: str | None = None) -> dict:
    picked = rows if status is None else [row for row in rows if row["status"] == status]
    return {"count": len(picked), "amount": round(sum(row["amount"] for row in picked), 2)}


def build_report(paired, recon: dict, decisions: dict | None, docs: list[DocLite]) -> dict:
    """Rows, candidates and a signed summary. ``recon`` maps txn id → (entity_type, entity_id)."""
    decisions = decisions if isinstance(decisions, dict) else {}
    resolved = []
    taken: set[tuple[str, int]] = set()
    for txn, filed in paired:
        status, decision = _status(txn.id, recon, decisions)
        resolved.append((txn, filed, status, decision))
        if status == "approved":
            taken.add((decision["entity_type"], decision["entity_id"]))
    by_key = {(doc.entity_type, doc.id): doc for doc in docs}
    rows = []
    for txn, filed, status, decision in resolved:
        auto = recon.get(txn.id) if status != "approved" else None
        row = {
            "id": txn.id,
            "date": txn.date,
            "amount": round(float(txn.amount), 2),
            "counterparty": displayed_counterparty(txn),
            "description": txn.description or "",
            "category": filed.category,
            "status": status,
            "status_he": STATUS_HE[status],
            "note": (decision or {}).get("note") or None,
            "matched": None,
            "auto_match": {"entity_type": auto[0], "entity_id": auto[1]} if auto else None,
            "candidates": [],
        }
        if status == "approved":
            row["matched"] = {"entity_type": decision["entity_type"], "entity_id": decision["entity_id"]}
        elif status == "open":
            row["candidates"] = candidates_for(txn, docs, taken)
            doc = by_key.get(auto) if auto else None
            if doc is not None and not any(
                (item["entity_type"], item["entity_id"]) == auto for item in row["candidates"]
            ):
                row["candidates"].insert(0, {
                    "entity_type": doc.entity_type, "entity_id": doc.id, "score": None,
                    "amount": round(doc.amount, 2),
                    "date": doc.date.isoformat() if doc.date else None, "name": doc.name or "",
                })
        rows.append(row)
    summary = {status: _bucket(rows, status) for status in (*STATUSES, "open")}
    summary["total"] = _bucket(rows)
    parts = [summary[status] for status in (*STATUSES, "open")]
    summary["balanced"] = (
        sum(part["count"] for part in parts) == summary["total"]["count"]
        and abs(sum(part["amount"] for part in parts) - summary["total"]["amount"]) < 0.01
    )
    summary["done"] = summary["total"]["count"] > 0 and summary["open"]["count"] == 0
    return {"rows": rows, "summary": summary, "status_labels": STATUS_HE}


def closing_state(summary: dict, bank_as_of: str | None, end: str) -> dict:
    """Whether the window is decided, and up to which bank date. No rows is not done."""
    total = summary["total"]["count"]
    open_count = summary["open"]["count"]
    if total == 0:
        return {"done": False, "label_he": "אין תנועות בנק שמורות בטווח. זה לא מאוזן — זה חסר."}
    if open_count:
        return {"done": False, "label_he": f"עדיין לא מאוזן — {open_count} תנועות ממתינות להחלטה"}
    if not bank_as_of:
        return {"done": True, "label_he": "כל התנועות השמורות הוכרעו. תאריך הבנק חסר."}
    if bank_as_of < end:
        ddmm = f"{bank_as_of[8:10]}.{bank_as_of[5:7]}"
        return {"done": True, "label_he": f"כל התנועות הוכרעו עד {ddmm} — הבנק לא מעודכן אחרי התאריך הזה"}
    return {"done": True, "label_he": "כל התנועות בטווח הוכרעו"}


def load_report(db, organization_id: int, start, end, plan: dict | None) -> dict:
    """Stored rows only. No provider call."""
    from ...models import BankTransaction
    from ..bank_reconciliation import load_docs_for_org
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
    invoices, bills, expenses = load_docs_for_org(db, organization_id)
    decisions = (plan or {}).get("bankMatchDecisions") if isinstance(plan, dict) else None
    report = build_report(paired, recon, decisions, [*invoices, *bills, *expenses])
    report["start"] = start.isoformat()
    report["end"] = end.isoformat()
    report["partial_banner"] = org_partial_banner(db, organization_id)
    report["closing"] = closing_state(report["summary"], report["partial_banner"].get("bank_as_of"), report["end"])
    report["provider_calls"] = 0
    return report


def plan_decision(db, organization_id: int, plan: dict | None, item: dict) -> tuple[dict, tuple | None]:
    """Validate one owner action. Returns the new plan and the database effect.

    Nothing is written here. The caller saves the plan first and then runs
    the effect with ``run_effect``. If the effect fails after the plan is
    saved, the approval is stale and the row shows as open again.

    The bank row's date and amount come from the database, not the client.
    אשר needs a document of this organization. Leaving an approved row
    (בדיקה, חסר מסמך, פתח מחדש) undoes its database match, but only when the
    database still holds the document that was approved.
    """
    from ...models import BankTransaction
    from ..manual_reconciliation import ManualReconciliationService

    action = item.get("action")
    if action not in ACTIONS:
        raise ValueError("פעולה לא מוכרת")
    txn_id = item.get("transaction_id")
    if isinstance(txn_id, bool) or not isinstance(txn_id, int) or txn_id <= 0:
        raise ValueError("חסרה תנועת בנק")
    txn = db.get(BankTransaction, txn_id)
    if txn is None or txn.organization_id != organization_id:
        raise ValueError("התנועה לא נמצאה בארגון הזה")
    note = item.get("note")
    if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE):
        raise ValueError(f"הערה עד {MAX_NOTE} תווים")

    plan = dict(plan or {})
    decisions = {
        str(key): dict(value)
        for key, value in (plan.get("bankMatchDecisions") or {}).items()
        if isinstance(value, dict)
    }
    key = str(txn.id)
    previous = decisions.get(key) or {}
    service = ManualReconciliationService(db, organization_id=organization_id)

    effect = None
    if action == "approve":
        entity_type = item.get("entity_type")
        entity_id = item.get("entity_id")
        if entity_type not in ENTITY_TYPES or isinstance(entity_id, bool) or not isinstance(entity_id, int):
            raise ValueError("אישור דורש מסמך: חשבונית, חשבון ספק או הוצאה")
        if txn.is_provisional:
            raise ValueError("תנועה זמנית לא מותאמת סופית")
        service._assert_not_allocated(txn)
        if service._load_entity(entity_type, entity_id) is None:
            raise ValueError("המסמך לא נמצא בארגון הזה")
        effect = ("match", txn.id, entity_type, entity_id)
        decision = {"status": "approved", "entity_type": entity_type, "entity_id": entity_id}
    else:
        if (
            previous.get("status") == "approved" and txn.is_reconciled
            and (txn.matched_entity_type, txn.matched_entity_id)
            == (previous.get("entity_type"), previous.get("entity_id"))
        ):
            service._assert_not_allocated(txn)
            effect = ("unmatch", txn.id, previous.get("entity_type"), previous.get("entity_id"))
        if action == "reopen":
            decisions.pop(key, None)
            plan["bankMatchDecisions"] = decisions
            return plan, effect
        decision = {"status": action}

    when = txn.transaction_date
    decision.update({
        "organizationId": txn.organization_id,
        "date": when.isoformat() if hasattr(when, "isoformat") else str(when),
        "amount": round(float(txn.amount), 2),
    })
    if isinstance(note, str) and note.strip():
        decision["note"] = note.strip()
    decisions[key] = decision
    plan["bankMatchDecisions"] = decisions
    return plan, effect


def run_effect(db, organization_id: int, effect: tuple | None) -> None:
    """Write the match columns after the plan is saved. Unmatch re-checks the stored document."""
    from ...models import BankTransaction
    from ..manual_reconciliation import ManualReconciliationService

    if effect is None:
        return
    kind, txn_id, entity_type, entity_id = effect
    service = ManualReconciliationService(db, organization_id=organization_id)
    if kind == "match":
        service.match_transaction(txn_id, entity_type, entity_id)
        return
    txn = db.get(BankTransaction, txn_id)
    if txn is not None and txn.organization_id == organization_id and txn.is_reconciled \
            and (txn.matched_entity_type, txn.matched_entity_id) == (entity_type, entity_id):
        service.unmatch_transaction(txn_id)


def validate_decisions(value, limit: int) -> str | None:
    """Plan validator. Returns a Hebrew error or None."""
    if value is None:
        return None
    if not isinstance(value, dict):
        return "החלטות ההתאמה חייבות להיות אובייקט"
    if len(value) > limit:
        return f"אפשר לשמור עד {limit} החלטות התאמה"
    for key, item in value.items():
        if not str(key).isdigit() or not isinstance(item, dict):
            return "החלטת התאמה לא תקינה"
        if item.get("status") not in STATUSES:
            return "סטטוס ההתאמה אינו מוכר"
        amount = item.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or abs(amount) > 1e9:
            return "סכום ההתאמה לא תקין"
        if not isinstance(item.get("organizationId"), int) or not isinstance(item.get("date"), str):
            return "להחלטת ההתאמה חסרים ארגון או תאריך"
        note = item.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE):
            return f"הערה עד {MAX_NOTE} תווים"
        if item["status"] == "approved":
            entity_id = item.get("entity_id")
            if item.get("entity_type") not in ENTITY_TYPES or isinstance(entity_id, bool) or not isinstance(entity_id, int):
                return "אישור התאמה דורש מסמך"
    return None
