"""Wave 2 Step 9.1 — AI chat tool layer. Thin wrappers over already-tested
org-scoped services; these tests confirm the wrapping is correct and that
category flags (read vs write) are set right, since ai_chat_service's
confirmation gate depends entirely on that flag."""
import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, BankTransaction, Contact, ContactType, Invoice, InvoiceStatus
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
        "create_bank_payment_request", "connect_bank_account",
        "run_client_sync", "register_office_client",
        "create_expense_category", "set_expense_category", "classify_pending_expenses",
        "file_expense", "email_report", "propose_vat_filing_approval",
        "memory",
        "create_task",
        "update_task",
        # נוסף במודע 10/08/2026: תיוק הוצאה לכרטיס באינדקס משנה את
        # הספרים (expense.account_id + status='filed'), ולכן write.
        # `suggest_expense_accounts` ו-`list_my_capabilities` הם read —
        # הם קוראים בלבד ואינם משנים דבר.
        "file_expense_to_account",
        # נוסף במודע 16/08/2026: הצעת מנה לספרים. ההצעה עצמה אינה
        # מבצעת דבר, אך היא הצעד הראשון ברישום **בלתי-הפיך** אצל הספק —
        # ולכן write, לא read. `get_trial_balance` ו-`get_open_batches`
        # שנוספו איתו הם read: הראשון מחשב מה-ledger של רצף, השני
        # מחזיר honest-null על פער הספק.
        "propose_books_batch",
        # נוסף במודע 18/08/2026: עדכון פרופיל רכב משנה את
        # VehicleProfile.primarily_business — עובדת-מס שקובעת ניכוי
        # מע"מ תשומות רכב בפועל (israeli_tax_rules.claimable_vat).
        "set_vehicle_profile",
        # W3 גל 1 (20/08/2026, אישור בעלים): הוראות קבע (יצירה/ביטול/
        # עדכון — כסף אמיתי אצל הספק), ביטול מסמך (רישום), ו-SMS גבייה
        # (פעולה בתשלום + פנייה ללקוח) — כולם write במודע.
        # `list_recurring` ו-`get_customer_debt_report` הם read.
        "create_recurring",
        "cancel_recurring",
        "update_recurring",
        "cancel_document",
        "send_collection_sms",
        # W3 גל 2 (20/08/2026): כיסוי מלא של מתודות SUMIT (ר'
        # sumit_tool_manifest + tests/test_sumit_tool_coverage.py).
        # מסמכים: שינוי מספור ותיוק לספרים הם שינויי ספרים; שכפול מסמך
        # יוצר מסמך אמיתי חדש — write.
        "set_next_document_number",
        "move_document_to_books",
        "create_document_from_existing",
        # CRM: יצירה/עדכון/ארכוב/מחיקה משנים נתונים אצל הספק — write.
        # הקריאות (list/get/count/html/folder/views) הן read.
        "create_crm_entity",
        "update_crm_entity",
        "archive_crm_entity",
        "delete_crm_entity",
        # אמצעי תשלום: קביעה/הסרה של אמצעי שמור — write (בלי פרטי
        # כרטיס לעולם); get_payment_methods הוא read ממוסך.
        "set_payment_method",
        "remove_payment_method",
        # סליקה: חיוב בפועל ודף תשלום — כסף אמיתי, write.
        "charge_customer",
        "begin_payment_redirect",
        # תקשורת: כל פנייה יוצאת (SMS מרובה/פקס/טיקט/רשימת תפוצה) —
        # write; הקריאות (רשימות/שולחים) הן read.
        "send_multiple_sms",
        "send_fax",
        "create_ticket",
        "add_to_mailing_list",
        # טריגרים: הרשמה/ביטול webhook אצל הספק — שינוי תצורה, write.
        "subscribe_trigger",
        "unsubscribe_trigger",
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
        # נוספו במודע 11/08/2026 עם מפתח חברת המשרד (CompanyID 844329067).
        # שניהם מחזירים תמונה של פורטל ההנה"ח כולו ולא של תיק בודד,
        # ולכן office=True — מנהל ארגון לא אמור לראות את מכסות המשרד.
        "office_account_status", "office_capabilities",
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


