"""תכנית מושקו (docs/superpowers/plans/2026-07-27-moshko-full-bot.md),
חבילות C ו-D: כלי email_report, הרחבת חוזה הכלים ל-needs_user, וכלי אישור
דיווח המע"מ (propose_vat_filing_approval / list_pending_approvals).

אין רשת חיה בשום מקום כאן: SMTP וגם verify_filing/vat_report_period
מוזרקים/מדומים (monkeypatch) — הבדיקות בודקות את הלוגיקה של הכלים עצמם,
לא את השירותים שכבר יש להם קובצי טסט נפרדים.
"""
import asyncio
from types import SimpleNamespace

import pytest

from cfo.database import SessionLocal
from cfo.models import Contact, ContactType, IrreversibleActionRequest, User
from cfo.services import daily_reports_service, filing_verification
from cfo.services.ai_chat_service import AIChatService
from cfo.services.ai_chat_tools import TOOLS, ChatTool
from cfo.services.irreversible_action_service import IrreversibleActionService


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


def _org_user(fresh_org, db):
    """fresh_org registers exactly one (ADMIN) user for its new org — fetch
    the real User row, since propose_vat_filing_approval needs an actual
    User (not just an id) to pass to IrreversibleActionService.propose."""
    org_id = fresh_org()["org_id"]
    user = db.query(User).filter(User.organization_id == org_id).first()
    assert user is not None
    return org_id, user


def _configure_smtp(monkeypatch):
    from cfo.config import settings as global_settings
    monkeypatch.setattr(global_settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(global_settings, "smtp_from", "rezef@example.com")
    monkeypatch.setattr(global_settings, "smtp_user", None)
    monkeypatch.setattr(global_settings, "smtp_password", None)
    return global_settings


def _disable_smtp(monkeypatch):
    from cfo.config import settings as global_settings
    monkeypatch.setattr(global_settings, "smtp_host", None)
    return global_settings


# ---------------------------------------------------------------------- #
# Package C — email_report
# ---------------------------------------------------------------------- #

def test_email_report_is_write_category():
    assert TOOLS["email_report"].category == "write"


def test_email_report_write_tool_is_never_auto_executed(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _configure_smtp(monkeypatch)
        send_calls = []

        async def spy_send(*args, **kwargs):
            send_calls.append((args, kwargs))
            return True

        monkeypatch.setattr("cfo.services.email_sender.send_email_smtp", spy_send)

        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "email_report", {
                    "report_type": "profit_loss",
                    "recipient_email": "cfo@example.com",
                })],
            ),
        ])
        service = AIChatService(db, org_id, user_id=1)
        result = asyncio.run(service.send_message("s1", "שלח לי דוח רווח והפסד למייל"))

        assert result["pending_action"]["tool"] == "email_report"
        assert result["pending_action"]["input"]["recipient_email"] == "cfo@example.com"
        # The write-gate must have prevented the tool (and therefore the
        # actual SMTP send) from running at all on this turn.
        assert send_calls == []
    finally:
        db.close()


