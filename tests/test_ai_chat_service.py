"""Wave 2 Step 9.2/9.3 — AI chat service. The confirmation gate is the
whole safety story: a write tool must never execute from the model's call
alone, on ANY turn — only a separate, explicit confirm_action() call
(re-reading tool/input from the DB, never from client input) may run it,
and only once.
"""
import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from cfo.database import SessionLocal
from cfo.models import ChatMessage, Contact, ContactType, Invoice, InvoiceStatus
from cfo.services import ai_chat_service, document_issuance_service
from cfo.services.ai_chat_service import AIChatService, ChatConfirmationError


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(id_, name, input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


class FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeAnthropicClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def _patch_client(monkeypatch, responses):
    fake = FakeAnthropicClient(responses)
    monkeypatch.setattr(AIChatService, "_make_client", lambda self: fake)
    return fake


def _seed_overdue_invoice(db, org_id, total="500"):
    contact = Contact(organization_id=org_id, name="לקוח", contact_type=ContactType.CUSTOMER)
    db.add(contact)
    db.flush()
    inv = Invoice(
        organization_id=org_id, contact_id=contact.id, invoice_number="X1",
        total=Decimal(total), balance=Decimal(total), status=InvoiceStatus.SENT,
        issue_date=date.today(), due_date=date.today(),
    )
    db.add(inv)
    db.commit()
    return inv


def test_read_tool_executes_automatically_and_feeds_result_back(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_overdue_invoice(db, org_id, total="777")
        fake = _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "get_ar_aging", {})],
            ),
            SimpleNamespace(
                stop_reason="end_turn",
                content=[_text_block("היתרה הפתוחה היא 777 ש\"ח")],
            ),
        ])

        service = AIChatService(db, org_id, user_id=1)
        result = asyncio.run(service.send_message("s1", "מה מצב הגבייה?"))

        assert result["pending_action"] is None
        assert "777" in result["reply"]
        # the tool actually ran and its real result was fed back to the model
        second_call_messages = fake.messages.calls[1]["messages"]
        tool_result_content = second_call_messages[-1]["content"][0]["content"]
        assert "777" in tool_result_content
    finally:
        db.close()


def test_write_tool_is_never_auto_executed(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[
                    _text_block("אני אפיק עבורך חשבונית."),
                    _tool_use_block("t1", "issue_document", {
                        "document_type": "invoice", "customer_id": "123",
                        "customer_name": "לקוח בדיקה",
                        "items": [{"description": "שירות", "unit_price": 100}],
                    }),
                ],
            ),
        ])

        service = AIChatService(db, org_id, user_id=1)
        result = asyncio.run(service.send_message("s1", "תפיק חשבונית ל-123 על 100 שקל"))

        assert result["pending_action"]["tool"] == "issue_document"
        assert result["pending_action"]["input"]["customer_name"] == "לקוח בדיקה"
        assert db.query(Invoice).filter(Invoice.organization_id == org_id).count() == 0

        msg = db.query(ChatMessage).filter(ChatMessage.id == result["message_id"]).first()
        assert msg.pending_action is not None
        assert msg.executed is False
    finally:
        db.close()


def test_create_payment_link_write_tool_is_never_auto_executed(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        inv = _seed_overdue_invoice(db, org_id, total="900")
        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[
                    _text_block("אצור קישור תשלום."),
                    _tool_use_block("t1", "create_payment_link", {"invoice_id": inv.id}),
                ],
            ),
        ])

        service = AIChatService(db, org_id, user_id=1)
        result = asyncio.run(service.send_message("s1", "תיצור קישור תשלום לחשבונית"))

        assert result["pending_action"]["tool"] == "create_payment_link"
        assert result["pending_action"]["input"]["invoice_id"] == inv.id

        msg = db.query(ChatMessage).filter(ChatMessage.id == result["message_id"]).first()
        assert msg.pending_action is not None
        assert msg.executed is False
    finally:
        db.close()


