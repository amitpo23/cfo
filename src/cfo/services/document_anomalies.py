"""Document anomaly detection (זיהוי מסמכים חריגים).

Deterministic checks over synced SUMIT documents that catch filing mistakes like the
real one we found — doc 120000, a ₪266,833 "sale" to שופרסל (a supplier), with no
allocation number, ~12× the next-largest invoice. The checks:

  magnitude_outlier   — an invoice far larger than the rest of the book
  missing_allocation  — a large taxable invoice with no חשבונית-ישראל allocation number
  vendor_as_customer  — an invoice issued to a contact that is actually a supplier
  duplicate_expense   — two bills from the same vendor, same amount, within a few
                        days of each other, or sharing the same bill_number —
                        likely the same expense filed twice

Each check is conservative (flags for human review, never auto-mutates SUMIT) and
returns a structured finding. Thresholds carry a `verify` note where they update.
"""
from __future__ import annotations

import statistics
from typing import Any

SEV_INFO, SEV_MED, SEV_HIGH = "info", "medium", "high"

# חשבונית ישראל: סכום שמעליו נדרש מספר הקצאה. יורד שנתית — לאימות מול רשות המסים.
ALLOCATION_THRESHOLD = 20000.0          # ₪ (2025; 2026 verify)
OUTLIER_MIN_ABS = 50000.0               # below this, never flag as magnitude outlier
OUTLIER_FACTOR = 8.0                    # flag if abs(total) > FACTOR × median of the rest
DUPLICATE_DATE_WINDOW_DAYS = 3           # same vendor+amount within this many days


