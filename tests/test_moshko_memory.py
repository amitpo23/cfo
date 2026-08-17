"""חבילה E — זיכרון לומד של מושקו
(docs/superpowers/plans/2026-07-27b-moshko-memory-and-whatsapp.md).

הפניית עיצוב: Hermes Agent — שני scope (עסק/משתמש), הזרקה קפואה
לפרומפט, תקרת-תווים שכופה אוצרות. הטסטים כאן מכסים: כתיבה/קריאה בשני
ה-scope, בידוד בין משתמשים ובין ארגונים, אכיפת תקרה + אזהרת חצייה,
דדופ תוכן זהה, update/forget בהתאמת תת-מחרוזת (כולל ההתאמה המרובה
הבטיחותית), render_memory_block, תאימות אחורה של build_system_prompt,
והכלים memory/search_history ברמת ai_chat_service/ai_chat_tools."""
import asyncio
from types import SimpleNamespace

from cfo.database import SessionLocal
from cfo.models import ChatMessage, User
from cfo.services import moshko_memory
from cfo.services.ai_chat_personas import PERSONAS, build_system_prompt
from cfo.services.ai_chat_service import AIChatService
from cfo.services.ai_chat_tools import TOOLS

from tests.test_ai_chat_service import _patch_client, _text_block, _tool_use_block


def _org_and_user(fresh_org, db):
    org_id = fresh_org()["org_id"]
    user = db.query(User).filter(User.organization_id == org_id).one()
    return org_id, user


# ---------------------------------------------------------------------- #
# Basic read/write roundtrip, both scopes.
# ---------------------------------------------------------------------- #