def test_confirm_action_executes_create_payment_link_exactly_once(monkeypatch, fresh_org):
    from cfo.integrations.sumit_models import PaymentLinkResponse
    from cfo.services import document_issuance_service

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        inv = _seed_overdue_invoice(db, org_id, total="900")
        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "create_payment_link", {"invoice_id": inv.id})],
            ),
        ])
        service = AIChatService(db, org_id, user_id=1)
        first = asyncio.run(service.send_message("s1", "צור קישור תשלום"))
        pending_id = first["message_id"]

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_a):
                return False

            async def create_payment_link(self, charge):
                return PaymentLinkResponse(payment_url="https://pay.sumit.co.il/x")

        class FakeConnector:
            async def _get_client(self):
                return FakeClient()

        monkeypatch.setattr(
            document_issuance_service, "get_connector_for_org",
            lambda _db, _org, preferred_source=None: (FakeConnector(), 1, "sumit"),
        )

        confirmed = asyncio.run(service.confirm_action(pending_id))
        assert confirmed["result"]["payment_url"] == "https://pay.sumit.co.il/x"

        try:
            asyncio.run(service.confirm_action(pending_id))
            raised = None
        except ChatConfirmationError as exc:
            raised = exc
        assert raised is not None
    finally:
        db.close()


def test_write_tool_still_not_executed_on_later_unconfirmed_turn(monkeypatch, fresh_org):
    """The discriminating test: a write tool proposed on turn 1 must still
    not execute after an unrelated turn 2 with no confirmation."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "issue_document", {
                    "document_type": "invoice", "customer_id": "123",
                    "customer_name": "לקוח בדיקה",
                    "items": [{"description": "שירות", "unit_price": 100}],
                })],
            ),
        ])
        service = AIChatService(db, org_id, user_id=1)
        first = asyncio.run(service.send_message("s1", "תפיק חשבונית"))
        pending_id = first["message_id"]

        # Turn 2: unrelated message, model doesn't call any tool at all.
        _patch_client(monkeypatch, responses=[
            SimpleNamespace(stop_reason="end_turn", content=[_text_block("בטח, במה עוד אפשר לעזור?")]),
        ])
        asyncio.run(service.send_message("s1", "תודה, מה עוד?"))

        assert db.query(Invoice).filter(Invoice.organization_id == org_id).count() == 0
        msg = db.query(ChatMessage).filter(ChatMessage.id == pending_id).first()
        assert msg.executed is False
    finally:
        db.close()


def _patch_sumit_connector(monkeypatch):
    from cfo.integrations.sumit_models import DocumentResponse

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def create_document(self, request):
            return DocumentResponse(
                document_id="SUMIT-1", document_number="1001",
                document_type=request.document_type, customer_id=request.customer_id,
                total_amount=Decimal("100"), vat_amount=Decimal("0"),
                status="open", issue_date=date.today(),
            )

    class FakeConnector:
        async def _get_client(self):
            return FakeClient()

    monkeypatch.setattr(
        document_issuance_service, "get_connector_for_org",
        lambda _db, _org, preferred_source=None: (FakeConnector(), 1, "sumit"),
    )


def test_confirm_action_executes_exactly_once(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "issue_document", {
                    "document_type": "invoice", "customer_id": "123",
                    "customer_name": "לקוח בדיקה",
                    "items": [{"description": "שירות", "unit_price": 100}],
                })],
            ),
        ])
        service = AIChatService(db, org_id, user_id=1)
        first = asyncio.run(service.send_message("s1", "תפיק חשבונית"))
        pending_id = first["message_id"]

        _patch_sumit_connector(monkeypatch)
        confirmed = asyncio.run(service.confirm_action(pending_id))
        assert confirmed["result"]["external_id"] == "SUMIT-1"
        assert db.query(Invoice).filter(Invoice.organization_id == org_id).count() == 1

        try:
            asyncio.run(service.confirm_action(pending_id))
            raised = None
        except ChatConfirmationError as exc:
            raised = exc
        assert raised is not None
        assert db.query(Invoice).filter(Invoice.organization_id == org_id).count() == 1
    finally:
        db.close()


def test_confirm_action_rejects_cross_org(monkeypatch, fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "issue_document", {
                    "document_type": "invoice", "customer_id": "123",
                    "customer_name": "לקוח", "items": [{"description": "x", "unit_price": 1}],
                })],
            ),
        ])
        service_a = AIChatService(db, org_a, user_id=1)
        first = asyncio.run(service_a.send_message("s1", "תפיק"))

        service_b = AIChatService(db, org_b, user_id=2)
        try:
            asyncio.run(service_b.confirm_action(first["message_id"]))
            raised = None
        except ChatConfirmationError as exc:
            raised = exc
        assert raised is not None
        assert db.query(Invoice).filter(Invoice.organization_id == org_b).count() == 0
    finally:
        db.close()


def test_confirm_action_rejects_message_without_pending_action(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        msg = ChatMessage(
            organization_id=org_id, user_id=1, session_id="s1",
            role="assistant", content="שלום",
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)

        service = AIChatService(db, org_id, user_id=1)
        try:
            asyncio.run(service.confirm_action(msg.id))
            raised = None
        except ChatConfirmationError as exc:
            raised = exc
        assert raised is not None
    finally:
        db.close()


def test_confirm_action_rejects_a_different_users_pending_action(monkeypatch, fresh_org):
    """IDOR check: user 999 in the SAME org must not be able to confirm
    (and execute) a write that user 1 proposed. message_id is a small
    sequential integer — trivially guessable — so org-scoping alone is
    not enough; ownership must be checked too."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "issue_document", {
                    "document_type": "invoice", "customer_id": "123",
                    "customer_name": "לקוח", "items": [{"description": "x", "unit_price": 1}],
                })],
            ),
        ])
        owner_service = AIChatService(db, org_id, user_id=1)
        pending = asyncio.run(owner_service.send_message("s1", "תפיק חשבונית"))

        attacker_service = AIChatService(db, org_id, user_id=999)
        try:
            asyncio.run(attacker_service.confirm_action(pending["message_id"]))
            raised = None
        except ChatConfirmationError as exc:
            raised = exc
        assert raised is not None, "a different user in the same org executed someone else's pending action"
        assert db.query(Invoice).filter(Invoice.organization_id == org_id).count() == 0
    finally:
        db.close()