def test_email_report_not_configured_when_smtp_missing(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _disable_smtp(monkeypatch)

        called = []

        async def fake_send(*args, **kwargs):
            called.append((args, kwargs))
            return True  # would be a lie if reached — must never be reached

        monkeypatch.setattr("cfo.services.email_sender.send_email_smtp", fake_send)

        result = asyncio.run(TOOLS["email_report"].fn(
            db, org_id, report_type="profit_loss", recipient_email="a@b.com",
        ))
        assert result["status"] == "not_configured"
        assert called == []
    finally:
        db.close()


def test_email_report_recipient_verified_as_contact(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _configure_smtp(monkeypatch)
        db.add(Contact(
            organization_id=org_id, name="רואה חשבון חיצוני",
            contact_type=ContactType.VENDOR, email="accountant@example.com",
        ))
        db.commit()

        async def fake_send(to, subject, body, settings, *, attachments=None):
            return True

        monkeypatch.setattr("cfo.services.email_sender.send_email_smtp", fake_send)

        result = asyncio.run(TOOLS["email_report"].fn(
            db, org_id, report_type="profit_loss", recipient_email="accountant@example.com",
        ))
        assert result["status"] == "sent"
        assert result["recipient_verified_as"] == "contact:רואה חשבון חיצוני"
    finally:
        db.close()


def test_email_report_recipient_verified_as_user_supplied(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _configure_smtp(monkeypatch)

        async def fake_send(to, subject, body, settings, *, attachments=None):
            return True

        monkeypatch.setattr("cfo.services.email_sender.send_email_smtp", fake_send)

        result = asyncio.run(TOOLS["email_report"].fn(
            db, org_id, report_type="profit_loss", recipient_email="someone-new@example.com",
        ))
        assert result["status"] == "sent"
        assert result["recipient_verified_as"] == "user_supplied"
    finally:
        db.close()


def test_email_report_sends_nonempty_attachment(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _configure_smtp(monkeypatch)

        captured = {}

        async def fake_send(to, subject, body, settings, *, attachments=None):
            captured["attachments"] = attachments
            captured["to"] = to
            captured["subject"] = subject
            return True

        monkeypatch.setattr("cfo.services.email_sender.send_email_smtp", fake_send)

        result = asyncio.run(TOOLS["email_report"].fn(
            db, org_id, report_type="cash_flow", recipient_email="a@b.com", period_months=3,
        ))
        assert result["status"] == "sent"
        assert captured["to"] == "a@b.com"
        assert len(captured["attachments"]) == 1
        filename, content, subtype = captured["attachments"][0]
        assert filename.endswith(".xlsx")
        assert len(content) > 0
        assert "spreadsheetml" in subtype
    finally:
        db.close()


def test_email_report_failed_send_is_reported_honestly(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _configure_smtp(monkeypatch)

        async def fake_send(to, subject, body, settings, *, attachments=None):
            return False

        monkeypatch.setattr("cfo.services.email_sender.send_email_smtp", fake_send)

        result = asyncio.run(TOOLS["email_report"].fn(
            db, org_id, report_type="balance_sheet", recipient_email="a@b.com",
        ))
        assert result["status"] == "failed"
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# Package D1 — needs_user contract
# ---------------------------------------------------------------------- #

def test_propose_vat_filing_approval_flagged_needs_user():
    assert TOOLS["propose_vat_filing_approval"].needs_user is True


def test_needs_user_regression_on_existing_tools():
    """None of the ~39 pre-existing tools should have opted into needs_user
    by accident — only the two new ones from this plan."""
    flagged = {name for name, t in TOOLS.items() if t.needs_user}
    assert flagged == {"propose_vat_filing_approval"}


def test_needs_user_tool_receives_user_id_kwarg(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        captured = []

        async def fake_fn(db, org_id, **kwargs):
            captured.append(kwargs)
            return {"ok": True}

        fake_tool = ChatTool(
            name="fake_needs_user", description="x", input_schema={"type": "object", "properties": {}},
            category="read", fn=fake_fn, needs_user=True,
        )
        monkeypatch.setitem(TOOLS, "fake_needs_user", fake_tool)

        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "fake_needs_user", {})],
            ),
            SimpleNamespace(stop_reason="end_turn", content=[_text_block("סיימתי")]),
        ])
        service = AIChatService(db, org_id, user_id=42)
        asyncio.run(service.send_message("s1", "בדיקה"))

        assert captured == [{"_user_id": 42}]
    finally:
        db.close()


def test_tool_without_needs_user_does_not_receive_user_id_kwarg(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        captured = []

        async def fake_fn(db, org_id, **kwargs):
            captured.append(kwargs)
            return {"ok": True}

        fake_tool = ChatTool(
            name="fake_no_needs_user", description="x", input_schema={"type": "object", "properties": {}},
            category="read", fn=fake_fn,
        )
        monkeypatch.setitem(TOOLS, "fake_no_needs_user", fake_tool)

        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "fake_no_needs_user", {})],
            ),
            SimpleNamespace(stop_reason="end_turn", content=[_text_block("סיימתי")]),
        ])
        service = AIChatService(db, org_id, user_id=42)
        asyncio.run(service.send_message("s1", "בדיקה"))

        assert captured == [{}]
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# Package D2 — propose_vat_filing_approval
# ---------------------------------------------------------------------- #