def test_create_bank_payment_request_tool_is_write_category_with_required_fields():
    tool = TOOLS["create_bank_payment_request"]
    assert tool.category == "write"
    assert set(tool.input_schema["required"]) == {
        "amount", "description", "creditor_name", "creditor_account_number",
    }


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


# ---------------------------------------------------------------------- #
# Expense-workflow tools — org-scoped (not office-tier). Let the accounting-
# office manager view expenses, open custom expense "cards" (categories),
# recategorize, bulk-classify, and check PCN874 readiness through the chat.
# ---------------------------------------------------------------------- #

def _create_expense(db, org_id, **overrides):
    from cfo.services.expense_filing_service import ExpenseFilingService
    data = {
        "supplier_name": "ספק לבדיקה", "amount": 100, "vat_amount": 18,
        "expense_date": date.today(),
    }
    data.update(overrides)
    if isinstance(data.get("expense_date"), str):
        data["expense_date"] = date.fromisoformat(data["expense_date"])
    return ExpenseFilingService(db, organization_id=org_id).create_expense(data)


def test_list_expenses_tool_is_org_scoped_with_totals_and_count(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _create_expense(db, org_a, supplier_name="ספק א", amount=100, vat_amount=18)
        _create_expense(db, org_a, supplier_name="ספק ב", amount=200, vat_amount=36)

        result_a = asyncio.run(TOOLS["list_expenses"].fn(db, org_a))
        result_b = asyncio.run(TOOLS["list_expenses"].fn(db, org_b))

        assert result_a["count"] == 2
        assert len(result_a["expenses"]) == 2
        assert result_a["totals"]["amount"] == 300.0
        assert result_a["totals"]["vat"] == 54.0
        row = result_a["expenses"][0]
        assert set(row.keys()) == {"id", "supplier", "amount", "vat", "date", "category", "status"}
        assert result_b["count"] == 0
        assert result_b["expenses"] == []
    finally:
        db.close()


def test_list_expenses_tool_filters_by_status_category_and_supplier(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _create_expense(db, org_id, supplier_name="חברת חשמל ארצית", category="utilities")
        filed = _create_expense(db, org_id, supplier_name="עו\"ד כהן", category="professional")
        from cfo.models import Expense
        row = db.query(Expense).filter(Expense.id == filed["id"]).first()
        row.status = "filed"
        db.commit()

        by_status = asyncio.run(TOOLS["list_expenses"].fn(db, org_id, status="filed"))
        assert by_status["count"] == 1
        assert by_status["expenses"][0]["supplier"] == "עו\"ד כהן"

        by_category = asyncio.run(TOOLS["list_expenses"].fn(db, org_id, category="utilities"))
        assert by_category["count"] == 1
        assert by_category["expenses"][0]["category"] == "utilities"

        by_supplier = asyncio.run(TOOLS["list_expenses"].fn(db, org_id, supplier="חשמל"))
        assert by_supplier["count"] == 1
        assert "חשמל" in by_supplier["expenses"][0]["supplier"]
    finally:
        db.close()


def test_list_expenses_tool_filters_by_date_range(fresh_org):
    from datetime import timedelta as td
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        old = _create_expense(
            db, org_id, supplier_name="ישן", expense_date=(date.today() - td(days=100)).isoformat(),
        )
        recent = _create_expense(
            db, org_id, supplier_name="חדש", expense_date=date.today().isoformat(),
        )
        result = asyncio.run(TOOLS["list_expenses"].fn(
            db, org_id, from_date=(date.today() - td(days=10)).isoformat(),
        ))
        ids = {e["id"] for e in result["expenses"]}
        assert recent["id"] in ids
        assert old["id"] not in ids
    finally:
        db.close()


def test_list_expenses_tool_respects_50_row_limit_but_reports_true_count(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        for i in range(55):
            _create_expense(db, org_id, supplier_name=f"ספק {i}", invoice_number=str(i))
        result = asyncio.run(TOOLS["list_expenses"].fn(db, org_id))
        assert result["count"] == 55
        assert len(result["expenses"]) == 50
    finally:
        db.close()


def test_get_pcn874_readiness_tool_wraps_service(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        exp = _create_expense(db, org_id, supplier_name="ספק מתויק")
        from cfo.models import Expense
        row = db.query(Expense).filter(Expense.id == exp["id"]).first()
        row.status = "filed"
        row.supplier_tax_id = "511402547"
        db.commit()

        result = asyncio.run(TOOLS["get_pcn874_readiness"].fn(db, org_id))
        assert result["filed_total"] == 1
        assert result["pcn_ready"] == 1
    finally:
        db.close()


def test_create_expense_category_tool_creates_a_custom_card(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["create_expense_category"].fn(
            db, org_id, key="conference_travel", name_he="נסיעות לכנסים",
            keywords=["כנס"],
        ))
        assert result["key"] == "conference_travel"
        assert result["built_in"] is False

        from cfo.services import expense_category_service
        keys = expense_category_service.org_category_keys(db, org_id)
        assert "conference_travel" in keys
    finally:
        db.close()


def test_create_expense_category_tool_is_write_category():
    assert TOOLS["create_expense_category"].category == "write"


def test_set_expense_category_tool_recategorizes_and_rejects_unknown_category(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        exp = _create_expense(db, org_id, supplier_name="ספק לשינוי")

        result = asyncio.run(TOOLS["set_expense_category"].fn(
            db, org_id, expense_id=exp["id"], category="rent",
        ))
        assert result["category"] == "rent"

        with pytest.raises(ValueError):
            asyncio.run(TOOLS["set_expense_category"].fn(
                db, org_id, expense_id=exp["id"], category="not_a_real_category",
            ))
    finally:
        db.close()


def test_set_expense_category_tool_is_write_category():
    assert TOOLS["set_expense_category"].category == "write"


def test_classify_pending_expenses_tool_returns_counts_and_actually_updates_rows(fresh_org):
    """create_expense auto-classifies at creation time, so a freshly-created
    expense is never actually 'uncategorized' — to exercise
    classify_pending_expenses honestly, force rows back into the
    None/'other' state it targets (as e.g. a raw SUMIT sync import would
    leave them) directly via the DB, bypassing the auto-classify-on-create
    path."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        from cfo.models import Expense

        travel = _create_expense(db, org_id, supplier_name="תחנת דלק פז")
        rent = _create_expense(db, org_id, supplier_name="השכרת משרד", description="דמי שכירות")
        # already-categorized (non-'other') and filed rows must NOT be touched
        manually_set = _create_expense(db, org_id, supplier_name="ספק שנקבע ידנית", category="materials")
        already_filed = _create_expense(db, org_id, supplier_name="תחנת דלק שכבר תויקה")

        db.query(Expense).filter(
            Expense.id.in_([travel["id"], rent["id"], already_filed["id"]])
        ).update({"category": None}, synchronize_session=False)
        db.query(Expense).filter(Expense.id == already_filed["id"]).update(
            {"status": "filed"}, synchronize_session=False
        )
        db.commit()

        result = asyncio.run(TOOLS["classify_pending_expenses"].fn(db, org_id))

        assert result["scanned"] == 2  # vehicle (fuel) + rent only — not manually_set, not already_filed
        assert result["classified"] == 2
        assert result["by_category"]["vehicle"] == 1
        assert result["by_category"]["rent"] == 1

        db.expire_all()
        travel_row = db.query(Expense).filter(Expense.id == travel["id"]).first()
        rent_row = db.query(Expense).filter(Expense.id == rent["id"]).first()
        manual_row = db.query(Expense).filter(Expense.id == manually_set["id"]).first()
        filed_row = db.query(Expense).filter(Expense.id == already_filed["id"]).first()
        assert travel_row.category == "vehicle"
        assert rent_row.category == "rent"
        assert manual_row.category == "materials"  # untouched
        assert filed_row.category is None  # untouched — already filed
    finally:
        db.close()


def test_classify_pending_expenses_tool_is_write_category():
    assert TOOLS["classify_pending_expenses"].category == "write"


# ---------------------------------------------------------------------- #
# rezef_help — project knowledge-base lookup tool. Read-only, no org data
# involved (ignores db/org_id) — content correctness is covered exhaustively
# in test_rezef_kb.py; these tests only confirm the tool wrapper dispatches
# to rezef_kb correctly and is registered/categorized right.
# ---------------------------------------------------------------------- #

def test_rezef_help_tool_is_read_category():
    assert TOOLS["rezef_help"].category == "read"


def test_rezef_help_tool_with_no_topic_returns_index(fresh_org):
    from cfo.services import rezef_kb

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["rezef_help"].fn(db, org_id))
        assert result["content"] == rezef_kb.topic_index()
        assert "לא נמצא" not in result["content"]
    finally:
        db.close()


def test_rezef_help_tool_with_known_topic_returns_section(fresh_org):
    from cfo.services import rezef_kb

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["rezef_help"].fn(db, org_id, topic="expenses"))
        assert result["content"] == rezef_kb.TOPICS["expenses"]
    finally:
        db.close()


def test_rezef_help_tool_with_unknown_topic_returns_index_and_not_found(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["rezef_help"].fn(db, org_id, topic="שיווק"))
        assert "לא נמצא" in result["content"]
        assert "שיווק" in result["content"]
    finally:
        db.close()


def test_rezef_help_tool_is_included_in_default_schema_and_not_office_gated():
    schemas = ai_chat_tools.anthropic_tool_schemas()
    names = {s["name"] for s in schemas}
    assert "rezef_help" in names
    assert TOOLS["rezef_help"].office is False


# ---------------------------------------------------------------------- #
# M8 — bank-aware chat tools. Thin wrappers over bank_query_service, which
# is exhaustively tested in test_bank_query_service.py; these tests only
# confirm registration, category, and correct org-scoped dispatch.
# ---------------------------------------------------------------------- #

def _mk_bank_account(db, org_id, external_id="open_finance:chat1"):
    acc = Account(
        organization_id=org_id, name="בנק דיסקונט", account_type=AccountType.BANK,
        external_id=external_id, balance=Decimal("5000"),
    )
    db.add(acc)
    db.flush()
    return acc


def _mk_bank_txn(db, org_id, account_id, *, amount, description="עסקה", days_ago=0, **raw_kwargs):
    raw = {"type": "CHECKING"}
    raw.update(raw_kwargs)
    txn = BankTransaction(
        organization_id=org_id, account_id=account_id,
        transaction_date=date.today() - timedelta(days=days_ago),
        description=description, amount=Decimal(str(amount)), currency="ILS",
        raw_data=raw,
    )
    db.add(txn)
    db.flush()
    return txn


def test_bank_chat_tools_are_registered_and_read_category():
    for name in ("query_bank_transactions", "get_bank_position", "get_missing_documents"):
        assert name in TOOLS
        assert TOOLS[name].category == "read"


def test_query_bank_transactions_tool_executes_against_seeded_data(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _mk_bank_account(db, org_id)
        _mk_bank_txn(db, org_id, acc.id, amount=-150, description="קפה ומאפה")
        _mk_bank_txn(db, org_id, acc.id, amount=800, description="תקבול לקוח")
        db.commit()

        result = asyncio.run(TOOLS["query_bank_transactions"].fn(db, org_id))
        assert result["count"] == 2
        assert result["total_amount"] == 650.0

        result_out = asyncio.run(TOOLS["query_bank_transactions"].fn(db, org_id, direction="out"))
        assert result_out["count"] == 1
        assert result_out["transactions"][0]["description"] == "קפה ומאפה"
    finally:
        db.close()


def test_get_bank_position_tool_executes_against_seeded_data(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _mk_bank_account(db, org_id)
        _mk_bank_txn(db, org_id, acc.id, amount=-100)
        db.commit()

        result = asyncio.run(TOOLS["get_bank_position"].fn(db, org_id))
        assert len(result["accounts"]) == 1
        assert result["accounts"][0]["balance"] == 5000.0
        assert result["accounts"][0]["transaction_count"] == 1
    finally:
        db.close()


def test_get_missing_documents_tool_executes_against_seeded_data(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _mk_bank_account(db, org_id)
        _mk_bank_txn(db, org_id, acc.id, amount=-300, description="הוראת קבע ביטוח")
        _mk_bank_txn(db, org_id, acc.id, amount=-450, description="ספק לא מזוהה", merchantName="ספק חדש בע\"מ")
        db.commit()

        result = asyncio.run(TOOLS["get_missing_documents"].fn(db, org_id))
        assert result["excluded"]["standing_orders"]["count"] == 1
        assert result["missing_document"]["count"] == 1
        assert result["missing_document"]["total"] == 450.0
    finally:
        db.close()


def test_bank_chat_tools_are_org_scoped(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc_a = _mk_bank_account(db, org_a, external_id="open_finance:a")
        acc_b = _mk_bank_account(db, org_b, external_id="open_finance:b")
        _mk_bank_txn(db, org_a, acc_a.id, amount=-10, description="A")
        _mk_bank_txn(db, org_b, acc_b.id, amount=-99999, description="B")
        db.commit()

        result_a = asyncio.run(TOOLS["query_bank_transactions"].fn(db, org_a))
        assert result_a["count"] == 1
        assert result_a["transactions"][0]["description"] == "A"

        position_a = asyncio.run(TOOLS["get_bank_position"].fn(db, org_a))
        assert len(position_a["accounts"]) == 1

        missing_a = asyncio.run(TOOLS["get_missing_documents"].fn(db, org_a))
        assert missing_a["missing_document"]["total"] == 10.0
    finally:
        db.close()


def test_get_bank_expense_gap_alerts_tool_registered_and_org_scoped(fresh_org):
    """כלי בוט חדש (מנוע פער בנק-חשבוניות) — קורא את התרעות ה-CfoInsight
    (insight_type='missing_document') שנוצרו ע"י bank_expense_gap.scan_and_alert,
    לא מריץ סיווג בזמן אמת (זה תפקידו של get_missing_documents)."""
    assert "get_bank_expense_gap_alerts" in TOOLS
    assert TOOLS["get_bank_expense_gap_alerts"].category == "read"

    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        from cfo.services import bank_expense_gap

        _mk_bank_txn(db, org_a, None, amount=-500, description="הוצאה בלי חשבונית", days_ago=1)
        _mk_bank_txn(db, org_b, None, amount=-99999, description="לא שייך ל-א", days_ago=1)
        db.commit()

        bank_expense_gap.scan_and_alert(db, org_a, lookback_days=14)
        bank_expense_gap.scan_and_alert(db, org_b, lookback_days=14)

        result_a = asyncio.run(TOOLS["get_bank_expense_gap_alerts"].fn(db, org_a))
        assert result_a["count"] == 1
        assert result_a["alerts"][0]["title"]
    finally:
        db.close()


def test_get_suppliers_missing_invoices_tool_registered_and_org_scoped(fresh_org):
    """כלי בוט חדש — ספקים ששולם להם ללא מסמך תואם, מקובצים ברמת ספק
    (לא תנועה בודדת) מעל bank_expense_gap.suppliers_missing_invoices."""
    assert "get_suppliers_missing_invoices" in TOOLS
    assert TOOLS["get_suppliers_missing_invoices"].category == "read"

    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_bank_txn(db, org_a, None, amount=-500, description="חיוב א",
                     merchantName="ספק בדיקה", days_ago=1)
        _mk_bank_txn(db, org_b, None, amount=-99999, description="לא שייך ל-א",
                     merchantName="ספק זר", days_ago=1)
        db.commit()

        result_a = asyncio.run(TOOLS["get_suppliers_missing_invoices"].fn(db, org_a))
        names = [s["name"] for s in result_a["suppliers"]]
        assert "ספק בדיקה" in names
        assert "ספק זר" not in names
        assert "unidentified_transfers" in result_a
        assert "totals" in result_a
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# Package 1 (2026-07-26 personas plan) — P&L source switch + 7 new
# read-only chat tools (get_credit_line_status, get_ar_health,
# get_cfo_insights, get_daily_brief, get_tax_estimate, verify_filing,
# kb_lookup). All read-category, all available to every persona (persona
# is a prompt-tone axis, not a permission gate — see ai_chat_personas.py).
# ---------------------------------------------------------------------- #

def test_get_pnl_tool_uses_ledger_source(fresh_org):
    """Council decision 2026-07-26: one P&L tool, ledger-based
    (financial_reports_service.generate_profit_loss), not DashboardService
    (would have been a second, divergent source of truth)."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["get_pnl"].fn(db, org_id))
        assert result["source"] == "ledger"
        assert "total_revenue" in result
        assert "total_expenses" in result
        assert "net_income" in result
    finally:
        db.close()


def test_get_credit_line_status_tool_returns_unknown_without_credit_limit(fresh_org):
    assert TOOLS["get_credit_line_status"].category == "read"
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["get_credit_line_status"].fn(db, org_id))
        assert result["status"] == "unknown"
        assert result["breach_date"] is None
    finally:
        db.close()


def test_get_credit_line_status_tool_reports_breach_date(fresh_org):
    """org-scoped smoke test with a real credit_limit + a live bank balance
    that goes below it, to prove the tool wraps the real service (not a
    stub). Sourced from BankTransaction/Account.balance — the service moved
    off the frozen Transaction table (follow-up, 21/08/2026 review)."""
    from datetime import date, timedelta
    from decimal import Decimal
    from cfo.models import BankTransaction

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = Account(
            organization_id=org_id, name="בנק ראשי", account_type=AccountType.BANK,
            balance=Decimal("-9000"), credit_limit=Decimal("5000"),
        )
        db.add(acc)
        db.flush()
        db.add(BankTransaction(
            organization_id=org_id, account_id=acc.id,
            amount=Decimal("-9000"),
            transaction_date=date.today() - timedelta(days=5),
        ))
        db.commit()

        result = asyncio.run(TOOLS["get_credit_line_status"].fn(db, org_id))
        assert result["status"] in ("breach", "warning")
        assert result["accounts"][0]["credit_limit"] == 5000.0
    finally:
        db.close()


def test_get_ar_health_tool_returns_dso_trend_and_risk_summary(fresh_org):
    assert TOOLS["get_ar_health"].category == "read"
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["get_ar_health"].fn(db, org_id))
        assert isinstance(result["dso_trend"], list)
        assert "risk_summary" in result
        assert "collection_summary" in result
        assert "total_receivables" in result
    finally:
        db.close()


def test_get_cfo_insights_tool_is_read_only_and_org_scoped(fresh_org):
    from cfo.models import CfoInsight

    assert TOOLS["get_cfo_insights"].category == "read"
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(CfoInsight(
            organization_id=org_a, fingerprint="test:fp:1", insight_type="cashflow",
            severity="high", title="בדיקה", status="active",
        ))
        db.commit()

        result_a = asyncio.run(TOOLS["get_cfo_insights"].fn(db, org_a))
        result_b = asyncio.run(TOOLS["get_cfo_insights"].fn(db, org_b))
        assert len(result_a["insights"]) == 1
        assert result_b["insights"] == []
    finally:
        db.close()


def test_get_daily_brief_tool_returns_subject_and_text(fresh_org):
    assert TOOLS["get_daily_brief"].category == "read"
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["get_daily_brief"].fn(db, org_id))
        assert set(result.keys()) == {"subject", "text"}
        assert isinstance(result["text"], str) and result["text"]
    finally:
        db.close()


def test_get_tax_estimate_tool_includes_method_caveat_and_low_confidence(fresh_org):
    """Binding requirement (council 2026-07-26): a tax estimate without an
    explicit caveat is never allowed — honest-null for tax numbers."""
    assert TOOLS["get_tax_estimate"].category == "read"
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["get_tax_estimate"].fn(db, org_id))
        assert result["confidence"] == "low"
        assert result["method"]
        assert result["caveat"]
        assert "calculated_amount" in result
    finally:
        db.close()


def test_verify_filing_tool_requires_year_and_month_and_returns_status(fresh_org):
    assert TOOLS["verify_filing"].category == "read"
    assert TOOLS["verify_filing"].input_schema["required"] == ["year", "month"]
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["verify_filing"].fn(db, org_id, year=2026, month=5))
        assert result["status"] in ("pass", "warn", "fail")
        assert "checks" in result
    finally:
        db.close()