def test_chat_history_is_scoped_to_the_requesting_user(fresh_org):
    """A user's chat session must not be readable by another user in the
    same org just by knowing/guessing the session_id."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(ChatMessage(
            organization_id=org_id, user_id=1, session_id="shared-guess",
            role="user", content="מידע פרטי",
        ))
        db.commit()

        owner_service = AIChatService(db, org_id, user_id=1)
        other_service = AIChatService(db, org_id, user_id=2)

        assert len(owner_service._history("shared-guess")) == 1
        assert len(other_service._history("shared-guess")) == 0
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# Office-manager tier: SUPER_ADMIN-only tools (list_office_clients,
# get_office_rollup, get_client_overview, run_client_sync,
# register_office_client). Role is re-derived per AIChatService instance
# (is_super_admin=...), exactly as a fresh request would derive it from the
# authenticated user's role — see routes/ai_chat.py for the wiring.
# ---------------------------------------------------------------------- #
def test_super_admin_sees_office_tools_in_schema(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        fake = _patch_client(monkeypatch, responses=[
            SimpleNamespace(stop_reason="end_turn", content=[_text_block("שלום")]),
        ])
        service = AIChatService(db, org_id, user_id=1, is_super_admin=True)
        asyncio.run(service.send_message("s1", "מה שלום המשרד?"))

        tool_names = {t["name"] for t in fake.messages.calls[0]["tools"]}
        assert "list_office_clients" in tool_names
        assert "register_office_client" in tool_names
    finally:
        db.close()


def test_regular_user_does_not_see_office_tools_in_schema(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        fake = _patch_client(monkeypatch, responses=[
            SimpleNamespace(stop_reason="end_turn", content=[_text_block("שלום")]),
        ])
        service = AIChatService(db, org_id, user_id=1, is_super_admin=False)
        asyncio.run(service.send_message("s1", "מה מצב הגבייה?"))

        tool_names = {t["name"] for t in fake.messages.calls[0]["tools"]}
        assert "list_office_clients" not in tool_names
        assert "register_office_client" not in tool_names
    finally:
        db.close()


def test_office_persona_in_system_prompt_only_for_super_admin(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        fake_super = _patch_client(monkeypatch, responses=[
            SimpleNamespace(stop_reason="end_turn", content=[_text_block("שלום")]),
        ])
        super_service = AIChatService(db, org_id, user_id=1, is_super_admin=True)
        asyncio.run(super_service.send_message("s1", "מה שלום המשרד?"))
        assert "משרד" in fake_super.messages.calls[0]["system"]

        fake_regular = _patch_client(monkeypatch, responses=[
            SimpleNamespace(stop_reason="end_turn", content=[_text_block("שלום")]),
        ])
        regular_service = AIChatService(db, org_id, user_id=2, is_super_admin=False)
        asyncio.run(regular_service.send_message("s2", "מה מצב הגבייה?"))
        assert "משרד" not in fake_regular.messages.calls[0]["system"]
    finally:
        db.close()


def test_regular_user_read_office_tool_call_is_refused_not_executed(monkeypatch, fresh_org):
    """Defense in depth: even if a non-super-admin's conversation somehow
    produces a tool_use block naming an office tool (it should never appear
    in their schema at all — this proves execution is ALSO blocked, not
    just visibility)."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        fake = _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "list_office_clients", {})],
            ),
            SimpleNamespace(stop_reason="end_turn", content=[_text_block("סיימתי")]),
        ])
        service = AIChatService(db, org_id, user_id=1, is_super_admin=False)
        result = asyncio.run(service.send_message("s1", "תראה לי את כל תיקי הלקוחות"))

        assert result["pending_action"] is None
        # The tool must NEVER actually have run — the fed-back tool_result is
        # a refusal, not real roster data (totals/clients keys).
        second_call_messages = fake.messages.calls[1]["messages"]
        tool_result_content = second_call_messages[-1]["content"][0]["content"]
        assert "totals" not in tool_result_content
        assert "clients" not in tool_result_content
        assert "error" in tool_result_content
    finally:
        db.close()


