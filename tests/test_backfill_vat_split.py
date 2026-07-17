"""TDD for scripts/backfill_vat_split.py — recompute VAT split for legacy synced
rows that were stored fully unsplit (subtotal == total, tax == 0), without any
external API calls. Dry-run by default; --apply writes; idempotent."""
import importlib.util
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "backfill_vat_split.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("backfill_vat_split", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backfill_vat_split"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def backfill_mod():
    return _load_script()


@pytest.fixture
def org_with_unsplit_and_split_rows(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Contact, ContactType, Invoice, InvoiceStatus, Bill, BillStatus, Expense

    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        cust = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="לקוח")
        vend = Contact(organization_id=org_id, contact_type=ContactType.VENDOR, name="ספק")
        db.add_all([cust, vend]); db.flush()

        # Legacy unsplit invoice (the bug fingerprint): subtotal==total, tax=0.
        unsplit_inv = Invoice(
            organization_id=org_id, contact_id=cust.id, invoice_number="LEGACY-1",
            issue_date=date(2026, 5, 10), due_date=date(2026, 6, 10),
            subtotal=Decimal("23600"), tax=Decimal("0"), total=Decimal("23600"),
            paid_amount=0, balance=Decimal("23600"), status=InvoiceStatus.SENT,
            source="sumit",
            raw_data={"document_id": "1", "total_amount": 23600.0, "vat_amount": 0.0,
                      "issue_date": "2026-05-10"},
        )
        db.add(unsplit_inv)

        # Already-correctly-split invoice — must be left untouched (idempotent no-op).
        split_inv = Invoice(
            organization_id=org_id, contact_id=cust.id, invoice_number="OK-1",
            issue_date=date(2026, 5, 11), due_date=date(2026, 6, 11),
            subtotal=Decimal("20000"), tax=Decimal("3600"), total=Decimal("23600"),
            paid_amount=0, balance=Decimal("23600"), status=InvoiceStatus.SENT,
            source="sumit", raw_data={"document_id": "2"},
        )
        db.add(split_inv)

        # Manual invoice, unsplit, zero VAT by deliberate user choice — must NOT be
        # touched (source != "sumit").
        manual_inv = Invoice(
            organization_id=org_id, contact_id=cust.id, invoice_number="MANUAL-1",
            issue_date=date(2026, 5, 12), due_date=date(2026, 6, 12),
            subtotal=Decimal("1000"), tax=Decimal("0"), total=Decimal("1000"),
            paid_amount=0, balance=Decimal("1000"), status=InvoiceStatus.SENT,
            source="manual",
        )
        db.add(manual_inv)

        # Legacy unsplit invoice where subtotal was left at the model default (0)
        # rather than mirroring total — the shape most likely for real pre-fix
        # rows (nothing ever set subtotal). Must still be caught.
        default_subtotal_inv = Invoice(
            organization_id=org_id, contact_id=cust.id, invoice_number="LEGACY-2",
            issue_date=date(2026, 5, 13), due_date=date(2026, 6, 13),
            subtotal=Decimal("0"), tax=Decimal("0"), total=Decimal("1180"),
            paid_amount=0, balance=Decimal("1180"), status=InvoiceStatus.SENT,
            source="sumit",
            raw_data={"document_id": "10", "total_amount": 1180.0, "vat_amount": 0.0,
                      "issue_date": "2026-05-13"},
        )
        db.add(default_subtotal_inv)

        # Legacy unsplit bill.
        unsplit_bill = Bill(
            organization_id=org_id, vendor_id=vend.id, bill_number="LB-1",
            issue_date=date(2026, 5, 8), due_date=date(2026, 6, 8),
            subtotal=Decimal("11800"), tax=Decimal("0"), total=Decimal("11800"),
            paid_amount=Decimal("11800"), balance=0, status=BillStatus.PAID,
            source="sumit", raw_data={"document_id": "3", "issue_date": "2026-05-08"},
        )
        db.add(unsplit_bill)

        # Legacy unsplit expense (filed).
        unsplit_exp = Expense(
            organization_id=org_id, external_id="9", source="sumit",
            supplier_name="ספק הוצאה", amount=Decimal("2360"), vat_amount=Decimal("0"),
            total=Decimal("2360"), expense_date=date(2026, 5, 15), status="filed",
            raw_data={"document_id": "9", "issue_date": "2026-05-15"},
        )
        db.add(unsplit_exp)

        db.commit()
        return {
            "org_id": org_id,
            "unsplit_invoice_id": unsplit_inv.id,
            "default_subtotal_invoice_id": default_subtotal_inv.id,
            "split_invoice_id": split_inv.id,
            "manual_invoice_id": manual_inv.id,
            "unsplit_bill_id": unsplit_bill.id,
            "unsplit_expense_id": unsplit_exp.id,
        }
    finally:
        db.close()


