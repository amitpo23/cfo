"""ap_service.run_bank_reconciliation() hardcoded a fake bank_name ('בנק לאומי')
and account_number ('12-345-67890') into every report, regardless of which real
bank/account the org's actual bank statement belongs to -- the function has no
real source for this info (bank_statement rows carry date/description/amount
only), so it invented a plausible-looking Israeli bank name instead of being
honest that this isn't available. Currently reachable via a real route
(GET /api/financial/ap/bank-reconciliation) but that route already drops both
fields before returning -- not live-exposed today, but a landmine for any
future caller that reads them directly off the service's return value."""
from cfo.database import SessionLocal
from cfo.services.ap_service import AccountsPayableService


def test_bank_reconciliation_has_no_fabricated_bank_identity(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        service = AccountsPayableService(db, organization_id=org_id)
        report = service.run_bank_reconciliation(
            bank_statement=[
                {"date": "2026-06-01", "description": "תשלום ספק", "amount": 500.0},
            ],
            book_transactions=[],
        )
    finally:
        db.close()

    assert report.bank_name is None, (
        f"bank_name should be None (no real source), got {report.bank_name!r}"
    )
    assert report.account_number is None, (
        f"account_number should be None (no real source), got {report.account_number!r}"
    )
    # Real, computed fields must still be present and correct.
    assert report.bank_balance == 500.0