_FAIL_VERIFICATION = {
    "status": "fail",
    "checks": [{"name": "reconciliation", "label": "x", "passed": False, "details": "פער"}],
    "period": "2026-07",
    "basis": "document",
}

_PASS_VERIFICATION = {
    "status": "pass",
    "checks": [{"name": "reconciliation", "label": "x", "passed": True, "details": "תואם"}],
    "period": "2026-07",
    "basis": "document",
}

_REPORT_NUMBERS = {
    "period": "2026-07", "output_vat": 1000.0, "input_vat": 400.0, "net_vat": 600.0,
}


def _patch_verify_filing(monkeypatch, result):
    def fake(db, org_id, year, month, *, months=1, basis="document"):
        return result
    monkeypatch.setattr(filing_verification, "verify_filing", fake)


def _patch_vat_report_period(monkeypatch, result=None):
    result = result or _REPORT_NUMBERS

    def fake(db, org_id, year, month, *, months=1, basis="document"):
        return result
    monkeypatch.setattr(daily_reports_service, "vat_report_period", fake)


def test_blocked_by_verification_fail_creates_no_request(monkeypatch, fresh_org):
    db = SessionLocal()
    try:
        org_id, user = _org_user(fresh_org, db)
        _patch_verify_filing(monkeypatch, _FAIL_VERIFICATION)

        result = asyncio.run(TOOLS["propose_vat_filing_approval"].fn(
            db, org_id, year=2026, month=7, _user_id=user.id,
        ))

        assert result["status"] == "blocked_by_verification"
        assert db.query(IrreversibleActionRequest).filter(
            IrreversibleActionRequest.organization_id == org_id,
        ).count() == 0
    finally:
        db.close()


def test_pass_creates_proposed_request_with_numbers_and_caveat(monkeypatch, fresh_org):
    db = SessionLocal()
    try:
        org_id, user = _org_user(fresh_org, db)
        _patch_verify_filing(monkeypatch, _PASS_VERIFICATION)
        _patch_vat_report_period(monkeypatch)

        result = asyncio.run(TOOLS["propose_vat_filing_approval"].fn(
            db, org_id, year=2026, month=7, _user_id=user.id,
        ))

        assert result["status"] == "proposed"
        assert result["transmission"] == "manual_via_sumit"
        assert "SUMIT" in result["caveat"]
        assert "רצף אינו משדר" in result["caveat"]

        row = db.query(IrreversibleActionRequest).filter(
            IrreversibleActionRequest.organization_id == org_id,
        ).one()
        assert row.status == "proposed"
        assert row.action_type == "filing_submission"
        assert row.payload["output_vat"] == 1000.0
        assert row.payload["input_vat"] == 400.0
        assert row.payload["net_vat"] == 600.0
    finally:
        db.close()


