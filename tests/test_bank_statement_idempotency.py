"""Wave 2 item 7.8: importing the same bank statement twice must not create
duplicate transactions."""
from cfo.database import SessionLocal
from cfo.models import Transaction
from cfo.services.bank_statement_service import BankStatementService

CSV_CONTENT = (
    "date,description,amount\n"
    "01/03/2026,Office supplies,-500\n"
    "02/03/2026,Client payment,3000\n"
)


def _make_org(client):
    import uuid
    email = f"bankimp-{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post("/api/admin/auth/register", json={
        "email": email, "password": "secret123", "full_name": "Bank Import Test",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["user"]["organization_id"]


def test_importing_same_statement_twice_does_not_duplicate(client):
    org_id = _make_org(client)
    db = SessionLocal()
    try:
        service = BankStatementService(db, org_id)

        first = service.import_statement(CSV_CONTENT, file_type="csv")
        assert first["success"] is True
        assert first["created_transactions"] == 2
        assert first["duplicates_skipped"] == 0

        second = service.import_statement(CSV_CONTENT, file_type="csv")
        assert second["success"] is True
        assert second["created_transactions"] == 0, "Re-import must not create new rows"
        assert second["duplicates_skipped"] == 2

        total = db.query(Transaction).filter(Transaction.organization_id == org_id).count()
        assert total == 2, f"Expected exactly 2 transactions after two imports, got {total}"
    finally:
        db.close()
