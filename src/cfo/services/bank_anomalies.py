"""
Morning bank-anomaly scan (PR2 of the bookkeeper daily-cycle plan).

Scans `BankTransaction` rows for description patterns that indicate a
bounced check, a failed standing order, or a returned/refused debit — the
kind of thing a bookkeeper needs to see and act on the same morning it
happens, not weeks later during reconciliation.

Taxonomy note: the spec's `kind` field has exactly three values
(bounced_check / failed_standing_order / returned_debit). Generic
refused-payment/dishonour fee wording ("עמלת החזרה", "אי כיבוד") doesn't
identify *which* instrument was returned, so those hits fold into
`returned_debit` — "something got returned"; there's no fourth bucket.

Each hit is upserted into CfoInsight (insight_type="bank_anomaly"),
deduped by a fingerprint keyed on the BankTransaction id (one insight per
transaction, updated in place on re-scan rather than duplicated).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models import BankTransaction, CfoInsight

INSIGHT_TYPE = "bank_anomaly"
BOUNCED_CHECK_ESCALATION_THRESHOLD = 5000

BOUNCED_CHECK_KEYWORDS = ["שיק חוזר", "החזרת שיק", "שיק שחזר", "צ'ק חוזר"]
FAILED_STANDING_ORDER_KEYWORDS = [
    "הוראת קבע שלא כובדה", 'החזרת הו"ק', 'הו"ק שלא כובדה', "ה.ק שלא כובדה",
]
RETURNED_DEBIT_KEYWORDS = ["החזרת חיוב", "ביטול חיוב", "חיוב שהוחזר"]
# Refused-payment / dishonour fee wording — folded into returned_debit, see
# module docstring.
REFUSED_PAYMENT_FEE_KEYWORDS = ["עמלת החזרה", "אי כיבוד"]

KIND_LABELS = {
    "bounced_check": "שיק חוזר",
    "failed_standing_order": "הוראת קבע שלא כובדה",
    "returned_debit": "חיוב שהוחזר",
}


def _norm(text: str) -> str:
    """Whitespace-collapse + casefold for tolerant substring matching."""
    return " ".join((text or "").split()).casefold()


def _matches(haystack: str, keywords: list[str]) -> bool:
    h = _norm(haystack)
    return any(_norm(k) in h for k in keywords)


def _classify(description: str) -> str | None:
    if _matches(description, BOUNCED_CHECK_KEYWORDS):
        return "bounced_check"
    if _matches(description, FAILED_STANDING_ORDER_KEYWORDS):
        return "failed_standing_order"
    if _matches(description, RETURNED_DEBIT_KEYWORDS) or _matches(description, REFUSED_PAYMENT_FEE_KEYWORDS):
        return "returned_debit"
    return None


def scan_bank_anomalies(db: Session, organization_id: int, since: date) -> list[dict[str, Any]]:
    """Scan BankTransaction rows since `since` for anomaly keyword hits."""
    rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.organization_id == organization_id,
            BankTransaction.transaction_date >= since,
        )
        .all()
    )
    hits: list[dict[str, Any]] = []
    for t in rows:
        description = t.description or ""
        kind = _classify(description)
        if kind is None:
            continue
        hits.append({
            "kind": kind,
            "transaction_id": t.id,
            "amount": float(t.amount or 0),
            "date": t.transaction_date.isoformat() if t.transaction_date else None,
            "description": description,
        })
    return hits


def scan_and_alert(db: Session, organization_id: int, since: date) -> dict[str, Any]:
    """Run `scan_bank_anomalies` and upsert a fingerprinted CfoInsight per hit."""
    hits = scan_bank_anomalies(db, organization_id, since)
    created = updated = 0
    insight_ids: list[int] = []
    now = datetime.utcnow()

    for h in hits:
        fingerprint = f"bank_anomaly:{h['transaction_id']}"
        amount = abs(h["amount"])
        severity = "high"
        if h["kind"] == "bounced_check" and amount > BOUNCED_CHECK_ESCALATION_THRESHOLD:
            severity = "critical"

        kind_label = KIND_LABELS[h["kind"]]
        title = f"{kind_label}: ₪{amount:,.2f} בתאריך {h['date']}"
        message = (
            f"{kind_label}: ₪{amount:,.2f} מ-{h['description']} בתאריך {h['date']} — טיפול היום."
        )
        evidence = {
            "kind": h["kind"], "transaction_id": h["transaction_id"],
            "amount": h["amount"], "date": h["date"], "description": h["description"],
        }
        recommended_action = "פנה ללקוח/ספק ולבנק לבירור מיידי."

        existing = db.query(CfoInsight).filter(
            CfoInsight.organization_id == organization_id,
            CfoInsight.fingerprint == fingerprint,
        ).first()
        if existing:
            existing.insight_type = INSIGHT_TYPE
            existing.severity = severity
            existing.title = title
            existing.message = message
            existing.evidence = evidence
            existing.recommended_action = recommended_action
            if existing.status == "resolved":
                existing.status = "active"
                existing.resolved_at = None
            existing.updated_at = now
            updated += 1
            insight_ids.append(existing.id)
        else:
            row = CfoInsight(
                organization_id=organization_id,
                fingerprint=fingerprint,
                insight_type=INSIGHT_TYPE,
                severity=severity,
                title=title,
                message=message,
                evidence=evidence,
                recommended_action=recommended_action,
                status="active",
            )
            db.add(row)
            db.flush()
            created += 1
            insight_ids.append(row.id)

    db.commit()
    return {"created": created, "updated": updated, "scanned": len(hits), "insight_ids": insight_ids}