def test_confirm_action_path_passes_user_id_to_propose_vat_filing_approval(monkeypatch, fresh_org):
    """propose_vat_filing_approval is category='write' + needs_user=True, so
    in production it is ALWAYS invoked from confirm_action (the second of
    the two call sites the plan names — 'בשני מקומות הקריאה'), never from
    the auto-executing read loop. This proves that path wires _user_id
    correctly end to end, through the real AIChatService (not calling
    TOOLS[...].fn directly like the other tests here)."""
    db = SessionLocal()
    try:
        org_id, user = _org_user(fresh_org, db)
        _patch_verify_filing(monkeypatch, _PASS_VERIFICATION)
        _patch_vat_report_period(monkeypatch)

        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "propose_vat_filing_approval", {
                    "year": 2026, "month": 7,
                })],
            ),
        ])
        # Deliberately the REAL user of this org (not the hardcoded user_id=1
        # every other test in test_ai_chat_service.py uses) — see the
        # org-mismatch assertion below.
        service = AIChatService(db, org_id, user_id=user.id)
        proposed = asyncio.run(service.send_message("s1", "אשר את הדיווח"))
        pending_id = proposed["message_id"]

        confirmed = asyncio.run(service.confirm_action(pending_id))
        assert confirmed["result"]["status"] == "proposed"

        row = db.query(IrreversibleActionRequest).filter(
            IrreversibleActionRequest.organization_id == org_id,
        ).one()
        assert row.proposed_by_user_id == user.id
    finally:
        db.close()


def test_confirm_action_path_rejects_mismatched_user_id(monkeypatch, fresh_org):
    """Defense in depth inside the tool itself: if _user_id somehow doesn't
    belong to this organization, the tool must refuse, not silently propose
    under someone else's identity. user_id=1 here is the wrong org's owner
    for THIS fresh org — exactly the mistake the other tests' user_id=1
    convention would make if reused for a needs_user tool."""
    db = SessionLocal()
    try:
        org_id, _user = _org_user(fresh_org, db)
        _patch_verify_filing(monkeypatch, _PASS_VERIFICATION)
        _patch_vat_report_period(monkeypatch)

        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "propose_vat_filing_approval", {
                    "year": 2026, "month": 7,
                })],
            ),
        ])
        service = AIChatService(db, org_id, user_id=1)
        proposed = asyncio.run(service.send_message("s1", "אשר את הדיווח"))
        confirmed = asyncio.run(service.confirm_action(proposed["message_id"]))

        assert confirmed["result"]["status"] == "failed"
        assert db.query(IrreversibleActionRequest).filter(
            IrreversibleActionRequest.organization_id == org_id,
        ).count() == 0
    finally:
        db.close()


def _seed_clean_period(db, org_id):
    """Same fixture shape as test_filing_verification.py's
    test_all_three_checks_pass_on_clean_period — real Invoice+Bill+SyncRun
    that makes the REAL (unmocked) verify_filing return status='pass'."""
    from datetime import date, datetime
    from decimal import Decimal
    from cfo.models import Bill, BillStatus, Invoice, InvoiceStatus, SyncRun, SyncStatus

    c = Contact(organization_id=org_id, name="לקוח", contact_type=ContactType.CUSTOMER)
    db.add(c)
    db.flush()
    db.add(Invoice(
        organization_id=org_id, contact_id=c.id, external_id="i1", source="sumit",
        invoice_number="100", issue_date=date(2026, 5, 10), status=InvoiceStatus.SENT,
        subtotal=Decimal("1000"), tax=Decimal("180"), total=Decimal("1180"),
        paid_amount=Decimal("0"), balance=Decimal("1180"),
    ))
    db.add(Bill(
        organization_id=org_id, external_id="b1", source="sumit", bill_number="B1",
        issue_date=date(2026, 5, 12), status=BillStatus.PAID,
        subtotal=Decimal("500"), tax=Decimal("90"), total=Decimal("590"),
        paid_amount=Decimal("590"), balance=Decimal("0"),
    ))
    db.add(SyncRun(
        organization_id=org_id, source="sumit", status=SyncStatus.COMPLETED,
        started_at=datetime.utcnow(), finished_at=datetime.utcnow(),
    ))
    db.commit()