def test_kb_lookup_tool_returns_real_content(fresh_org):
    """Package 2 wired the real KB loader (kb_loader.py) — kb_lookup now
    returns actual sections from docs/bookkeeper_kb + docs/sumit_help_kb,
    not the package-1 honest-null stub."""
    assert TOOLS["kb_lookup"].category == "read"
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["kb_lookup"].fn(db, org_id, query="מע\"מ תשומות"))
        assert result["results"]
        assert result["results"][0]["text"]
        assert result["results"][0]["source"]
    finally:
        db.close()


def test_new_package1_tools_are_not_office_gated():
    for name in (
        "get_credit_line_status", "get_ar_health", "get_cfo_insights",
        "get_daily_brief", "get_tax_estimate", "verify_filing", "kb_lookup",
    ):
        assert TOOLS[name].office is False, name


def test_file_expense_tool_is_write_and_calls_file_to_sumit(monkeypatch, fresh_org):
    """Package A (moshko-full-bot plan): file_expense wraps
    ExpenseFilingService.file_to_sumit — must be category='write' so the
    chat confirmation gate never auto-executes a real SUMIT booking."""
    assert TOOLS["file_expense"].category == "write"
    assert TOOLS["file_expense"].input_schema["required"] == ["expense_id"]
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        called = {}

        async def fake_file_to_sumit(self, expense_id):
            called["expense_id"] = expense_id
            return {"id": expense_id, "status": "filed"}

        from cfo.services.expense_filing_service import ExpenseFilingService
        monkeypatch.setattr(ExpenseFilingService, "file_to_sumit", fake_file_to_sumit)

        result = asyncio.run(TOOLS["file_expense"].fn(db, org_id, expense_id=42))
        assert called["expense_id"] == 42
        assert result["status"] == "filed"
    finally:
        db.close()


