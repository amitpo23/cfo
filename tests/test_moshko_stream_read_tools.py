"""Read-only Moshko tools over the cash, budget, and connection rows already stored.

No SUMIT call and no Open Finance call. A missing balance stays null.
"""
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, IntegrationConnection, Organization, SyncRun, SyncStatus
from cfo.services.ai_chat_tools import TOOLS

NEW_TOOLS = {
    "get_checking_snapshot",
    "get_weekly_cashflow_forecast",
    "get_budget_vs_actual_summary",
    "get_bank_pack_summary",
    "get_unclassified_transfers",
    "get_open_finance_health",
    "get_sumit_connection_status",
}


def _org(db, name: str) -> Organization:
    org = Organization(name=name, is_active=True)
    db.add(org)
    db.flush()
    return org


def test_new_stream_tools_are_read_only_and_org_scoped():
    for name in NEW_TOOLS:
        tool = TOOLS[name]
        assert tool.category == "read"
        assert tool.office is False
        assert "org_id" not in (tool.input_schema.get("properties") or {})
    assert TOOLS["get_weekly_cashflow_forecast"].truth_class == "forecast"


def test_checking_snapshot_missing_and_stale_are_not_zero(client):
    db = SessionLocal()
    try:
        empty = _org(db, "stream-empty")
        stale_org = _org(db, "stream-stale")
        fresh = _org(db, "stream-fresh")
        zero = _org(db, "stream-zero")
        other = _org(db, "stream-other")
        db.add(Account(
            organization_id=stale_org.id, name="עו״ש ישן", account_type=AccountType.BANK,
            balance=Decimal("1500.00"), source="open_finance", raw_account_type="CHECKING",
            balance_as_of=datetime.utcnow() - timedelta(days=5),
            credit_limit=Decimal("10000.00"), available_limit=Decimal("8500.00"),
        ))
        db.add(Account(
            organization_id=fresh.id, name="עו״ש", account_type=AccountType.BANK,
            balance=Decimal("320.50"), source="open_finance", raw_account_type="CHECKING",
            balance_as_of=datetime.utcnow(),
        ))
        db.add(Account(
            organization_id=zero.id, name="עו״ש אפס", account_type=AccountType.BANK,
            balance=Decimal("0.00"), source="open_finance", raw_account_type="CHECKING",
            balance_as_of=datetime.utcnow(),
        ))
        db.add(Account(
            organization_id=other.id, name="עו״ש אחר", account_type=AccountType.BANK,
            balance=Decimal("9999.00"), source="open_finance", raw_account_type="CHECKING",
            balance_as_of=datetime.utcnow(),
        ))
        db.commit()

        missing = asyncio.run(TOOLS["get_checking_snapshot"].fn(db, empty.id))
        assert missing["balance"] is None
        assert missing["status"] == "unknown"
        assert missing["provider_calls"] == 0
        assert missing["balance"] != 0

        stale = asyncio.run(TOOLS["get_checking_snapshot"].fn(db, stale_org.id))
        assert stale["balance"] is None
        assert stale["status"] == "unknown"
        assert stale["as_of"] is None
        assert stale["stale_balances"]
        assert stale["stale_balances"][0]["balance"] is None
        assert stale["provider_calls"] == 0

        current = asyncio.run(TOOLS["get_checking_snapshot"].fn(db, fresh.id))
        assert current["balance"] == 320.5
        assert current["as_of"] == datetime.utcnow().date().isoformat()
        assert current["source"] == "open_finance"
        assert current["figure"] == "checking_snapshot"
        assert current["organization_id"] == fresh.id

        real_zero = asyncio.run(TOOLS["get_checking_snapshot"].fn(db, zero.id))
        assert real_zero["balance"] == 0.0
        assert real_zero["status"] == "ready"
    finally:
        db.close()


def test_weekly_forecast_and_budget_keep_missing_null(client):
    db = SessionLocal()
    try:
        org = _org(db, "stream-forecast")
        db.commit()
        forecast = asyncio.run(TOOLS["get_weekly_cashflow_forecast"].fn(db, org.id))
        assert forecast["provider_calls"] == 0
        assert forecast["engine"] == "cashflow_source"
        assert forecast["opening"]["amount"] is None
        assert forecast["week_count"] > 0
        assert all(week["closing"] is None for week in forecast["weeks"])

        budget = asyncio.run(TOOLS["get_budget_vs_actual_summary"].fn(db, org.id))
        assert budget["provider_calls"] == 0
        assert budget["budget_vs_actual"]["status"] == "unknown"
        assert budget["budget_vs_actual"]["has_budget"] is False
        assert budget["assumptions"]["missing_count"] > 0
        assert budget["assumptions"]["confirmed"] == []
        assert budget["books_pnl"]["basis"] == "no_books"
        for month in budget["books_pnl"]["months"]:
            assert month["revenue"] is None
            assert month["costs"] is None
            assert month["net"] is None
        for month in budget["budget_vs_actual"]["months"]:
            totals = month["totals"]
            assert totals["revenue"]["actual"] is None
            assert totals["costs"]["actual"] is None
    finally:
        db.close()


