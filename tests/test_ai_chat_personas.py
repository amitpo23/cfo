"""Persona layer (package 1 of docs/superpowers/plans/2026-07-26-
conversational-channels-personas.md). Binding decision: a persona is a
prompt/tone/foreground-tools axis ONLY — never a permission gate. office/
role remain the single security gate, unchanged. These tests pin that
down: persona selection, prompt composition, and (the highest-risk case)
that no persona ever widens what a non-super-admin user can see or run.
"""
import asyncio
from types import SimpleNamespace

from cfo.database import SessionLocal
from cfo.services import ai_chat_personas
from cfo.services.ai_chat_personas import (
    DEFAULT_PERSONA,
    PERSONAS,
    build_system_prompt,
    resolve_persona,
)
from cfo.services.ai_chat_service import AIChatService

from tests.test_ai_chat_service import _patch_client, _text_block, _tool_use_block


def test_resolve_persona_defaults_to_cfo_when_key_is_none():
    persona = resolve_persona(None)
    assert persona.key == DEFAULT_PERSONA == "cfo"


def test_resolve_persona_falls_back_to_default_for_unknown_key():
    persona = resolve_persona("some-made-up-persona")
    assert persona.key == DEFAULT_PERSONA


def test_resolve_persona_returns_the_requested_known_persona():
    assert resolve_persona("bookkeeper").key == "bookkeeper"
    assert resolve_persona("accountant").key == "accountant"
    assert resolve_persona("cfo").key == "cfo"


def test_all_three_personas_are_registered_with_hebrew_titles():
    assert set(PERSONAS) == {"bookkeeper", "cfo", "accountant"}
    for persona in PERSONAS.values():
        assert persona.title_he
        assert persona.prompt_addendum
        # ההנחיה על כלי הבכורה חיה בתוך הפרומפט עצמו — מקור אמת יחיד
        assert "כלי הבכורה" in persona.prompt_addendum


def test_build_system_prompt_contains_base_and_persona_block():
    persona = PERSONAS["bookkeeper"]
    prompt = build_system_prompt(persona, include_office=False)
    assert ai_chat_personas.BASE_SYSTEM_PROMPT in prompt
    assert persona.prompt_addendum in prompt
    assert ai_chat_personas.OFFICE_SYSTEM_PROMPT_ADDENDUM not in prompt


def test_build_system_prompt_includes_office_addendum_only_when_requested():
    persona = PERSONAS["cfo"]
    without_office = build_system_prompt(persona, include_office=False)
    with_office = build_system_prompt(persona, include_office=True)
    assert ai_chat_personas.OFFICE_SYSTEM_PROMPT_ADDENDUM not in without_office
    assert ai_chat_personas.OFFICE_SYSTEM_PROMPT_ADDENDUM in with_office


def test_build_system_prompt_differs_per_persona():
    """Each persona's block must actually show up distinctly — otherwise the
    'tone anchor' promise in the plan is a no-op."""
    cfo_prompt = build_system_prompt(PERSONAS["cfo"], include_office=False)
    accountant_prompt = build_system_prompt(PERSONAS["accountant"], include_office=False)
    bookkeeper_prompt = build_system_prompt(PERSONAS["bookkeeper"], include_office=False)
    assert cfo_prompt != accountant_prompt != bookkeeper_prompt
    assert "מנהל כספים" in cfo_prompt
    assert "רואה חשבון" in accountant_prompt
    assert "מנהלת חשבונות" in bookkeeper_prompt


