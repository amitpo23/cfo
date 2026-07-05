"""Wave 2 Step 9.1 — AI chat tool layer. Thin wrappers over already-tested
org-scoped services; these tests confirm the wrapping is correct and that
category flags (read vs write) are set right, since ai_chat_service's
confirmation gate depends entirely on that flag."""
import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import Contact, ContactType, Invoice, InvoiceStatus
from cfo.services import ai_chat_tools
from cfo.services.ai_chat_tools import TOOLS


def test_all_tools_have_a_valid_category():
    for tool in TOOLS.values():
        assert tool.category in ("read", "write")


def test_write_tools_are_exactly_issue_document_and_log_attempt():
    """Locks in which tools are write-gated — if a new write tool is added
    without setting category='write', this test forces a deliberate choice."""
    write_tools = {name for name, t in TOOLS.items() if t.category == "write"}
    assert write_tools == {
        "issue_document", "log_collection_attempt", "create_payment_link",
        "run_client_sync", "register_office_client",
    }


def test_anthropic_tool_schemas_shape():
    """Default call (no include_office) must fail closed — office tools are
    excluded unless explicitly requested. See ai_chat_service for who is
    allowed to pass include_office=True (SUPER_ADMIN only)."""
    schemas = ai_chat_tools.anthropic_tool_schemas()
    office_count = sum(1 for t in TOOLS.values() if t.office)
    assert office_count > 0
    assert len(schemas) == len(TOOLS) - office_count
    names = {s["name"] for s in schemas}
    assert "list_office_clients" not in names
    for schema in schemas:
        assert set(schema.keys()) == {"name", "description", "input_schema"}
        assert schema["input_schema"]["type"] == "object"


def test_anthropic_tool_schemas_include_office_when_requested():
    schemas = ai_chat_tools.anthropic_tool_schemas(include_office=True)
    assert len(schemas) == len(TOOLS)
    names = {s["name"] for s in schemas}
    assert {"list_office_clients", "get_office_rollup", "get_client_overview",
            "run_client_sync", "register_office_client"} <= names


def test_office_tools_are_flagged_office_and_others_are_not():
    """The `office` flag is the single source of truth for chat-schema
    visibility gating — this locks in exactly which tools are office-only."""
    office_tool_names = {
        "list_office_clients", "get_office_rollup", "get_client_overview",
        "run_client_sync", "register_office_client",
    }
    for name, tool in TOOLS.items():
        assert tool.office == (name in office_tool_names), name