def test_bank_pack_pointer_and_empty_transfer_coverage(client):
    db = SessionLocal()
    try:
        org = _org(db, "stream-pack")
        db.commit()
        pack = asyncio.run(TOOLS["get_bank_pack_summary"].fn(db, org.id))
        assert pack["provider_calls"] == 0
        assert pack["title_he"] == "חבילה לבנק"
        assert "רווח והפסד" in pack["contains_he"]
        assert pack["page"] is None
        assert pack["opening"]["amount"] is None
        assert pack["opening"]["missing_label"]
        assert pack["week_count"] > 0

        queue = asyncio.run(TOOLS["get_unclassified_transfers"].fn(db, org.id))
        assert queue["provider_calls"] == 0
        assert queue["unclassified_count"] == 0
        assert queue["coverage"]["total"] == 0
        assert queue["coverage"]["balanced"] is True
        assert queue["rows"] == []
    finally:
        db.close()


def test_balance_diagnostic_endpoints_match_the_admin_page(client, owner, platform_admin):
    """The admin page reads these two GETs and nothing else."""
    single = client.get("/api/cashflow/balance-diagnostic", headers=owner["headers"])
    assert single.status_code == 200, single.text
    body = single.json()
    assert body["provider_calls"] == 0
    assert "snapshot_balance" in body
    assert body["import_notes_he"]

    denied = client.get("/api/cashflow/balance-diagnostic/all", headers=owner["headers"])
    assert denied.status_code == 403

    allowed = client.get("/api/cashflow/balance-diagnostic/all", headers=platform_admin["headers"])
    assert allowed.status_code == 200, allowed.text
    payload = allowed.json()
    assert payload["provider_calls"] == 0
    assert isinstance(payload["organizations"], list)


def test_connection_status_reads_stored_rows_only(client):
    db = SessionLocal()
    try:
        org = _org(db, "stream-connections")
        secret = "encrypted-blob-must-not-leak"
        db.add(IntegrationConnection(
            organization_id=org.id, source="sumit", status="active",
            credentials_encrypted=secret,
            last_synced_at=datetime(2026, 10, 20, 3, 0),
        ))
        db.add(SyncRun(
            organization_id=org.id, source="sumit", status=SyncStatus.FAILED,
            finished_at=datetime(2026, 10, 20, 3, 5),
            error_summary="CompanyID נדחה",
        ))
        db.add(IntegrationConnection(
            organization_id=org.id, source="open_finance", status="active",
            credentials_encrypted=secret,
            last_synced_at=datetime(2026, 10, 28, 2, 0),
        ))
        db.add(Account(
            organization_id=org.id, name="עו״ש מחובר", account_type=AccountType.BANK,
            balance=Decimal("1500.00"), source="open_finance", raw_account_type="CHECKING",
            balance_as_of=datetime.utcnow() - timedelta(days=5),
            credit_limit=Decimal("10000.00"), available_limit=Decimal("8500.00"),
        ))
        db.commit()

        sumit = asyncio.run(TOOLS["get_sumit_connection_status"].fn(db, org.id))
        assert sumit["configured"] is True
        assert sumit["active"] is True
        assert sumit["status"] == "active"
        assert sumit["last_error"] == "CompanyID נדחה"
        assert sumit["last_run_status"] == "failed"
        assert sumit["provider_calls"] == 0
        assert secret not in str(sumit)

        health = asyncio.run(TOOLS["get_open_finance_health"].fn(db, org.id))
        assert health["status"] == "active"
        assert health["last_synced_at"] is not None
        assert health["freshness"] == "unknown"
        assert health["balance"] is None
        assert health["provider_calls"] == 0
        facility = health["facilities"][0]
        assert facility["booked"] is None
        assert facility["available"] is None
        assert facility["credit_limit"] == 10000.0
        assert facility["freshness"] == "unknown"
        assert secret not in str(health)

        bare = _org(db, "stream-unconfigured")
        db.commit()
        absent = asyncio.run(TOOLS["get_sumit_connection_status"].fn(db, bare.id))
        assert absent["configured"] is False
        assert absent["active"] is False
        assert absent["status"] == "not_configured"
        assert absent["last_error"] is None
        assert absent["last_synced_at"] is None
    finally:
        db.close()