def test_get_expense_intake_status_tool_is_read_and_reports_counts(fresh_org):
    from cfo.models import Expense
    from datetime import date

    assert TOOLS["get_expense_intake_status"].category == "read"
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Expense(
            organization_id=org_id, source="telegram", supplier_name="ספק",
            amount=Decimal("100"), vat_amount=Decimal("18"), total=Decimal("118"),
            expense_date=date.today(), status="pending",
        ))
        db.commit()

        result = asyncio.run(TOOLS["get_expense_intake_status"].fn(db, org_id))
        assert result["intake_today"] == 1
        assert result["pending_filing"] == 1
        assert "daily_limit" in result
        assert "intake_enabled" in result
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# find_capability — מושקו מגלה יכולות מעבר ל-50 הכלים הרשומים
# ---------------------------------------------------------------------- #
def test_find_capability_is_registered_as_a_read_tool():
    """הכלי קורא את הקטלוג בלבד ואינו מפעיל דבר אצל הספק — לכן read."""
    from cfo.services.ai_chat_tools import TOOLS

    assert "find_capability" in TOOLS
    assert TOOLS["find_capability"].category == "read"


def test_find_capability_returns_parallel_capabilities_from_both_systems():
    """משימה אחת מחזירה גם את הכלי של SUMIT וגם של Open Finance —
    מושקו לא צריך לדעת מראש באיזו מערכת להסתכל."""
    import asyncio

    from cfo.services.ai_chat_tools import TOOLS

    result = asyncio.run(TOOLS["find_capability"].fn(None, 1, task="transactions"))

    assert result["count"] > 0
    assert {item["system"] for item in result["capabilities"]} == {"sumit", "open_finance"}