def _f(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _finding(atype, severity, title, message, *, refs) -> dict[str, Any]:
    return {"type": atype, "severity": severity, "title": title,
            "message": message, "refs": refs}


def detect_document_anomalies(db, organization_id: int) -> list[dict[str, Any]]:
    from ..models import Invoice, Bill, Contact, InvoiceStatus, ContactType

    invoices = [
        i for i in db.query(Invoice).filter(Invoice.organization_id == organization_id).all()
        if i.status not in {InvoiceStatus.DRAFT, InvoiceStatus.VOID, InvoiceStatus.CANCELLED}
    ]
    findings: list[dict[str, Any]] = []

    # Vendor tax-ids and vendor contact-ids, for the supplier-as-customer check.
    bills = db.query(Bill).filter(Bill.organization_id == organization_id).all()
    vendor_contact_ids = {b.vendor_id for b in bills if b.vendor_id}
    contacts = {c.id: c for c in db.query(Contact).filter(
        Contact.organization_id == organization_id).all()}
    vendor_tax_ids = {
        (contacts[cid].tax_id or "").strip()
        for cid in vendor_contact_ids if cid in contacts and contacts[cid].tax_id
    }

    totals = [abs(_f(i.total)) for i in invoices]

    for inv in invoices:
        total = abs(_f(inv.total))
        label = inv.invoice_number or f"#{inv.id}"
        contact = contacts.get(inv.contact_id)
        cust_name = contact.name if contact else "לקוח"

        # 1) Magnitude outlier — compare against the median of the OTHER invoices.
        others = [t for t in totals if t is not total]
        if len(others) >= 3:
            median = statistics.median(others)
            if median > 0 and total >= OUTLIER_MIN_ABS and total > OUTLIER_FACTOR * median:
                findings.append(_finding(
                    "magnitude_outlier", SEV_HIGH,
                    f"חשבונית חריגה בסדר גודל: {label} — ₪{total:,.0f}",
                    f"חשבונית {label} ל\"{cust_name}\" על ₪{total:,.0f} גדולה פי "
                    f"~{total/median:.0f} מהחציון (₪{median:,.0f}). בדוק אם זו טעות תיוק.",
                    refs={"invoice_id": inv.id, "total": total},
                ))

        # 2) Large taxable invoice without an allocation number (חשבונית ישראל).
        if total >= ALLOCATION_THRESHOLD and not (inv.allocation_number or "").strip():
            findings.append(_finding(
                "missing_allocation", SEV_MED,
                f"חסר מספר הקצאה: {label} — ₪{total:,.0f}",
                f"חשבונית {label} על ₪{total:,.0f} מעל סף חשבונית-ישראל (₪{ALLOCATION_THRESHOLD:,.0f}) "
                f"אך ללא מספר הקצאה. ודא הקצאה מול רשות המסים או שזו אינה חשבונית מס.",
                refs={"invoice_id": inv.id, "total": total},
            ))

        # 3) Invoice issued to a contact that is actually a supplier.
        is_vendor = (
            inv.contact_id in vendor_contact_ids
            or (contact is not None and contact.contact_type == ContactType.VENDOR)
            or (contact is not None and (contact.tax_id or "").strip() in vendor_tax_ids
                and (contact.tax_id or "").strip())
        )
        if is_vendor:
            findings.append(_finding(
                "vendor_as_customer", SEV_HIGH,
                f"ספק מתויק כלקוח: {label} — \"{cust_name}\"",
                f"חשבונית {label} הופקה ל\"{cust_name}\" שמופיע כספק במערכת. "
                f"ייתכן שזו הוצאה שתויקה בטעות כמסמך יוצא.",
                refs={"invoice_id": inv.id, "contact_id": inv.contact_id},
            ))

    findings.extend(_detect_duplicate_expenses(bills, contacts))

    return findings


def _detect_duplicate_expenses(bills: list, contacts: dict) -> list[dict[str, Any]]:
    """Flag pairs of bills that look like the same expense filed twice:
    same vendor+amount within DUPLICATE_DATE_WINDOW_DAYS, or the same
    bill_number reused across two rows."""
    from ..models import BillStatus

    bills = [b for b in bills if b.status not in {BillStatus.DRAFT, BillStatus.VOID}]
    findings: list[dict[str, Any]] = []
    flagged_pairs: set[tuple[int, int]] = set()

    for i, a in enumerate(bills):
        for b in bills[i + 1:]:
            pair = (min(a.id, b.id), max(a.id, b.id))
            if pair in flagged_pairs:
                continue

            same_number = bool(a.bill_number) and a.bill_number == b.bill_number
            same_vendor_amount_close_date = (
                a.vendor_id is not None
                and a.vendor_id == b.vendor_id
                and _f(a.total) == _f(b.total)
                and a.issue_date is not None and b.issue_date is not None
                and abs((a.issue_date - b.issue_date).days) <= DUPLICATE_DATE_WINDOW_DAYS
            )
            if not (same_number or same_vendor_amount_close_date):
                continue

            flagged_pairs.add(pair)
            contact = contacts.get(a.vendor_id)
            vendor_name = contact.name if contact else "ספק"
            reason = "אותו מספר מסמך" if same_number else "אותו ספק+סכום בטווח ימים קרוב"
            findings.append(_finding(
                "duplicate_expense", SEV_MED,
                f"חשד לכפילות הוצאה: {a.bill_number or a.id} / {b.bill_number or b.id}",
                f"שתי הוצאות מ\"{vendor_name}\" על ₪{_f(a.total):,.0f} ({reason}) — "
                f"תאריכים {a.issue_date} ו-{b.issue_date}. בדוק אם זו אותה הוצאה שתויקה פעמיים.",
                refs={"bill_id_a": a.id, "bill_id_b": b.id},
            ))

    return findings


def persist_anomalies(db, organization_id: int) -> dict[str, int]:
    """Run detection and upsert each finding as a CfoInsight (idempotent).

    Lets anomalies live in the same insights stream as bank insights — surviving
    across runs and surfacing in the insights dashboard, not only the engine view.
    """
    from ..models import CfoInsight

    findings = detect_document_anomalies(db, organization_id)
    created = updated = 0
    for f in findings:
        inv_id = f["refs"].get("invoice_id")
        fingerprint = f"docanom:{f['type']}:{inv_id}"
        row = db.query(CfoInsight).filter(
            CfoInsight.organization_id == organization_id,
            CfoInsight.fingerprint == fingerprint,
        ).first()
        action = "בדוק את המסמך ב-SUMIT ותקן/בטל אם זו טעות תיוק."
        if row:
            row.severity, row.title, row.message = f["severity"], f["title"], f["message"]
            row.evidence, row.recommended_action = f["refs"], action
            if row.status == "resolved":
                row.status = "active"
            updated += 1
        else:
            db.add(CfoInsight(
                organization_id=organization_id, fingerprint=fingerprint,
                insight_type=f["type"], severity=f["severity"],
                title=f["title"], message=f["message"], evidence=f["refs"],
                recommended_action=action, status="active",
            ))
            created += 1
    db.commit()
    return {"created": created, "updated": updated, "total": len(findings)}