def test_regular_user_write_office_tool_call_is_refused_and_never_proposed(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        from cfo.models import SumitCompany

        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "register_office_client", {
                    "name": "לקוח פרוץ", "company_id": "666666666", "api_key": "k",
                })],
            ),
        ])
        service = AIChatService(db, org_id, user_id=1, is_super_admin=False)
        result = asyncio.run(service.send_message("s1", "תרשום לקוח חדש"))

        assert result["pending_action"] is None
        assert db.query(SumitCompany).filter(
            SumitCompany.company_id == "666666666",
        ).count() == 0
    finally:
        db.close()


def test_run_client_sync_requires_confirmation_for_super_admin(monkeypatch, fresh_org):
    """A write office tool must follow the exact same confirmation gate as
    every other write tool — proposed, not executed, until confirm_action."""
    office_org = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        from cfo.models import SumitCompany
        from cfo.services import office_service

        roster = office_service.register_client(
            db, office_org, name="לקוח לסנכרון", sumit_company_id="123123123",
            sumit_api_key="k",
        )
        client_id = roster["id"]

        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "run_client_sync", {"client_id": client_id})],
            ),
        ])
        service = AIChatService(db, office_org, user_id=1, is_super_admin=True)
        result = asyncio.run(service.send_message("s1", "סנכרן את הלקוח הזה"))

        assert result["pending_action"]["tool"] == "run_client_sync"
        assert result["pending_action"]["input"]["client_id"] == client_id

        roster_row = db.query(SumitCompany).filter(SumitCompany.id == client_id).first()
        assert roster_row.last_synced_at is None  # not executed yet
    finally:
        db.close()


def test_confirm_action_refuses_office_tool_if_role_changed_since_proposal(monkeypatch, fresh_org):
    """Role is re-derived per request — if a SUPER_ADMIN proposes an office
    write and is demoted/logs out before confirming, a fresh (non-super)
    confirm must be refused, not silently allowed through a stale proposal."""
    office_org = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        from cfo.models import SumitCompany

        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "register_office_client", {
                    "name": "לקוח תפקיד השתנה", "company_id": "321321321", "api_key": "k",
                })],
            ),
        ])
        proposer = AIChatService(db, office_org, user_id=1, is_super_admin=True)
        proposed = asyncio.run(proposer.send_message("s1", "תרשום לקוח"))
        pending_id = proposed["message_id"]

        demoted = AIChatService(db, office_org, user_id=1, is_super_admin=False)
        try:
            asyncio.run(demoted.confirm_action(pending_id))
            raised = None
        except ChatConfirmationError as exc:
            raised = exc
        assert raised is not None
        assert db.query(SumitCompany).filter(
            SumitCompany.company_id == "321321321",
        ).count() == 0
        msg = db.query(ChatMessage).filter(ChatMessage.id == pending_id).first()
        assert msg.executed is False
    finally:
        db.close()


def test_confirm_action_reports_honest_error_when_register_office_client_fails(monkeypatch, fresh_org):
    """No fake success: office_service.register_client raises when there is
    no SUMIT key (no office default, no per-client key) — confirm_action
    must surface that as a clean refusal, never mark executed, never post a
    'בוצע' success message."""
    office_org = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        from cfo.models import SumitCompany

        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "register_office_client", {
                    "name": "לקוח בלי מפתח", "company_id": "444555666",
                })],
            ),
        ])
        service = AIChatService(db, office_org, user_id=1, is_super_admin=True)
        proposed = asyncio.run(service.send_message("s1", "תרשום לקוח בלי מפתח"))
        pending_id = proposed["message_id"]

        try:
            asyncio.run(service.confirm_action(pending_id))
            raised = None
        except ChatConfirmationError as exc:
            raised = exc
        assert raised is not None

        msg = db.query(ChatMessage).filter(ChatMessage.id == pending_id).first()
        assert msg.executed is False
        assert db.query(SumitCompany).filter(
            SumitCompany.company_id == "444555666",
        ).count() == 0
    finally:
        db.close()


