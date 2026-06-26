"""Document anomaly detection (זיהוי מסמכים חריגים).

Deterministic checks over synced SUMIT documents that catch filing mistakes like the
real one we found — doc 120000, a ₪266,833 "sale" to שופרסל (a supplier), with no
allocation number, ~12× the next-largest invoice. The checks:

  magnitude_outlier   — an invoice far larger than the rest of the book
  missing_allocation  — a large taxable invoice with no חשבונית-ישראל allocation number
  vendor_as_customer  — an invoice issued to a contact that is actually a supplier

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
    if not invoices:
        return findings

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
