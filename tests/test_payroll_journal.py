"""Wave 2 item 7.4: running payroll must post a balanced derived journal entry
(gross expense / deductions payable / net payable) via ledger_service."""
from datetime import date
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Employee
from cfo.services import ledger_service, payroll_service


def test_run_payroll_posts_balanced_journal_entry(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        emp = Employee(organization_id=org_id, name="בדיקת שכר", tax_id="000000000",
                       gross_salary=Decimal("12000"), credit_points=Decimal("2.25"),
                       pension_pct=Decimal("6.0"))
        db.add(emp)
        db.commit()

        result = payroll_service.run_payroll(db, org_id, 2026, 6)
        assert result["employees"] == 1

        entries = ledger_service.build_journal(
            db, org_id, start=date(2026, 6, 1), end=date(2026, 6, 30), include_opening=False,
        )
        payroll_entries = [e for e in entries if (e.source_ref or "").startswith("payroll:")]
        assert len(payroll_entries) == 1

        entry = payroll_entries[0]
        total_debit = sum(l.debit for l in entry.lines)
        total_credit = sum(l.credit for l in entry.lines)
        assert round(total_debit, 2) == round(total_credit, 2), "Journal entry must balance"

        gross_line = next(l for l in entry.lines if l.account == "5100")
        assert gross_line.debit == 12000.0
    finally:
        db.close()


def test_rerunning_payroll_updates_journal_entry_not_duplicates(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        emp = Employee(organization_id=org_id, name="בדיקת שכר 2", tax_id="000000001",
                       gross_salary=Decimal("10000"), credit_points=Decimal("2.25"),
                       pension_pct=Decimal("6.0"))
        db.add(emp)
        db.commit()

        payroll_service.run_payroll(db, org_id, 2026, 7)
        payroll_service.run_payroll(db, org_id, 2026, 7)  # re-run same period

        entries = ledger_service.build_journal(
            db, org_id, start=date(2026, 7, 1), end=date(2026, 7, 31), include_opening=False,
        )
        payroll_entries = [e for e in entries if (e.source_ref or "").startswith("payroll:")]
        assert len(payroll_entries) == 1, "Re-running payroll must update, not duplicate, the journal entry"
    finally:
        db.close()