def test_confirm_action_executes_register_office_client_successfully(monkeypatch, fresh_org):
    office_org = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        from cfo.models import SumitCompany

        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "register_office_client", {
                    "name": "לקוח תקין", "company_id": "888777666", "api_key": "k",
                })],
            ),
        ])
        service = AIChatService(db, office_org, user_id=1, is_super_admin=True)
        proposed = asyncio.run(service.send_message("s1", "תרשום לקוח חדש"))
        pending_id = proposed["message_id"]

        confirmed = asyncio.run(service.confirm_action(pending_id))
        assert confirmed["result"]["company_id"] == "888777666"

        msg = db.query(ChatMessage).filter(ChatMessage.id == pending_id).first()
        assert msg.executed is True
        assert db.query(SumitCompany).filter(
            SumitCompany.company_id == "888777666",
        ).count() == 1
    finally:
        db.close()


def test_confirm_action_executes_run_client_sync_successfully(monkeypatch, fresh_org):
    from cfo.services import office_service
    from cfo.services.connector_base import FetchResult
    from cfo.models import SumitCompany

    office_org = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        roster = office_service.register_client(
            db, office_org, name="לקוח לביצוע סנכרון", sumit_company_id="222333444",
            sumit_api_key="k",
        )
        client_id = roster["id"]

        class _EmptyConnector:
            async def fetch_accounts(self, updated_since=None, cursor=None, page_size=100):
                return FetchResult(items=[], has_more=False)

            async def fetch_customers(self, updated_since=None, cursor=None, page_size=100):
                return FetchResult(items=[], has_more=False)

            async def fetch_vendors(self, updated_since=None, cursor=None, page_size=100):
                return FetchResult(items=[], has_more=False)

            async def fetch_invoices(self, updated_since=None, cursor=None, page_size=100):
                return FetchResult(items=[], has_more=False)

            async def fetch_bills(self, updated_since=None, cursor=None, page_size=100):
                return FetchResult(items=[], has_more=False)

            async def fetch_payments(self, updated_since=None, cursor=None, page_size=100):
                return FetchResult(items=[], has_more=False)

            async def fetch_bank_transactions(self, updated_since=None, cursor=None, page_size=100):
                return FetchResult(items=[], has_more=False)

            async def fetch_journal_entries(self, updated_since=None, cursor=None, page_size=100):
                return FetchResult(items=[], has_more=False)

            async def close(self):
                return None

        monkeypatch.setattr(
            office_service, "get_connector_for_org",
            lambda _db, _org, preferred_source=None: (_EmptyConnector(), 1, "sumit"),
        )

        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "run_client_sync", {"client_id": client_id})],
            ),
        ])
        service = AIChatService(db, office_org, user_id=1, is_super_admin=True)
        proposed = asyncio.run(service.send_message("s1", "סנכרן"))
        pending_id = proposed["message_id"]

        confirmed = asyncio.run(service.confirm_action(pending_id))
        assert confirmed["result"]["status"] in {"completed", "partial"}

        db.expire_all()
        roster_row = db.query(SumitCompany).filter(SumitCompany.id == client_id).first()
        assert roster_row.last_synced_at is not None
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# Expense-workflow write tools (create_expense_category, set_expense_category,
# classify_pending_expenses) — same confirmation gate as every other write
# tool: proposed on the first call, never executed until a separate,
# explicit confirm_action().
# ---------------------------------------------------------------------- #

def _seed_pending_expense(db, org_id, supplier_name="ספק", category=None):
    from cfo.services.expense_filing_service import ExpenseFilingService
    return ExpenseFilingService(db, organization_id=org_id).create_expense({
        "supplier_name": supplier_name, "amount": 100, "vat_amount": 18,
        "expense_date": date.today(), "category": category,
    })