def test_remember_org_scope_write_and_read_roundtrip(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = moshko_memory.remember(db, org_id, content="הבנק הראשי הוא בנק דיסקונט")
        assert result["status"] == "ok"

        memories = moshko_memory.list_memories(db, org_id)
        assert len(memories) == 1
        assert memories[0]["scope"] == "org"
        assert memories[0]["content"] == "הבנק הראשי הוא בנק דיסקונט"
    finally:
        db.close()


def test_remember_user_scope_write_and_read_roundtrip(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = moshko_memory.remember(
            db, org_id, content="מעדיף תשובות קצרות", scope="user", user_id=1,
        )
        assert result["status"] == "ok"

        memories = moshko_memory.list_memories(db, org_id, user_id=1)
        by_content = {m["content"]: m for m in memories}
        assert "מעדיף תשובות קצרות" in by_content
        assert by_content["מעדיף תשובות קצרות"]["scope"] == "user"
    finally:
        db.close()


def test_remember_user_scope_requires_user_id():
    db = SessionLocal()
    try:
        try:
            moshko_memory.remember(db, 1, content="עובדה", scope="user")
            raised = None
        except ValueError as exc:
            raised = exc
        assert raised is not None
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# Isolation: user-to-user (within an org) and org-to-org.
# ---------------------------------------------------------------------- #

def test_user_cannot_see_another_users_personal_memory(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        moshko_memory.remember(db, org_id, content="סוד של משתמש א", scope="user", user_id=1)
        moshko_memory.remember(db, org_id, content="סוד של משתמש ב", scope="user", user_id=2)

        contents_a = {m["content"] for m in moshko_memory.list_memories(db, org_id, user_id=1)}
        contents_b = {m["content"] for m in moshko_memory.list_memories(db, org_id, user_id=2)}

        assert "סוד של משתמש א" in contents_a
        assert "סוד של משתמש ב" not in contents_a
        assert "סוד של משתמש ב" in contents_b
        assert "סוד של משתמש א" not in contents_b
    finally:
        db.close()


def test_org_facts_are_visible_to_every_user_but_personal_memory_is_not(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        moshko_memory.remember(db, org_id, content="עובדה משותפת לכל הארגון")
        moshko_memory.remember(db, org_id, content="פרטי למשתמש 1 בלבד", scope="user", user_id=1)

        for_user_1 = {m["content"] for m in moshko_memory.list_memories(db, org_id, user_id=1)}
        for_user_2 = {m["content"] for m in moshko_memory.list_memories(db, org_id, user_id=2)}
        no_user = {m["content"] for m in moshko_memory.list_memories(db, org_id)}

        assert "עובדה משותפת לכל הארגון" in for_user_1
        assert "עובדה משותפת לכל הארגון" in for_user_2
        assert "עובדה משותפת לכל הארגון" in no_user
        assert "פרטי למשתמש 1 בלבד" in for_user_1
        assert "פרטי למשתמש 1 בלבד" not in for_user_2
        assert "פרטי למשתמש 1 בלבד" not in no_user
    finally:
        db.close()


def test_org_isolation_between_organizations(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        moshko_memory.remember(db, org_a, content="עובדה של ארגון א בלבד")

        memories_a = moshko_memory.list_memories(db, org_a)
        memories_b = moshko_memory.list_memories(db, org_b)
        assert len(memories_a) == 1
        assert memories_b == []
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# Cap enforcement + consolidation warning.
# ---------------------------------------------------------------------- #

def test_remember_blocks_write_when_cap_reached(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        monkeypatch.setattr(moshko_memory, "ORG_MEMORY_CHAR_CAP", 20)

        first = moshko_memory.remember(db, org_id, content="A" * 15)
        assert first["status"] == "ok"

        second = moshko_memory.remember(db, org_id, content="B" * 10)
        assert second["status"] == "cap_reached"
        assert second["message"]
        assert "usage" in second

        memories = moshko_memory.list_memories(db, org_id)
        assert len(memories) == 1  # the blocked write never happened
    finally:
        db.close()


def test_remember_blocks_write_when_user_cap_reached(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        monkeypatch.setattr(moshko_memory, "USER_MEMORY_CHAR_CAP", 20)

        first = moshko_memory.remember(db, org_id, content="A" * 15, scope="user", user_id=1)
        assert first["status"] == "ok"

        second = moshko_memory.remember(db, org_id, content="B" * 10, scope="user", user_id=1)
        assert second["status"] == "cap_reached"

        # A different user's cap is untouched.
        third = moshko_memory.remember(db, org_id, content="C" * 15, scope="user", user_id=2)
        assert third["status"] == "ok"
    finally:
        db.close()


def test_remember_warns_above_consolidation_threshold_but_still_writes(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        monkeypatch.setattr(moshko_memory, "ORG_MEMORY_CHAR_CAP", 100)

        result = moshko_memory.remember(db, org_id, content="A" * 85)  # 85% of cap
        assert result["status"] == "ok"
        assert "warning" in result

        below_threshold = moshko_memory.remember(
            db, org_id, content="B" * 5, scope="user", user_id=1,
        )
        assert "warning" not in below_threshold
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# Dedup: identical content (normalized) never creates a duplicate row.
# ---------------------------------------------------------------------- #

def test_remember_dedups_identical_content_case_and_whitespace_insensitive(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        first = moshko_memory.remember(db, org_id, content="  הספק הקבוע הוא חברת החשמל  ")
        assert first["status"] == "ok"

        second = moshko_memory.remember(db, org_id, content="הספק הקבוע הוא חברת החשמל")
        assert second["status"] == "already_known"
        assert second["id"] == first["id"]

        assert len(moshko_memory.list_memories(db, org_id)) == 1
    finally:
        db.close()


def test_remember_dedup_is_scoped_separately_for_org_and_user(fresh_org):
    """Same wording as both an org fact and a personal memory must not
    collide across scopes — they're different bags of facts."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        moshko_memory.remember(db, org_id, content="עובדה זהה בניסוח")
        second = moshko_memory.remember(
            db, org_id, content="עובדה זהה בניסוח", scope="user", user_id=1,
        )
        assert second["status"] == "ok"
        assert len(moshko_memory.list_memories(db, org_id, user_id=1)) == 2
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# update_memory / forget — substring match, ambiguity safety.
# ---------------------------------------------------------------------- #

def test_update_memory_single_match_replaces_content(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        moshko_memory.remember(db, org_id, content="הבנק הראשי הוא בנק לאומי")

        result = moshko_memory.update_memory(
            db, org_id, match="הבנק הראשי", content="הבנק הראשי הוא בנק דיסקונט",
        )
        assert result["status"] == "ok"

        memories = moshko_memory.list_memories(db, org_id)
        assert memories[0]["content"] == "הבנק הראשי הוא בנק דיסקונט"
    finally:
        db.close()


def test_update_memory_blocks_write_when_it_would_exceed_cap(monkeypatch, fresh_org):
    """The cap is the only mechanism preventing unbounded growth of the
    block frozen-injected into every turn's system prompt — it must hold
    for update, not just for a fresh add (otherwise a model blocked by
    cap_reached on add could bypass the cap via update on a short row with
    much longer replacement content)."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        monkeypatch.setattr(moshko_memory, "ORG_MEMORY_CHAR_CAP", 20)
        moshko_memory.remember(db, org_id, content="A" * 10)

        result = moshko_memory.update_memory(db, org_id, match="A", content="B" * 30)
        assert result["status"] == "cap_reached"

        memories = moshko_memory.list_memories(db, org_id)
        assert memories[0]["content"] == "A" * 10  # untouched
    finally:
        db.close()


def test_update_memory_no_match_returns_not_found(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = moshko_memory.update_memory(db, org_id, match="לא קיים", content="חדש")
        assert result["status"] == "not_found"
    finally:
        db.close()


def test_update_memory_multiple_matches_does_not_update_and_returns_candidates(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        moshko_memory.remember(db, org_id, content="הספק א מספק ציוד משרדי")
        moshko_memory.remember(db, org_id, content="הספק ב מספק ציוד משרדי גם כן")

        result = moshko_memory.update_memory(
            db, org_id, match="ציוד משרדי", content="עודכן",
        )
        assert result["status"] == "ambiguous"
        assert len(result["candidates"]) == 2

        memories = moshko_memory.list_memories(db, org_id)
        assert "עודכן" not in {m["content"] for m in memories}  # nothing changed
    finally:
        db.close()


def test_forget_single_match_deletes(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        moshko_memory.remember(db, org_id, content="עובדה למחיקה ייחודית לגמרי")

        result = moshko_memory.forget(db, org_id, match="למחיקה ייחודית")
        assert result["status"] == "ok"
        assert moshko_memory.list_memories(db, org_id) == []
    finally:
        db.close()


def test_forget_no_match_returns_not_found_without_side_effects(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        moshko_memory.remember(db, org_id, content="עובדה קיימת")

        result = moshko_memory.forget(db, org_id, match="לא קיים בכלל")
        assert result["status"] == "not_found"
        assert len(moshko_memory.list_memories(db, org_id)) == 1
    finally:
        db.close()


def test_forget_multiple_matches_does_not_delete_and_returns_candidates(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        moshko_memory.remember(db, org_id, content="הספק א מספק ציוד משרדי")
        moshko_memory.remember(db, org_id, content="הספק ב מספק ציוד משרדי גם כן")

        result = moshko_memory.forget(db, org_id, match="ציוד משרדי")
        assert result["status"] == "ambiguous"
        assert len(result["candidates"]) == 2
        assert len(moshko_memory.list_memories(db, org_id)) == 2  # nothing deleted
    finally:
        db.close()


def test_forget_is_scoped_and_cannot_delete_another_users_memory(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        moshko_memory.remember(db, org_id, content="זיכרון פרטי ייחודי", scope="user", user_id=1)

        # Attempting the same match without targeting user 1's scope (i.e.
        # as another user / org scope) must not find or delete it.
        result = moshko_memory.forget(db, org_id, match="זיכרון פרטי ייחודי", user_id=2)
        assert result["status"] == "not_found"
        assert len(moshko_memory.list_memories(db, org_id, user_id=1)) == 1
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# render_memory_block — frozen injection block, Hebrew headers, honest-empty.
# ---------------------------------------------------------------------- #

def test_render_memory_block_is_empty_string_when_no_memories(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        assert moshko_memory.render_memory_block(db, org_id, user_id=1) == ""
        assert moshko_memory.render_memory_block(db, org_id, user_id=None) == ""
    finally:
        db.close()


def test_render_memory_block_shows_only_org_header_when_no_personal_memory(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        moshko_memory.remember(db, org_id, content="עובדה על העסק")

        block = moshko_memory.render_memory_block(db, org_id, user_id=1)
        assert "## מה אני יודע על העסק" in block
        assert "עובדה על העסק" in block
        assert "## מה אני יודע עליך" not in block
    finally:
        db.close()


def test_render_memory_block_shows_both_headers_and_is_isolated_per_user(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        moshko_memory.remember(db, org_id, content="עובדה על העסק")
        moshko_memory.remember(db, org_id, content="העדפה אישית של המשתמש 1", scope="user", user_id=1)

        block_user_1 = moshko_memory.render_memory_block(db, org_id, user_id=1)
        assert "## מה אני יודע על העסק" in block_user_1
        assert "## מה אני יודע עליך" in block_user_1
        assert "עובדה על העסק" in block_user_1
        assert "העדפה אישית של המשתמש 1" in block_user_1

        block_user_2 = moshko_memory.render_memory_block(db, org_id, user_id=2)
        assert "## מה אני יודע על העסק" in block_user_2
        assert "## מה אני יודע עליך" not in block_user_2
        assert "העדפה אישית של המשתמש 1" not in block_user_2
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# usage()
# ---------------------------------------------------------------------- #

def test_usage_reports_chars_and_cap_per_scope(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        moshko_memory.remember(db, org_id, content="A" * 10)
        moshko_memory.remember(db, org_id, content="B" * 5, scope="user", user_id=1)

        result = moshko_memory.usage(db, org_id, user_id=1)
        assert result["org"]["chars"] == 10
        assert result["org"]["cap"] == moshko_memory.ORG_MEMORY_CHAR_CAP
        assert result["user"]["chars"] == 5
        assert result["user"]["cap"] == moshko_memory.USER_MEMORY_CHAR_CAP

        no_user = moshko_memory.usage(db, org_id)
        assert "user" not in no_user
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# build_system_prompt — backward compatibility + memory injection.
# ---------------------------------------------------------------------- #

def test_build_system_prompt_backward_compatible_without_memory_block():
    persona = PERSONAS["cfo"]
    without_arg = build_system_prompt(persona, include_office=False)
    with_empty_block = build_system_prompt(persona, include_office=False, memory_block="")
    assert without_arg == with_empty_block


def test_build_system_prompt_includes_memory_block_when_provided():
    persona = PERSONAS["cfo"]
    block = "## מה אני יודע על העסק\n- עובדה לדוגמה"
    prompt = build_system_prompt(persona, include_office=False, memory_block=block)
    assert block in prompt

    without_block = build_system_prompt(persona, include_office=False)
    assert block not in without_block


def test_base_system_prompt_forbids_pulling_numbers_from_memory():
    from cfo.services.ai_chat_personas import BASE_SYSTEM_PROMPT
    assert "memory" in BASE_SYSTEM_PROMPT
    assert "honest-null" in BASE_SYSTEM_PROMPT


# ---------------------------------------------------------------------- #
# `memory` tool registration + write-gate (same confirmation-gate pattern
# as every other write tool — see test_ai_chat_service.py).
# ---------------------------------------------------------------------- #

def test_memory_tool_is_write_category_and_needs_user():
    assert TOOLS["memory"].category == "write"
    assert TOOLS["memory"].needs_user is True


def test_search_history_tool_is_read_category_and_needs_user():
    assert TOOLS["search_history"].category == "read"
    assert TOOLS["search_history"].needs_user is True


def test_memory_tool_add_is_never_auto_executed(monkeypatch, fresh_org):
    db = SessionLocal()
    try:
        org_id, user = _org_and_user(fresh_org, db)
        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[
                    _text_block("אני אזכור את זה."),
                    _tool_use_block("t1", "memory", {
                        "action": "add", "content": "הבנק הראשי הוא בנק הפועלים", "scope": "org",
                    }),
                ],
            ),
        ])
        service = AIChatService(db, org_id, user_id=user.id)
        result = asyncio.run(service.send_message("s1", "תזכור שהבנק הראשי הוא בנק הפועלים"))

        assert result["pending_action"]["tool"] == "memory"
        assert moshko_memory.list_memories(db, org_id) == []  # not written yet

        msg = db.query(ChatMessage).filter(ChatMessage.id == result["message_id"]).first()
        assert msg.pending_action is not None
        assert msg.executed is False
    finally:
        db.close()


def test_confirm_action_executes_memory_add_successfully(monkeypatch, fresh_org):
    db = SessionLocal()
    try:
        org_id, user = _org_and_user(fresh_org, db)
        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "memory", {
                    "action": "add", "content": "הבנק הראשי הוא בנק הפועלים", "scope": "org",
                })],
            ),
        ])
        service = AIChatService(db, org_id, user_id=user.id)
        proposed = asyncio.run(service.send_message("s1", "תזכור את זה"))
        pending_id = proposed["message_id"]

        confirmed = asyncio.run(service.confirm_action(pending_id))
        assert confirmed["result"]["status"] == "ok"

        memories = moshko_memory.list_memories(db, org_id)
        assert any(m["content"] == "הבנק הראשי הוא בנק הפועלים" for m in memories)
    finally:
        db.close()


def test_confirm_action_reports_honest_error_and_never_marks_executed_when_memory_add_is_capped(
    monkeypatch, fresh_org,
):
    """The cap is the only thing preventing the frozen-injected memory
    block from growing without bound — if a capped write were silently
    reported as success, the model would never be prompted to consolidate,
    and the user could never retry the pending action (it would already be
    burned as 'executed'). Same 'never fake success' contract already
    proven for register_office_client (test_ai_chat_service.py)."""
    from cfo.services.ai_chat_service import ChatConfirmationError

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        monkeypatch.setattr(moshko_memory, "ORG_MEMORY_CHAR_CAP", 10)
        moshko_memory.remember(db, org_id, content="A" * 10)  # fills the cap exactly

        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "memory", {
                    "action": "add", "content": "עובדה חדשה שלא נכנסת", "scope": "org",
                })],
            ),
        ])
        service = AIChatService(db, org_id, user_id=1)
        proposed = asyncio.run(service.send_message("s1", "תזכור עובדה נוספת"))
        pending_id = proposed["message_id"]

        try:
            asyncio.run(service.confirm_action(pending_id))
            raised = None
        except ChatConfirmationError as exc:
            raised = exc
        assert raised is not None

        msg = db.query(ChatMessage).filter(ChatMessage.id == pending_id).first()
        assert msg.executed is False
        # No fake "בוצע" confirmation message must have been persisted.
        session_messages = [
            m.content for m in db.query(ChatMessage).filter(
                ChatMessage.organization_id == org_id, ChatMessage.session_id == "s1",
            ).all()
        ]
        assert not any(c.startswith("בוצע:") for c in session_messages)

        memories = moshko_memory.list_memories(db, org_id)
        assert len(memories) == 1  # nothing new was written
    finally:
        db.close()


def test_confirm_action_reports_honest_error_when_forget_match_is_ambiguous(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        moshko_memory.remember(db, org_id, content="הספק א מספק ציוד משרדי")
        moshko_memory.remember(db, org_id, content="הספק ב מספק ציוד משרדי גם כן")

        from cfo.services.ai_chat_service import ChatConfirmationError

        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "memory", {
                    "action": "forget", "match": "ציוד משרדי", "scope": "org",
                })],
            ),
        ])
        service = AIChatService(db, org_id, user_id=1)
        proposed = asyncio.run(service.send_message("s1", "תשכח את הספק"))

        try:
            asyncio.run(service.confirm_action(proposed["message_id"]))
            raised = None
        except ChatConfirmationError as exc:
            raised = exc
        assert raised is not None
        assert len(moshko_memory.list_memories(db, org_id)) == 2  # nothing deleted
    finally:
        db.close()


def test_confirm_action_executes_memory_add_scoped_to_the_confirming_user(monkeypatch, fresh_org):
    """scope='user' writes must be attributed to the CONFIRMING user's real
    identity (never model-supplied) — same needs_user pattern proven for
    propose_vat_filing_approval."""
    db = SessionLocal()
    try:
        org_id, user = _org_and_user(fresh_org, db)
        _patch_client(monkeypatch, responses=[
            SimpleNamespace(
                stop_reason="tool_use",
                content=[_tool_use_block("t1", "memory", {
                    "action": "add", "content": "מעדיף תשובות ארוכות", "scope": "user",
                })],
            ),
        ])
        service = AIChatService(db, org_id, user_id=user.id)
        proposed = asyncio.run(service.send_message("s1", "תזכור שאני מעדיף תשובות ארוכות"))
        confirmed = asyncio.run(service.confirm_action(proposed["message_id"]))
        assert confirmed["result"]["status"] == "ok"

        assert any(
            m["content"] == "מעדיף תשובות ארוכות"
            for m in moshko_memory.list_memories(db, org_id, user_id=user.id)
        )
        assert not any(
            m["content"] == "מעדיף תשובות ארוכות"
            for m in moshko_memory.list_memories(db, org_id, user_id=user.id + 100000)
        )
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# `search_history` tool — complements the 30-message history cap.
# ---------------------------------------------------------------------- #

def test_search_history_tool_returns_only_same_user_and_org_messages(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(ChatMessage(
            organization_id=org_a, user_id=1, session_id="s1", role="user",
            content="דיברנו על תזרים מזומנים שבוע שעבר",
        ))
        db.add(ChatMessage(
            organization_id=org_a, user_id=2, session_id="s1", role="user",
            content="גם אני שאלתי על תזרים מזומנים",
        ))
        db.add(ChatMessage(
            organization_id=org_b, user_id=1, session_id="s1", role="user",
            content="תזרים מזומנים בארגון אחר לגמרי",
        ))
        db.commit()

        result = asyncio.run(TOOLS["search_history"].fn(db, org_a, query="תזרים", _user_id=1))
        assert len(result["results"]) == 1
        assert "דיברנו" in result["results"][0]["excerpt"]
    finally:
        db.close()


def test_search_history_tool_excludes_unconfirmed_pending_actions(fresh_org):
    """Same rule as ai_chat_service._history: an unconfirmed proposal never
    happened. A search must not let Moshko conclude a write occurred just
    because it was proposed — only the executed confirmation message (or a
    genuinely executed/plain message) may surface."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(ChatMessage(
            organization_id=org_id, user_id=1, session_id="s1", role="assistant",
            content="אני מציע לבצע: תיוק הוצאה 42. לאשר?",
            pending_action={"tool": "file_expense", "input": {"expense_id": 42}},
        ))
        db.add(ChatMessage(
            organization_id=org_id, user_id=1, session_id="s1", role="assistant",
            content="בוצע: תיוק הוצאה 42",
        ))
        db.commit()

        result = asyncio.run(TOOLS["search_history"].fn(db, org_id, query="הוצאה 42", _user_id=1))
        excerpts = [r["excerpt"] for r in result["results"]]
        assert "בוצע: תיוק הוצאה 42" in excerpts
        assert not any("מציע לבצע" in e for e in excerpts)
    finally:
        db.close()


def test_search_history_tool_with_no_match_returns_empty_results(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(TOOLS["search_history"].fn(db, org_id, query="משהו שלא נאמר מעולם", _user_id=1))
        assert result["results"] == []
    finally:
        db.close()