def test_get_ar_aging_tool_returns_real_data(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        contact = Contact(organization_id=org_id, name="לקוח", contact_type=ContactType.CUSTOMER)
        db.add(contact)
        db.flush()
        db.add(Invoice(
            organization_id=org_id, contact_id=contact.id, invoice_number="X1",
            total=Decimal("500"), balance=Decimal("500"), status=InvoiceStatus.SENT,
            issue_date=date.today() - timedelta(days=40), due_date=date.today() - timedelta(days=10),
        ))
        db.commit()

        result = asyncio.run(TOOLS["get_ar_aging"].fn(db, org_id))
        assert result["total"] == 500.0
    finally:
        db.close()


def test_get_collection_cases_tool_is_org_scoped(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        from cfo.services import collection_case_service as svc
        contact = Contact(organization_id=org_a, name="חייב", contact_type=ContactType.CUSTOMER)
        db.add(contact)
        db.flush()
        db.add(Invoice(
            organization_id=org_a, contact_id=contact.id, invoice_number="X2",
            total=Decimal("100"), balance=Decimal("100"), status=InvoiceStatus.SENT,
            issue_date=date.today() - timedelta(days=60), due_date=date.today() - timedelta(days=45),
        ))
        db.commit()
        svc.open_cases_for_overdue(db, org_a, date.today(), days_threshold=30)

        result_a = asyncio.run(TOOLS["get_collection_cases"].fn(db, org_a))
        result_b = asyncio.run(TOOLS["get_collection_cases"].fn(db, org_b))
        assert len(result_a["cases"]) == 1
        assert result_b["cases"] == []
    finally:
        db.close()


def test_search_contacts_tool_is_org_scoped(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Contact(organization_id=org_a, name="חברת בדיקה בעמ", contact_type=ContactType.CUSTOMER))
        db.commit()

        result_a = asyncio.run(TOOLS["search_contacts"].fn(db, org_a, query="בדיקה"))
        result_b = asyncio.run(TOOLS["search_contacts"].fn(db, org_b, query="בדיקה"))
        assert len(result_a["contacts"]) == 1
        assert result_a["contacts"][0]["name"] == "חברת בדיקה בעמ"
        assert result_b["contacts"] == []
    finally:
        db.close()


def test_get_ledger_card_tool_is_org_scoped(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        contact = Contact(organization_id=org_a, name="לקוח כרטסת", contact_type=ContactType.CUSTOMER)
        db.add(contact)
        db.flush()
        contact_id = contact.id
        db.commit()

        result_a = asyncio.run(TOOLS["get_ledger_card"].fn(db, org_a, contact_id=contact_id))
        result_b = asyncio.run(TOOLS["get_ledger_card"].fn(db, org_b, contact_id=contact_id))
        assert result_a["contact_name"] == "לקוח כרטסת"
        assert "error" in result_b
    finally:
        db.close()


def test_get_vat_position_tool_returns_real_data(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        contact = Contact(organization_id=org_id, name="לקוח", contact_type=ContactType.CUSTOMER)
        db.add(contact)
        db.flush()
        db.add(Invoice(
            organization_id=org_id, contact_id=contact.id, invoice_number="V1",
            subtotal=Decimal("1000"), tax=Decimal("180"), total=Decimal("1180"),
            balance=Decimal("1180"), status=InvoiceStatus.SENT,
            issue_date=date.today(), due_date=date.today(),
        ))
        db.commit()

        result = asyncio.run(TOOLS["get_vat_position"].fn(db, org_id))
        assert result["output_vat"] == 180.0
    finally:
        db.close()


def test_get_cashflow_tool_returns_projection_list(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["get_cashflow"].fn(db, org_id))
        assert isinstance(result["projection"], list)
    finally:
        db.close()


def test_list_invoices_tool_is_org_scoped(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        contact = Contact(organization_id=org_a, name="לקוח", contact_type=ContactType.CUSTOMER)
        db.add(contact)
        db.flush()
        db.add(Invoice(
            organization_id=org_a, contact_id=contact.id, invoice_number="L1",
            total=Decimal("300"), balance=Decimal("300"), status=InvoiceStatus.SENT,
            issue_date=date.today(), due_date=date.today(),
        ))
        db.commit()

        result_a = asyncio.run(TOOLS["list_invoices"].fn(db, org_a))
        result_b = asyncio.run(TOOLS["list_invoices"].fn(db, org_b))
        assert len(result_a["documents"]) == 1
        assert result_b["documents"] == []
    finally:
        db.close()


def test_get_engine_status_tool_returns_status(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["get_engine_status"].fn(db, org_id))
        assert isinstance(result, dict)
    finally:
        db.close()


def test_create_payment_link_tool_is_write_category():
    assert TOOLS["create_payment_link"].category == "write"


# ---------------------------------------------------------------------- #
# Office-manager tools — SUPER_ADMIN tier. Role gating itself is tested at
# the service layer (test_ai_chat_service.py); these tests only confirm the
# tool wrappers correctly reuse office_service/financial_synthesis/
# engine_service with real seeded data.
# ---------------------------------------------------------------------- #
def test_list_office_clients_tool_returns_seeded_roster(fresh_org):
    from cfo.services import office_service

    office_org = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        office_service.register_client(
            db, office_org, name="לקוח נבחן", sumit_company_id="555000111",
            sumit_api_key="k",
        )
        result = asyncio.run(TOOLS["list_office_clients"].fn(db, office_org))
        companies = {c["company_id"] for c in result["clients"]}
        assert "555000111" in companies
    finally:
        db.close()


def test_get_office_rollup_tool_returns_real_data(fresh_org):
    from cfo.services import office_service

    office_org = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        office_service.register_client(
            db, office_org, name="רולאפ", sumit_company_id="777000111",
            sumit_api_key="k",
        )
        result = asyncio.run(TOOLS["get_office_rollup"].fn(db, office_org))
        assert result["totals"]["clients"] >= 1
        assert any(c["company_id"] == "777000111" for c in result["clients"])
    finally:
        db.close()


def test_get_client_overview_tool_returns_engine_and_synthesis(fresh_org):
    """get_client_overview takes an explicit client_org_id — a DIFFERENT org
    than the caller's own (office) org — since a SUPER_ADMIN must be able to
    drill into any client file, not just ones registered under one roster."""
    target_org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(
            TOOLS["get_client_overview"].fn(db, 999999, client_org_id=target_org_id)
        )
        assert result["organization_id"] == target_org_id
        assert "engine_status" in result
        assert "synthesis" in result
    finally:
        db.close()


def test_register_office_client_tool_raises_honest_error_without_sumit_key(fresh_org):
    """No fake success: with no office default key and no per-client key,
    the underlying office_service.register_client ValueError must propagate
    unmasked — ai_chat_service.confirm_action is what turns this into a
    clean refusal, never a silent/fake 'בוצע'. Uses a fresh (pristine) org —
    a shared org could have an office default key set by an earlier test."""
    office_org = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            asyncio.run(TOOLS["register_office_client"].fn(
                db, office_org, name="בלי מפתח", company_id="000999888",
            ))
    finally:
        db.close()


def test_run_client_sync_tool_raises_for_unknown_client(fresh_org):
    office_org = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            asyncio.run(TOOLS["run_client_sync"].fn(db, office_org, client_id=999999))
    finally:
        db.close()