def test_dry_run_identifies_candidates_without_writing(backfill_mod, org_with_unsplit_and_split_rows):
    from cfo.database import SessionLocal
    from cfo.models import Invoice, Bill, Expense

    ctx = org_with_unsplit_and_split_rows
    reports = backfill_mod.run(ctx["org_id"], apply=False)
    by_entity = {r.entity: r for r in reports}

    assert by_entity["invoices"].candidates == 2  # unsplit + default-subtotal sumit rows
    assert by_entity["bills"].candidates == 1
    assert by_entity["expenses"].candidates == 1
    assert ctx["unsplit_invoice_id"] in by_entity["invoices"].changed_ids
    assert ctx["default_subtotal_invoice_id"] in by_entity["invoices"].changed_ids
    assert ctx["split_invoice_id"] not in by_entity["invoices"].changed_ids
    assert ctx["manual_invoice_id"] not in by_entity["invoices"].changed_ids

    # Dry-run must not touch the DB.
    db = SessionLocal()
    try:
        row = db.query(Invoice).get(ctx["unsplit_invoice_id"])
        assert row.tax == Decimal("0")
        assert row.subtotal == Decimal("23600")
    finally:
        db.close()


def test_apply_recomputes_split_and_matches_expected(backfill_mod, org_with_unsplit_and_split_rows):
    from cfo.database import SessionLocal
    from cfo.models import Invoice, Bill, Expense

    ctx = org_with_unsplit_and_split_rows
    backfill_mod.run(ctx["org_id"], apply=True)

    db = SessionLocal()
    try:
        inv = db.query(Invoice).get(ctx["unsplit_invoice_id"])
        assert inv.tax == Decimal("3600.00")
        assert inv.subtotal == Decimal("20000.00")
        assert inv.subtotal + inv.tax == inv.total

        default_inv = db.query(Invoice).get(ctx["default_subtotal_invoice_id"])
        assert default_inv.tax == Decimal("180.00")
        assert default_inv.subtotal == Decimal("1000.00")
        assert default_inv.subtotal + default_inv.tax == default_inv.total

        # Untouched rows stay untouched.
        split_inv = db.query(Invoice).get(ctx["split_invoice_id"])
        assert split_inv.tax == Decimal("3600")
        assert split_inv.subtotal == Decimal("20000")

        manual_inv = db.query(Invoice).get(ctx["manual_invoice_id"])
        assert manual_inv.tax == Decimal("0")
        assert manual_inv.subtotal == Decimal("1000")

        bill = db.query(Bill).get(ctx["unsplit_bill_id"])
        assert bill.tax == Decimal("1800.00")
        assert bill.subtotal + bill.tax == bill.total

        exp = db.query(Expense).get(ctx["unsplit_expense_id"])
        assert exp.vat_amount == Decimal("360.00")
        assert exp.amount + exp.vat_amount == exp.total
    finally:
        db.close()


def test_apply_is_idempotent(backfill_mod, org_with_unsplit_and_split_rows):
    ctx = org_with_unsplit_and_split_rows
    backfill_mod.run(ctx["org_id"], apply=True)
    second_pass = backfill_mod.run(ctx["org_id"], apply=True)
    for report in second_pass:
        assert report.candidates == 0, f"{report.entity} still had candidates on 2nd pass"


def test_explicit_nonzero_vat_in_raw_data_wins_over_derivation(backfill_mod, fresh_org):
    """When raw_data DOES carry a real explicit non-zero VAT figure, trust it over
    the standard-rate derivation (matches the live connector's precedence)."""
    from cfo.database import SessionLocal
    from cfo.models import Contact, ContactType, Invoice, InvoiceStatus

    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        cust = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="לקוח")
        db.add(cust); db.flush()
        inv = Invoice(
            organization_id=org_id, contact_id=cust.id, invoice_number="EXPLICIT-1",
            issue_date=date(2026, 5, 20), due_date=date(2026, 6, 20),
            subtotal=Decimal("1180"), tax=Decimal("0"), total=Decimal("1180"),
            paid_amount=0, balance=Decimal("1180"), status=InvoiceStatus.SENT,
            source="sumit", raw_data={"VAT": 100, "issue_date": "2026-05-20"},
        )
        db.add(inv); db.commit()
        inv_id = inv.id
    finally:
        db.close()

    backfill_mod.run(org_id, apply=True)

    db = SessionLocal()
    try:
        row = db.query(Invoice).get(inv_id)
        assert row.tax == Decimal("100")  # explicit VAT, NOT the 180 an 18% split would give
        assert row.subtotal == Decimal("1080")
    finally:
        db.close()