def test_idempotent_double_call_with_real_unmocked_verify_filing(fresh_org):
    """No monkeypatch here — the real verify_filing (and its volatile
    sync-freshness/duplicate-check internals) runs twice for the exact same
    period. This is what actually proves the hashed payload is stable
    (only name+passed per check, no timestamps/details) — a mocked
    verify_filing can't catch a payload that changes between two real calls."""
    db = SessionLocal()
    try:
        org_id, user = _org_user(fresh_org, db)
        _seed_clean_period(db, org_id)

        first = asyncio.run(TOOLS["propose_vat_filing_approval"].fn(
            db, org_id, year=2026, month=5, _user_id=user.id,
        ))
        second = asyncio.run(TOOLS["propose_vat_filing_approval"].fn(
            db, org_id, year=2026, month=5, _user_id=user.id,
        ))

        assert first["status"] == "proposed"
        assert second["status"] == "proposed"
        assert first["request_id"] == second["request_id"]
        assert db.query(IrreversibleActionRequest).filter(
            IrreversibleActionRequest.organization_id == org_id,
        ).count() == 1
    finally:
        db.close()


def test_idempotent_double_call_same_period_creates_one_request(monkeypatch, fresh_org):
    db = SessionLocal()
    try:
        org_id, user = _org_user(fresh_org, db)
        _patch_verify_filing(monkeypatch, _PASS_VERIFICATION)
        _patch_vat_report_period(monkeypatch)

        first = asyncio.run(TOOLS["propose_vat_filing_approval"].fn(
            db, org_id, year=2026, month=7, _user_id=user.id,
        ))
        second = asyncio.run(TOOLS["propose_vat_filing_approval"].fn(
            db, org_id, year=2026, month=7, _user_id=user.id,
        ))

        assert first["request_id"] == second["request_id"]
        assert db.query(IrreversibleActionRequest).filter(
            IrreversibleActionRequest.organization_id == org_id,
        ).count() == 1
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# Package D3 — list_pending_approvals
# ---------------------------------------------------------------------- #

def test_list_pending_approvals_scoped_to_org(fresh_org):
    db = SessionLocal()
    try:
        org_a, user_a = _org_user(fresh_org, db)
        org_b, user_b = _org_user(fresh_org, db)

        IrreversibleActionService(db, org_a).propose(
            proposed_by=user_a, action_type="filing_submission",
            payload={"x": 1}, idempotency_key="a-1", description="בקשה א",
        )
        IrreversibleActionService(db, org_b).propose(
            proposed_by=user_b, action_type="filing_submission",
            payload={"x": 2}, idempotency_key="b-1", description="בקשה ב",
        )

        result_a = asyncio.run(TOOLS["list_pending_approvals"].fn(db, org_a))
        names_a = {item["description"] for item in result_a["pending"]}
        assert names_a == {"בקשה א"}

        result_b = asyncio.run(TOOLS["list_pending_approvals"].fn(db, org_b))
        names_b = {item["description"] for item in result_b["pending"]}
        assert names_b == {"בקשה ב"}
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# Package D4 — persona prompt updates
# ---------------------------------------------------------------------- #

def test_base_prompt_tells_the_model_about_email_report_and_filing_approval():
    from cfo.services.ai_chat_personas import BASE_SYSTEM_PROMPT
    assert "email_report" in BASE_SYSTEM_PROMPT
    assert "propose_vat_filing_approval" in BASE_SYSTEM_PROMPT


def test_accountant_addendum_requires_verify_filing_before_filing_approval():
    from cfo.services.ai_chat_personas import PERSONAS
    addendum = PERSONAS["accountant"].prompt_addendum
    assert "verify_filing" in addendum
    assert "propose_vat_filing_approval" in addendum
    assert "SUMIT" in addendum


def test_cfo_addendum_requires_data_backed_answers_to_what_to_improve():
    from cfo.services.ai_chat_personas import PERSONAS
    addendum = PERSONAS["cfo"].prompt_addendum
    assert "get_cfo_insights" in addendum
    assert "get_ar_health" in addendum
    assert "get_credit_line_status" in addendum
    assert "get_cashflow" in addendum
