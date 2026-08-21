"""W6.5 — בקרות ספרים שוטפות כ-invariants ב-data_quality.

הפערים (SWOT #7-8): איזון חובה=זכות נבדק רק כשמבקשים דוח; אין בדיקת
רצף מספרי מסמכים (חשיפה מול רשות המסים); זיהוי כפילויות רק לפי
external_id — כפילות ידנית (אותו ספק+סכום+תאריך) עוברת בשקט.
"""
from datetime import date
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import Bill, BillStatus, Contact, ContactType, Invoice, InvoiceStatus
from cfo.services import data_quality


def _names(result):
    return {c["name"] for c in result["checks"]}


def test_new_invariants_are_registered(client, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = data_quality.run_checks(db, org_id)
    finally:
        db.close()
    assert {"trial_balance_balanced", "document_number_continuity",
            "near_duplicate_bills"} <= _names(result)


def test_document_number_gap_is_detected(client, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        for num in ("1001", "1002", "1005"):
            db.add(Invoice(
                organization_id=org_id, invoice_number=num,
                issue_date=date(2026, 7, 1), due_date=date(2026, 7, 30),
                total=Decimal("100"), status=InvoiceStatus.SENT,
            ))
        db.commit()
        result = data_quality.run_checks(db, org_id)
        check = next(c for c in result["checks"]
                     if c["name"] == "document_number_continuity")
        assert check["passed"] is False
        assert "1003" in check["details"] or "פער" in check["details"]
    finally:
        db.close()


def test_continuous_numbering_passes(client, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        for num in ("2001", "2002", "2003"):
            db.add(Invoice(
                organization_id=org_id, invoice_number=num,
                issue_date=date(2026, 7, 1), due_date=date(2026, 7, 30),
                total=Decimal("100"), status=InvoiceStatus.SENT,
            ))
        db.commit()
        result = data_quality.run_checks(db, org_id)
        check = next(c for c in result["checks"]
                     if c["name"] == "document_number_continuity")
        assert check["passed"] is True
    finally:
        db.close()


def test_near_duplicate_bills_detected_without_external_id(client, fresh_org):
    """שני חשבונות ספק זהים (ספק+סכום+תאריך) בלי external_id — בדיוק
    התרחיש שניפח ₪150K בעבר (duplicate_gate docstring)."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        vendor = Contact(organization_id=org_id, name="ספק כפול",
                         contact_type=ContactType.VENDOR)
        db.add(vendor)
        db.flush()
        for _ in range(2):
            db.add(Bill(
                organization_id=org_id, vendor_id=vendor.id,
                issue_date=date(2026, 7, 10), total=Decimal("1500"),
                status=BillStatus.RECEIVED,
            ))
        db.commit()
        result = data_quality.run_checks(db, org_id)
        check = next(c for c in result["checks"]
                     if c["name"] == "near_duplicate_bills")
        assert check["passed"] is False
    finally:
        db.close()