# ---------------------------------------------------------------------- #
# Highest-risk case: persona must never broaden the office-tool gate.
# ---------------------------------------------------------------------- #
def test_persona_does_not_broaden_tool_schema_for_a_regular_user(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        fake = _patch_client(monkeypatch, responses=[
            SimpleNamespace(stop_reason="end_turn", content=[_text_block("שלום")]),
        ])
        service = AIChatService(db, org_id, user_id=1, is_super_admin=False)
        asyncio.run(service.send_message("s1", "מה מצב הגבייה?", persona="bookkeeper"))

        tool_names = {t["name"] for t in fake.messages.calls[0]["tools"]}
        assert "list_office_clients" not in tool_names
        assert "register_office_client" not in tool_names
    finally:
        db.close()


def test_persona_does_not_allow_a_regular_user_to_execute_an_office_tool(monkeypatch, fresh_org):
    """Defense in depth mirrors test_ai_chat_service's office tests, but
    with a persona set — proving the persona layer sits strictly above (and
    never inside) the office security gate."""
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
        result = asyncio.run(
            service.send_message("s1", "תראה לי את כל תיקי הלקוחות", persona="accountant")
        )

        assert result["pending_action"] is None
        # The tool must never have actually run — the fed-back tool_result
        # is a refusal, not real roster data (totals/clients keys).
        second_call_messages = fake.messages.calls[1]["messages"]
        tool_result_content = second_call_messages[-1]["content"][0]["content"]
        assert "totals" not in tool_result_content
        assert "error" in tool_result_content
    finally:
        db.close()


def test_super_admin_still_gets_office_tools_regardless_of_persona(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        fake = _patch_client(monkeypatch, responses=[
            SimpleNamespace(stop_reason="end_turn", content=[_text_block("שלום")]),
        ])
        service = AIChatService(db, org_id, user_id=1, is_super_admin=True)
        asyncio.run(service.send_message("s1", "מה שלום המשרד?", persona="bookkeeper"))

        tool_names = {t["name"] for t in fake.messages.calls[0]["tools"]}
        assert "list_office_clients" in tool_names
    finally:
        db.close()


def test_send_message_with_persona_passes_persona_prompt_to_the_client(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        fake = _patch_client(monkeypatch, responses=[
            SimpleNamespace(stop_reason="end_turn", content=[_text_block("שלום")]),
        ])
        service = AIChatService(db, org_id, user_id=1, is_super_admin=False)
        asyncio.run(service.send_message("s1", "מה חסר לי?", persona="bookkeeper"))

        system_prompt = fake.messages.calls[0]["system"]
        assert "מנהלת חשבונות" in system_prompt
        # מ-18/08/2026 "רואה חשבון" מופיע גם ב-BASE (ערנות חשבונאית
        # תמידית, לא תלוית-כובע) — ולכן הבידוד הנכון לבדוק הוא תוספת
        # הכובע הייחודית של accountant, לא המחרוזת הגסה.
        assert "בכובע רואה חשבון (Accountant)" not in system_prompt
    finally:
        db.close()


def test_send_message_without_persona_defaults_to_cfo_prompt(monkeypatch, fresh_org):
    """Backward compatibility: the existing UI doesn't send `persona` at
    all yet — it must keep working exactly as before, defaulting to cfo."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        fake = _patch_client(monkeypatch, responses=[
            SimpleNamespace(stop_reason="end_turn", content=[_text_block("שלום")]),
        ])
        service = AIChatService(db, org_id, user_id=1, is_super_admin=False)
        asyncio.run(service.send_message("s1", "מה מצב התזרים?"))

        system_prompt = fake.messages.calls[0]["system"]
        assert "מנהל כספים" in system_prompt
    finally:
        db.close()


def test_send_message_with_unknown_persona_falls_back_silently(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        fake = _patch_client(monkeypatch, responses=[
            SimpleNamespace(stop_reason="end_turn", content=[_text_block("שלום")]),
        ])
        service = AIChatService(db, org_id, user_id=1, is_super_admin=False)
        result = asyncio.run(
            service.send_message("s1", "שאלה כלשהי", persona="not-a-real-persona")
        )

        assert result["reply"] == "שלום"
        system_prompt = fake.messages.calls[0]["system"]
        assert "מנהל כספים" in system_prompt
    finally:
        db.close()
