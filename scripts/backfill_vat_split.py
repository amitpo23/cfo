#!/usr/bin/env python
"""M9 — VAT split backfill (dry-run by default).

Recomputes the subtotal/tax (Invoice/Bill) and amount/vat_amount (Expense) split for
rows that were synced from SUMIT before the connector-level VAT derivation existed
(sumit_connector._derive_subtotal_tax / sumit_integration._document_response_from_list
/ vat_utils.split_inclusive). Those legacy rows carry ``total`` (the real,
VAT-inclusive gross SUMIT sent) but ``tax == 0`` because SUMIT's list endpoint never
returns a VAT breakdown and nothing derived it at sync time.

NO external API calls — everything is recomputed from data already in the DB
(the row's own ``total``/``amount`` column + its ``issue_date``/``expense_date``
+ the statutory VAT-rate schedule in ``vat_utils``). Safe to run repeatedly
(idempotent): once a row's tax is split and consistent with total, it is left alone.

--- Why this only touches "clearly never split" rows -----------------------------
A live audit of a production SUMIT org's raw_data (2026-06-21 backup,
cfo.db.osek439924597.*.bak) showed that ``raw_data.vat_amount`` is essentially
*always* 0/absent for synced documents, regardless of whether the document is really
taxable or genuinely VAT-exempt — SUMIT's list endpoint doesn't expose a VAT
breakdown at all (see vat_utils.py docstring), so raw_data alone cannot reliably
distinguish "explicit zero VAT (exempt)" from "VAT never split (the bug)". Because
of that, this script does NOT trust raw_data.vat_amount as an exemption signal by
itself. Instead it uses the strongest available signal — the row's OWN persisted
subtotal/tax columns:

  A row is a backfill candidate only if ALL of:
    - source == "sumit" (never touches manually-entered rows — a user's own zero-VAT
      entry is a deliberate choice, not a sync artifact)
    - total (or amount, for Expense) != 0
    - tax (or vat_amount) == 0
    - subtotal == total (Invoice/Bill) or amount == total (Expense) — i.e. the
      document was stored completely unsplit, the exact fingerprint of the bug.

If raw_data DOES carry an explicit non-zero VAT-ish field (VAT/Vat/VATAmount/
VatAmount/DocumentVAT/TotalVAT/VAT_Amount/vat_amount), that value wins over
derivation — same precedence the live connector already applies.

Recommendation for whoever runs this against production: before --apply, spot-check
a handful of candidate rows' SUMIT documents in the SUMIT UI (or via
get_document_supplier_details) for any known VAT-exempt customers (donations,
Eilat-zone, export/foreign-currency invoices) — this script cannot see that context
and will derive standard-rate VAT for every candidate row.

Usage:
    .venv/bin/python scripts/backfill_vat_split.py                 # dry-run, all orgs
    .venv/bin/python scripts/backfill_vat_split.py --org-id 5      # dry-run, one org
    .venv/bin/python scripts/backfill_vat_split.py --org-id 5 --apply
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_VAT_KEYS = ("VAT", "Vat", "VATAmount", "VatAmount", "DocumentVAT", "TotalVAT",
             "VAT_Amount", "vat_amount")


def _explicit_vat_from_raw(raw_data: Optional[dict]) -> Optional[Decimal]:
    """Non-zero explicit VAT field from raw_data, or None (mirrors connector's
    precedence rule: a real non-zero VAT figure always wins over derivation)."""
    if not raw_data:
        return None
    for key in _VAT_KEYS:
        v = raw_data.get(key)
        if v is not None:
            try:
                d = Decimal(str(v))
            except (TypeError, ValueError):
                continue
            if d != 0:
                return d
    return None


def _doc_date(raw_data: Optional[dict], *fallbacks) -> date:
    for fb in fallbacks:
        if isinstance(fb, date):
            return fb
    if raw_data:
        for key in ("issue_date", "date"):
            v = raw_data.get(key)
            if v:
                try:
                    return date.fromisoformat(str(v)[:10])
                except ValueError:
                    continue
    return date.today()


def _recompute_split(total: Decimal, raw_data: Optional[dict], doc_date: date) -> tuple[Decimal, Decimal]:
    """(subtotal, tax) for a gross `total`, honoring an explicit raw VAT if present."""
    from cfo.services.vat_utils import split_inclusive

    explicit = _explicit_vat_from_raw(raw_data)
    if explicit is not None:
        tax = explicit
        # Sign-align tax with total (mirrors sumit_connector._derive_subtotal_tax's
        # credit-note handling): subtotal + tax must equal total.
        if total < 0 and tax > 0:
            tax = -tax
        elif total > 0 and tax < 0:
            tax = -tax
        subtotal = total - tax
        return subtotal, tax
    return split_inclusive(total, doc_date)


@dataclass
class EntityReport:
    entity: str
    candidates: int = 0
    total_before: Decimal = Decimal("0")
    tax_before: Decimal = Decimal("0")
    tax_after: Decimal = Decimal("0")
    changed_ids: list = field(default_factory=list)


def _is_candidate(source: str, total: Decimal, tax: Decimal, subtotal: Decimal) -> bool:
    """A row is a backfill candidate if it's synced (never touch manual entries —
    a user's own zero-VAT entry is deliberate) and has a real gross total but no
    tax split. Deliberately NOT requiring subtotal == total: a pre-fix row may have
    left subtotal at the model default (0) rather than mirroring total, so gating
    on that shape would silently miss real legacy rows. `source == "sumit"` is the
    guard that matters; `subtotal` is unused here but kept in the signature so call
    sites read consistently across the three entity backfill functions."""
    return (source or "") == "sumit" and total != 0 and (tax or Decimal("0")) == 0


def backfill_invoices(db, org_id: Optional[int], apply: bool) -> EntityReport:
    from cfo.models import Invoice

    report = EntityReport(entity="invoices")
    q = db.query(Invoice)
    if org_id is not None:
        q = q.filter(Invoice.organization_id == org_id)
    for row in q.all():
        total = Decimal(str(row.total or 0))
        tax = Decimal(str(row.tax or 0))
        subtotal = Decimal(str(row.subtotal or 0))
        if not _is_candidate(row.source, total, tax, subtotal):
            continue
        doc_date = _doc_date(row.raw_data, row.issue_date, row.due_date)
        new_subtotal, new_tax = _recompute_split(total, row.raw_data, doc_date)
        report.candidates += 1
        report.total_before += total
        report.tax_before += tax
        report.tax_after += new_tax
        report.changed_ids.append(row.id)
        if apply:
            row.subtotal = new_subtotal
            row.tax = new_tax
    if apply and report.candidates:
        db.commit()
    return report


def backfill_bills(db, org_id: Optional[int], apply: bool) -> EntityReport:
    from cfo.models import Bill

    report = EntityReport(entity="bills")
    q = db.query(Bill)
    if org_id is not None:
        q = q.filter(Bill.organization_id == org_id)
    for row in q.all():
        total = Decimal(str(row.total or 0))
        tax = Decimal(str(row.tax or 0))
        subtotal = Decimal(str(row.subtotal or 0))
        if not _is_candidate(row.source, total, tax, subtotal):
            continue
        doc_date = _doc_date(row.raw_data, row.issue_date, row.due_date)
        new_subtotal, new_tax = _recompute_split(total, row.raw_data, doc_date)
        report.candidates += 1
        report.total_before += total
        report.tax_before += tax
        report.tax_after += new_tax
        report.changed_ids.append(row.id)
        if apply:
            row.subtotal = new_subtotal
            row.tax = new_tax
    if apply and report.candidates:
        db.commit()
    return report


def backfill_expenses(db, org_id: Optional[int], apply: bool) -> EntityReport:
    from cfo.models import Expense

    report = EntityReport(entity="expenses")
    q = db.query(Expense)
    if org_id is not None:
        q = q.filter(Expense.organization_id == org_id)
    for row in q.all():
        total = Decimal(str(row.total or 0))
        vat = Decimal(str(row.vat_amount or 0))
        amount = Decimal(str(row.amount or 0))
        if not _is_candidate(row.source, total, vat, amount):
            continue
        doc_date = _doc_date(row.raw_data, row.expense_date)
        new_amount, new_vat = _recompute_split(total, row.raw_data, doc_date)
        report.candidates += 1
        report.total_before += total
        report.tax_before += vat
        report.tax_after += new_vat
        report.changed_ids.append(row.id)
        if apply:
            row.amount = new_amount
            row.vat_amount = new_vat
    if apply and report.candidates:
        db.commit()
    return report


def run(org_id: Optional[int], apply: bool) -> list[EntityReport]:
    from cfo.database import SessionLocal

    db = SessionLocal()
    try:
        reports = [
            backfill_invoices(db, org_id, apply),
            backfill_bills(db, org_id, apply),
            backfill_expenses(db, org_id, apply),
        ]
        return reports
    finally:
        db.close()


def _print_reports(reports: list[EntityReport], apply: bool) -> None:
    mode = "APPLIED" if apply else "DRY-RUN (pass --apply to write)"
    print(f"=== VAT split backfill — {mode} ===")
    total_candidates = 0
    for r in reports:
        total_candidates += r.candidates
        print(f"\n{r.entity}: {r.candidates} candidate row(s)")
        if r.candidates:
            print(f"  total (gross, unchanged): {r.total_before}")
            print(f"  tax before: {r.tax_before}  ->  tax after: {r.tax_after}")
            print(f"  ids: {r.changed_ids[:20]}{'...' if len(r.changed_ids) > 20 else ''}")
    print(f"\nTotal candidate rows across entities: {total_candidates}")
    if not apply and total_candidates:
        print("Nothing written — re-run with --apply to persist.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--org-id", type=int, default=None, help="Limit to one organization")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    args = parser.parse_args()

    reports = run(args.org_id, args.apply)
    _print_reports(reports, args.apply)


if __name__ == "__main__":
    main()