def test_create_expense_category_write_tool_is_never_auto_executed(monkeypatch, fresh_org):
    from cfo.models import ExpenseCategory

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "create_expense_category", {
                    "key": "conference_travel", "name_he": "נסיעות לכנסים",
                })],
            ),
        ])
        service = AIChatService(db, org_id, user_id=1)
        result = asyncio.run(service.send_message("s1", "פתח לי כרטיס הוצאה לנסיעות כנסים"))

        assert result["pending_action"]["tool"] == "create_expense_category"
        assert db.query(ExpenseCategory).filter(
            ExpenseCategory.organization_id == org_id,
            ExpenseCategory.key == "conference_travel",
        ).count() == 0
    finally:
        db.close()


def test_confirm_action_executes_create_expense_category_successfully(monkeypatch, fresh_org):
    from cfo.models import ExpenseCategory

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "create_expense_category", {
                    "key": "conference_travel", "name_he": "נסיעות לכנסים",
                })],
            ),
        ])
        service = AIChatService(db, org_id, user_id=1)
        proposed = asyncio.run(service.send_message("s1", "פתח כרטיס הוצאה"))
        pending_id = proposed["message_id"]

        confirmed = asyncio.run(service.confirm_action(pending_id))
        assert confirmed["result"]["key"] == "conference_travel"
        assert db.query(ExpenseCategory).filter(
            ExpenseCategory.organization_id == org_id,
            ExpenseCategory.key == "conference_travel",
        ).count() == 1

        try:
            asyncio.run(service.confirm_action(pending_id))
            raised = None
        except ChatConfirmationError as exc:
            raised = exc
        assert raised is not None
    finally:
        db.close()


def test_set_expense_category_write_tool_is_never_auto_executed(monkeypatch, fresh_org):
    from cfo.models import Expense

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        exp = _seed_pending_expense(db, org_id, supplier_name="ספק לשינוי קטגוריה")
        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "set_expense_category", {
                    "expense_id": exp["id"], "category": "rent",
                })],
            ),
        ])
        service = AIChatService(db, org_id, user_id=1)
        result = asyncio.run(service.send_message("s1", "שנה את הקטגוריה של ההוצאה הזו לשכירות"))

        assert result["pending_action"]["tool"] == "set_expense_category"
        row = db.query(Expense).filter(Expense.id == exp["id"]).first()
        assert row.category != "rent"
    finally:
        db.close()


def test_confirm_action_executes_set_expense_category_successfully(monkeypatch, fresh_org):
    from cfo.models import Expense

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        exp = _seed_pending_expense(db, org_id, supplier_name="ספק לשינוי קטגוריה 2")
        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "set_expense_category", {
                    "expense_id": exp["id"], "category": "rent",
                })],
            ),
        ])
        service = AIChatService(db, org_id, user_id=1)
        proposed = asyncio.run(service.send_message("s1", "שנה קטגוריה"))
        pending_id = proposed["message_id"]

        confirmed = asyncio.run(service.confirm_action(pending_id))
        assert confirmed["result"]["category"] == "rent"

        row = db.query(Expense).filter(Expense.id == exp["id"]).first()
        assert row.category == "rent"
    finally:
        db.close()


def test_classify_pending_expenses_write_tool_is_never_auto_executed(monkeypatch, fresh_org):
    from cfo.models import Expense

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        exp = _seed_pending_expense(db, org_id, supplier_name="תחנת דלק פז")
        db.query(Expense).filter(Expense.id == exp["id"]).update({"category": None})
        db.commit()

        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "classify_pending_expenses", {})],
            ),
        ])
        service = AIChatService(db, org_id, user_id=1)
        result = asyncio.run(service.send_message("s1", "סווג את כל ההוצאות הממתינות"))

        assert result["pending_action"]["tool"] == "classify_pending_expenses"
        db.expire_all()
        row = db.query(Expense).filter(Expense.id == exp["id"]).first()
        assert row.category is None  # לא בוצע עדיין
    finally:
        db.close()


def test_confirm_action_executes_classify_pending_expenses_successfully(monkeypatch, fresh_org):
    from cfo.models import Expense

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        exp = _seed_pending_expense(db, org_id, supplier_name="תחנת דלק פז")
        db.query(Expense).filter(Expense.id == exp["id"]).update({"category": None})
        db.commit()

        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "classify_pending_expenses", {})],
            ),
        ])
        service = AIChatService(db, org_id, user_id=1)
        proposed = asyncio.run(service.send_message("s1", "סווג את כל ההוצאות הממתינות"))
        pending_id = proposed["message_id"]

        confirmed = asyncio.run(service.confirm_action(pending_id))
        assert confirmed["result"]["classified"] == 1

        db.expire_all()
        row = db.query(Expense).filter(Expense.id == exp["id"]).first()
        assert row.category == "travel"
    finally:
        db.close()
