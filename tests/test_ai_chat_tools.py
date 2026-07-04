"""Wave 2 Step 9.1 — AI chat tool layer. Thin wrappers over already-tested
org-scoped services; these tests confirm the wrapping is correct and that
category flags (read vs write) are set right, since ai_chat_service's
confirmation gate depends entirely on that flag."""
import asyncio
from datetime import date, timedelta
from decimal import Decimal

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
    assert write_tools == {"issue_document", "log_collection_attempt", "create_payment_link"}


def test_anthropic_tool_schemas_shape():
    schemas = ai_chat_tools.anthropic_tool_schemas()
    assert len(schemas) == len(TOOLS)
    for schema in schemas:
        assert set(schema.keys()) == {"name", "description", "input_schema"}
        assert schema["input_schema"]["type"] == "object"


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