def test_find_capability_marks_which_results_need_owner_approval():
    """מושקו חייב לראות מהתוצאה עצמה מה כותב — לא לזכור בעל-פה."""
    import asyncio

    from cfo.services.ai_chat_tools import TOOLS

    result = asyncio.run(TOOLS["find_capability"].fn(None, 1, task="expense"))

    assert result["capabilities"]
    for item in result["capabilities"]:
        assert "requires_approval" in item
        assert item["requires_approval"] is (item["kind"] != "read")


def test_find_capability_can_restrict_to_reads_for_safe_exploration():
    import asyncio

    from cfo.services.ai_chat_tools import TOOLS

    result = asyncio.run(TOOLS["find_capability"].fn(None, 1, task="customer", reads_only=True))

    assert result["capabilities"]
    assert all(item["kind"] == "read" for item in result["capabilities"])


def test_find_capability_returns_honest_empty_for_no_match():
    """אין התאמה = אפס תוצאות, לא 'הכי קרוב' מנוחש שמושקו יפעיל בטעות."""
    import asyncio

    from cfo.services.ai_chat_tools import TOOLS

    result = asyncio.run(TOOLS["find_capability"].fn(None, 1, task="זבחזבחזבח"))

    assert result["count"] == 0
    assert result["capabilities"] == []


