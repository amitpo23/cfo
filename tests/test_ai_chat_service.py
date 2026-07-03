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