# ---------------------------------------------------------------------- #
# תיוק ומפת משימות — חיבור היכולות למושקו (10/08/2026)
# ---------------------------------------------------------------------- #
def test_moshko_can_suggest_and_file_expenses_to_index_accounts():
    from cfo.services.ai_chat_tools import TOOLS

    assert TOOLS["suggest_expense_accounts"].category == "read"
    assert TOOLS["file_expense_to_account"].category == "write"


def test_filing_tool_reports_what_it_linked(fresh_org):
    import asyncio
    from datetime import date
    from decimal import Decimal

    from cfo.database import SessionLocal
    from cfo.models import Account, AccountType, Expense
    from cfo.services.ai_chat_tools import TOOLS

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = Account(organization_id=org_id, name="אנרגיה רפת",
                      account_type=AccountType.EXPENSE, source="hashavshevet_mdb",
                      source_account_code="701600")
        db.add(acc)
        exp = Expense(organization_id=org_id, supplier_name="ספק", amount=Decimal("10"),
                      total=Decimal("10"), expense_date=date(2026, 7, 1), status="pending")
        db.add(exp)
        db.commit()

        result = asyncio.run(
            TOOLS["file_expense_to_account"].fn(db, org_id, expense_id=exp.id, account_id=acc.id)
        )
        assert result["source_account_code"] == "701600"
        assert result["status"] == "filed"
    finally:
        db.close()


def test_moshko_can_list_what_it_is_able_to_do_for_an_organization(fresh_org):
    """מושקו צריך לדעת מה הוא יכול לבצע בתיק הזה — ומה חסום ולמה."""
    import asyncio

    from cfo.services.ai_chat_tools import TOOLS

    org_id = fresh_org()["org_id"]
    result = asyncio.run(TOOLS["list_my_capabilities"].fn(None, org_id))

    assert result["tasks"]
    blocked = [t for t in result["tasks"] if not t["executable"]]
    assert blocked, "ארגון בלי חיבורים אמור להראות משימות חסומות"
    assert all(t["blocked_by"] for t in blocked)
