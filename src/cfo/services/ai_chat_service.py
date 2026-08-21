"""AI chat assistant service (Wave 2 Step 9.2/9.3).

The confirmation gate is the whole safety story here: a "write" tool
(issue_document, log_collection_attempt) is NEVER executed as a direct
result of the model calling it — on any turn, not just the first. When the
model requests a write tool, the turn halts and persists a pending_action on
the assistant's message row instead of running it. Only a separate,
explicit confirm_action(message_id) call executes it — and that call
re-reads the tool name/input from the DB row itself (never from client-
supplied data), scoped to the caller's organization, and only once
(ChatMessage.executed guards against re-confirming).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ChatMessage, User
from . import moshko_memory
from .ai_chat_tools import TOOLS, anthropic_tool_schemas, tool_target_system
from .moshko_observability import (
    record_gap_best_effort,
    redact_sensitive_text,
    record_llm_usage_best_effort,
    record_tool_call_best_effort,
)
from .ai_chat_personas import (
    BASE_SYSTEM_PROMPT,
    build_system_prompt,
    resolve_persona,
)
from .policy_service import PolicyService

# Backward-compatible alias — the persona layer (ai_chat_personas.py) now
# owns the prompt strings; re-exported here under the original name because
# existing callers/tests reference ai_chat_service.SYSTEM_PROMPT directly.
SYSTEM_PROMPT = BASE_SYSTEM_PROMPT
logger = logging.getLogger(__name__)

_MAX_TOOL_TURNS = 6

# Most recent messages replayed to the model per turn. Not a "context
# window" figure — it is the point past which older chat turns stop earning
# their input cost, given every factual answer comes from a tool call made
# fresh in the current turn, never from what was said ten turns ago.
_MAX_HISTORY_MESSAGES = 30


class ChatConfirmationError(ValueError):
    """Raised when confirm_action can't proceed (not found / wrong org /
    nothing pending / already executed)."""


class AIChatNotConfiguredError(ValueError):
    """Raised when ANTHROPIC_API_KEY isn't set. Subclasses ValueError so an
    app-level FastAPI handler (see cfo.api) maps it to a clean HTTP 400,
    same pattern as SumitNotConfiguredError — otherwise the raw anthropic
    SDK raises a bare TypeError deep in header-building that leaks as an
    unhandled 500."""


class AIChatUpstreamError(RuntimeError):
    """Raised when a correctly-configured ANTHROPIC_API_KEY still fails at
    the Anthropic API itself (found live in the first real 9.5 test: a
    valid key with no credit balance raises anthropic.BadRequestError deep
    inside messages.create). Mapped to a clean HTTP 503 — same "honest
    upstream failure" pattern as SUMIT's httpx.ConnectError handling —
    instead of leaking the raw SDK exception as an unhandled 500."""


_OFFICE_REFUSAL_TEXT = (
    "אין הרשאה לפעולה זו — כלי משרד זמינים רק במצב מנהל משרד (SUPER_ADMIN)."
)

_ACTION_PENDING = "pending"
_ACTION_EXECUTING = "executing"
_ACTION_EXECUTED = "executed"
_ACTION_CANCELLED = "cancelled"
_ACTION_UNKNOWN = "unknown"

# W1.1 — דפוסי ויתור. שמרני בכוונה: עדיף לפספס ניסוח נדיר מאשר להציף
# את התור בתשובות תקינות שמכילות "לא" כלשהו. מודול-level (לא class attr)
# כדי ש-W1.5 (moshko_regression.py) ישתמש באותו גלאי בדיוק דרך
# is_giveup_answer — לא כתיבה כפולה של הגלאי.
_GIVEUP_MARKERS = (
    "לא הצלחתי",
    "אין לי כלי",
    "אין לי יכולת",
    "איני יכול לבצע",
    "אין לי גישה",
    "לא יכול לבצע",
)


def is_giveup_answer(text: str | None) -> bool:
    """True אם הטקסט הוא תשובת-ויתור של המודל (הגלאי הקיים של W1.1)."""
    if not text:
        return False
    return any(marker in text for marker in _GIVEUP_MARKERS)


class AIChatService:
    def __init__(
        self, db: Session, organization_id: int, user_id: int,
        *, is_super_admin: bool = False, channel: str = "web",
    ):
        self.db = db
        self.organization_id = organization_id
        self.user_id = user_id
        # Re-derived by the caller on EVERY request from the authenticated
        # user's current role (see routes/ai_chat.py) — never persisted,
        # never trusted from a prior turn. This is the single gate for both
        # office-tool schema visibility and office-tool execution below.
        self.is_super_admin = is_super_admin
        self.channel = channel

    def _tool_policy_decision(
        self, tool, tool_input: dict[str, Any], *, exclude_message_id: int | None = None,
    ):
        if tool.office:
            return None
        if not tool.policy_action:
            raise ChatConfirmationError(
                "פעולת הכתיבה חסרה מיפוי הרשאה ולכן נחסמה בבטחה",
            )
        user = self.db.get(User, self.user_id)
        if user is None:
            raise ChatConfirmationError("לא ניתן לאמת את המשתמש המבקש")
        return PolicyService(
            self.db, self.organization_id,
        ).evaluate_tool(
            user=user,
            policy_action=tool.policy_action,
            tool_input=tool_input,
            channel=self.channel,
            exclude_message_id=exclude_message_id,
        )

    @staticmethod
    def _assert_chat_policy(decision) -> None:
        if decision is None:
            return
        if not decision.allowed:
            raise ChatConfirmationError(
                f"מדיניות הארגון אינה מתירה את הפעולה: {decision.reason}",
            )
        if decision.requires_step_up:
            raise ChatConfirmationError(
                "הפעולה דורשת אימות מוגבר שאינו זמין בתוך השיחה",
            )
        if decision.required_approvals > 1:
            raise ChatConfirmationError(
                "הפעולה דורשת יותר ממאשר אחד ויש להעבירה למרכז האישורים",
            )
        if decision.separation_of_duties:
            raise ChatConfirmationError(
                "מדיניות הפרדת התפקידים אינה מאפשרת אישור עצמי בשיחה",
            )

    def _history(self, session_id: str) -> list[ChatMessage]:
        # Scoped to (org, user) — a chat session is a private conversation,
        # not shared team data. Without the user_id check, any authenticated
        # user in the same org could read another user's session just by
        # knowing/guessing its session_id.
        #
        # Capped at the most recent _MAX_HISTORY_MESSAGES. A messaging
        # channel has no "new chat" button: telegram_webhook.py derives one
        # permanent session_id per chat (f"tg-{external_id}"), so an
        # uncapped history means every turn re-sends the entire lifetime of
        # that conversation to the model — input cost and latency growing
        # without bound for as long as the user keeps the bot. The query
        # takes the newest rows and re-sorts ascending so the model still
        # reads them oldest-first.
        rows = (
            self.db.query(ChatMessage)
            .filter(
                ChatMessage.organization_id == self.organization_id,
                ChatMessage.user_id == self.user_id,
                ChatMessage.session_id == session_id,
            )
            .order_by(ChatMessage.id.desc())
            .limit(_MAX_HISTORY_MESSAGES)
            .all()
        )
        return list(reversed(rows))

    def _make_client(self):
        import anthropic
        if not settings.anthropic_api_key:
            raise AIChatNotConfiguredError(
                "עוזר ה-AI לא הוגדר: ANTHROPIC_API_KEY חסר בהגדרות המערכת"
            )
        return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    def _record_usage(self, session_id: str, response: Any) -> None:
        """Extra guard around the best-effort recorder for monkeypatches and
        future implementations: observability is never on the chat's critical
        path."""
        try:
            record_llm_usage_best_effort(
                self.db,
                organization_id=self.organization_id,
                user_id=self.user_id,
                session_id=session_id,
                provider="anthropic",
                model=settings.ai_chat_model,
                usage=getattr(response, "usage", None),
                purpose="chat",
            )
        except Exception:
            logger.exception("LLM usage recorder failed outside its best-effort boundary")

    async def _execute_tool_observed(
        self,
        *,
        tool,
        call_kwargs: dict[str, Any],
        logged_arguments: dict[str, Any],
        session_id: str,
        message_id: int | None,
        propagate: bool,
    ) -> Any:
        started = perf_counter()
        try:
            result = await tool.fn(self.db, self.organization_id, **call_kwargs)
        except Exception as exc:
            elapsed = round((perf_counter() - started) * 1000)
            record_tool_call_best_effort(
                self.db,
                organization_id=self.organization_id,
                user_id=self.user_id,
                session_id=session_id,
                message_id=message_id,
                tool_name=tool.name,
                target_system=tool_target_system(tool.name, arguments=logged_arguments),
                arguments=logged_arguments,
                succeeded=False,
                error=str(exc),
                duration_ms=elapsed,
            )
            # W1.1 — כלי שנפל הוא פער: שורה בתור הניתוח, לא רק רישום.
            record_gap_best_effort(
                self.db,
                organization_id=self.organization_id,
                user_id=self.user_id,
                session_id=session_id,
                message_id=message_id,
                gap_kind="tool_failed",
                tool_name=tool.name,
                error=str(exc),
            )
            if propagate:
                raise
            return {"error": str(exc), "tool": tool.name}

        elapsed = round((perf_counter() - started) * 1000)
        record_tool_call_best_effort(
            self.db,
            organization_id=self.organization_id,
            user_id=self.user_id,
            session_id=session_id,
            message_id=message_id,
            tool_name=tool.name,
            target_system=tool_target_system(
                tool.name,
                arguments=logged_arguments,
                result=result if isinstance(result, dict) else None,
            ),
            arguments=logged_arguments,
            succeeded=True,
            error=None,
            duration_ms=elapsed,
            result=result,
        )
        return result

    def _build_proactive_flags(self) -> str:
        """W-proactive (20/08/2026) — הדגלים האדומים שמושקו פותח בהם שיחה.

        הדוגמה של הבעלים: "למה מושקו לא אומר לי שאין הכנסות ממרץ ושהתזרים
        שלילי?" — הבלוק הזה נבנה בתחילת session מהנתונים המקומיים בלבד
        (אפס קריאות API) ומוזרק ל-system prompt עם הוראה לפתוח בו ולשאול.
        honest-null: אין דגלים ⇒ מחרוזת ריקה, מושקו לא ממציא בעיות.
        best-effort: כל כשל כאן לעולם לא מפיל את השיחה.
        """
        try:
            from datetime import date as date_type

            from ..models import CfoInsight

            lines: list[str] = []
            listed_types: set[str] = set()
            insights = (
                self.db.query(CfoInsight)
                .filter(
                    CfoInsight.organization_id == self.organization_id,
                    CfoInsight.status == "active",
                    CfoInsight.severity.in_(("high", "critical")),
                )
                .order_by(CfoInsight.created_at.desc())
                .limit(5)
                .all()
            )
            for row in insights:
                listed_types.add(row.insight_type)
                lines.append(f"- [{row.severity}] {row.title}")

            # דממת הכנסות — נבדקת חיה גם אם מחזור הבוקר לא רץ.
            if "revenue_silence" not in listed_types:
                from . import revenue_watch

                silence = revenue_watch.scan_and_alert(
                    self.db, self.organization_id, today=date_type.today(),
                )
                if silence.get("status") == "silence":
                    lines.append(
                        f"- [{silence['severity']}] אין מסמכי הכנסה כבר "
                        f"{silence['days_silent']} ימים "
                        f"(האחרון: {silence['last_revenue_date']})"
                    )

            # תזרים מצטבר שלילי בשלושת השבועות הקרובים.
            try:
                from .dashboard_service import DashboardService

                projection = DashboardService(
                    self.db, self.organization_id,
                ).get_cashflow_projection(weeks=3)
                negative = [
                    w for w in projection
                    if (w.get("cumulative_balance") or 0) < 0
                ]
                if negative:
                    first = negative[0]
                    lines.append(
                        f"- [high] תזרים מצטבר שלילי צפוי החל משבוע "
                        f"{first.get('week')} ({first.get('cumulative_balance'):,.0f} ש\"ח)"
                    )
            except Exception:
                pass

            if not lines:
                return ""
            return (
                "## דגלים אדומים כרגע (מהנתונים בפועל)\n"
                + "\n".join(lines)
                + "\n\nפתח את תשובתך הראשונה בהצפת הדגלים האלה בקצרה, "
                  "ושאל את המשתמש שאלה ממוקדת על החמור שבהם. אל תמציא "
                  "דגלים שאינם ברשימה."
            )
        except Exception:
            return ""

    def _capture_gap_if_giveup(
        self, *, session_id: str, message_id: int | None,
        question: str, final_text: str,
    ) -> None:
        """תשובת ויתור של המודל היא פער-יכולת — נלכדת כשורה בתור הניתוח.

        זו הדוגמה של הבעלים (20/08): "אני מבקש דוח כספי לשנת X והוא לא
        מצליח — אני רוצה את זה בשורה בתוך ניהול השיחות". best-effort.
        """
        if not is_giveup_answer(final_text):
            return
        record_gap_best_effort(
            self.db,
            organization_id=self.organization_id,
            user_id=self.user_id,
            session_id=session_id,
            message_id=message_id,
            gap_kind="model_gave_up",
            question=question,
            answer=final_text,
        )

    async def send_message(
        self, session_id: str, text: str, persona: Optional[str] = None,
    ) -> dict[str, Any]:
        # Unconfirmed proposals are excluded from context — from the
        # model's point of view, a pending (not-yet-executed) action never
        # happened, so it must not be treated as something already done.
        history = [m for m in self._history(session_id) if not m.pending_action]

        user_msg = ChatMessage(
            organization_id=self.organization_id, user_id=self.user_id,
            session_id=session_id, role="user", content=text,
        )
        self.db.add(user_msg)
        self.db.flush()

        messages: list[dict[str, Any]] = [
            {"role": m.role, "content": m.content} for m in history
        ]
        messages.append({"role": "user", "content": text})

        client = self._make_client()
        # Fail closed: office tools are added to the schema ONLY for a
        # confirmed SUPER_ADMIN — a regular user's request never even
        # mentions these tools exist (see anthropic_tool_schemas). The
        # persona (resolved below) is a prompt/tone axis only — it never
        # widens this gate; every persona gets the exact same tool_schemas.
        tool_schemas = anthropic_tool_schemas(include_office=self.is_super_admin)
        persona_obj = resolve_persona(persona)
        # Frozen injection, not retrieval (Hermes-style — see moshko_memory.py):
        # loaded fresh once per turn, never mutated mid-turn, so a write via
        # the `memory` tool this turn only shows up starting the NEXT turn.
        memory_block = moshko_memory.render_memory_block(
            self.db, self.organization_id, self.user_id,
        )
        system_prompt = build_system_prompt(
            persona_obj, include_office=self.is_super_admin,
            memory_block=memory_block,
        )
        # W-proactive: בתחילת session מושקו פותח בדגלים האדומים של הארגון
        # ושואל עליהם — לא מחכה שישאלו אותו (הכל מקומי, אפס API).
        if not history:
            proactive_block = self._build_proactive_flags()
            if proactive_block:
                system_prompt = f"{system_prompt}\n\n{proactive_block}"

        pending_action: Optional[dict[str, Any]] = None
        final_text = ""

        for _ in range(_MAX_TOOL_TURNS):
            import anthropic
            try:
                response = await client.messages.create(
                    model=settings.ai_chat_model,
                    max_tokens=1024,
                    system=system_prompt,
                    messages=messages,
                    tools=tool_schemas,
                )
            except anthropic.APIError as exc:
                raise AIChatUpstreamError(
                    f"עוזר ה-AI לא זמין כרגע (שגיאת Anthropic API): {exc}"
                ) from exc

            self._record_usage(session_id, response)

            if response.stop_reason != "tool_use":
                final_text = "".join(
                    b.text for b in response.content if b.type == "text"
                )
                break

            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            assistant_text = "".join(
                b.text for b in response.content if b.type == "text"
            )
            assistant_content = [
                {"type": "text", "text": b.text} if b.type == "text"
                else {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
                for b in response.content
            ]
            messages.append({"role": "assistant", "content": assistant_content})

            write_call = next(
                (b for b in tool_use_blocks if TOOLS[b.name].category == "write"), None
            )
            if write_call is not None and TOOLS[write_call.name].office and not self.is_super_admin:
                # Defense in depth: this tool must never have been offered to
                # a non-super-admin in the first place (see tool_schemas
                # above) — if it's requested anyway, refuse outright without
                # ever proposing (let alone executing) it.
                final_text = _OFFICE_REFUSAL_TEXT
                break
            if write_call is not None:
                # Halt here — never execute a write tool from the model's
                # own call. Persist what it proposed; only an explicit,
                # separate confirm_action() can run it.
                tool = TOOLS[write_call.name]
                try:
                    decision = self._tool_policy_decision(tool, dict(write_call.input))
                    self._assert_chat_policy(decision)
                except ChatConfirmationError as exc:
                    final_text = str(exc)
                    break
                policy_context = (
                    PolicyService(self.db, self.organization_id).tool_context(
                        policy_action=tool.policy_action,
                        tool_input=dict(write_call.input),
                    ) if decision is not None else {}
                )
                pending_action = {
                    "tool": write_call.name,
                    "input": write_call.input,
                    "description": tool.description,
                    "policy_action": tool.policy_action,
                    "policy_amount": (
                        str(policy_context.get("amount"))
                        if policy_context.get("amount") is not None else None
                    ),
                    "policy_decision": decision.to_audit() if decision is not None else None,
                }
                final_text = assistant_text or (
                    f"אני מציע לבצע: {TOOLS[write_call.name].description}. לאשר?"
                )
                break

            tool_results = []
            for block in tool_use_blocks:
                tool = TOOLS[block.name]
                if tool.office and not self.is_super_admin:
                    # Same defense-in-depth as the write-tool check above,
                    # for read office tools: never execute, never leak data,
                    # even if somehow requested by name.
                    result = {"error": _OFFICE_REFUSAL_TEXT}
                    record_tool_call_best_effort(
                        self.db,
                        organization_id=self.organization_id,
                        user_id=self.user_id,
                        session_id=session_id,
                        message_id=user_msg.id,
                        tool_name=tool.name,
                        target_system=tool_target_system(tool.name, arguments=dict(block.input)),
                        arguments=dict(block.input),
                        succeeded=False,
                        error=_OFFICE_REFUSAL_TEXT,
                        duration_ms=0,
                    )
                else:
                    # Merge into a dict first (not **a, **b in the call) so a
                    # duplicate key can never raise "multiple values for
                    # argument" — if a tool_use.input somehow carried its own
                    # _user_id, the real caller identity below always wins,
                    # it's never spoofable from model output.
                    call_kwargs = dict(block.input)
                    if tool.needs_user:
                        call_kwargs["_user_id"] = self.user_id
                    result = await self._execute_tool_observed(
                        tool=tool,
                        call_kwargs=call_kwargs,
                        logged_arguments=dict(block.input),
                        session_id=session_id,
                        message_id=user_msg.id,
                        propagate=False,
                    )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                })
            messages.append({"role": "user", "content": tool_results})
        else:
            final_text = "לא הצלחתי להשלים את הבקשה בתוך מספר הצעדים המותר."

        assistant_msg = ChatMessage(
            organization_id=self.organization_id, user_id=self.user_id,
            session_id=session_id, role="assistant", content=final_text,
            pending_action=pending_action,
            action_status=_ACTION_PENDING if pending_action else None,
        )
        self.db.add(assistant_msg)
        self.db.flush()
        # W1.1: תשובת ויתור נלכדת בתור הפערים — פעולה מוצעת אינה ויתור.
        if pending_action is None:
            self._capture_gap_if_giveup(
                session_id=session_id, message_id=assistant_msg.id,
                question=text, final_text=final_text,
            )
        self.db.commit()
        self.db.refresh(assistant_msg)

        return {
            "message_id": assistant_msg.id,
            "reply": final_text,
            "pending_action": pending_action,
        }

    async def confirm_action(self, message_id: int) -> dict[str, Any]:
        # Scoped to (org, user) — message_id is a small sequential integer,
        # trivially guessable, so org-scoping alone isn't enough: without
        # the user_id check here, any other user in the same org could
        # confirm (and execute) a write that someone else's chat proposed.
        msg = self.db.query(ChatMessage).filter(
            ChatMessage.id == message_id,
            ChatMessage.organization_id == self.organization_id,
            ChatMessage.user_id == self.user_id,
        ).first()
        if msg is None:
            raise ChatConfirmationError(f"הודעה {message_id} לא נמצאה")
        if not msg.pending_action:
            raise ChatConfirmationError("אין פעולה ממתינה לאישור בהודעה זו")
        if msg.executed or msg.action_status == _ACTION_EXECUTED:
            raise ChatConfirmationError("הפעולה כבר בוצעה")

        if msg.action_status == _ACTION_CANCELLED:
            raise ChatConfirmationError("הפעולה בוטלה ואינה ניתנת לביצוע")
        if msg.action_status == _ACTION_EXECUTING:
            raise ChatConfirmationError("הפעולה כבר בתהליך ביצוע; לא תופעל שוב")
        if msg.action_status == _ACTION_UNKNOWN:
            raise ChatConfirmationError(
                "תוצאת הפעולה אינה ידועה ודורשת אימות ידני לפני כל ניסיון נוסף"
            )
        if msg.action_status not in (None, _ACTION_PENDING):
            raise ChatConfirmationError("מצב הפעולה אינו מאפשר ביצוע")

        tool_name = msg.pending_action.get("tool")
        tool = TOOLS.get(tool_name)
        if tool is None:
            raise ChatConfirmationError("הפעולה הממתינה אינה מוכרת עוד למערכת")
        if tool.office and not self.is_super_admin:
            # Defense in depth: role is re-derived on THIS request, not
            # trusted from whatever it was when the action was proposed. A
            # demoted/former-super-admin user (or any other caller) must not
            # be able to execute an office write via a stale pending_action.
            raise ChatConfirmationError(_OFFICE_REFUSAL_TEXT)
        decision = self._tool_policy_decision(
            tool,
            dict(msg.pending_action.get("input") or {}),
            exclude_message_id=msg.id,
        )
        self._assert_chat_policy(decision)

        # Compare-and-set claim committed BEFORE invoking the tool.  This is
        # the exactly-once boundary inside Rezef: only one worker can move a
        # proposal from pending/legacy-NULL to executing.  A process crash or
        # ambiguous provider response leaves it executing/unknown, which is
        # deliberately not replayable without manual verification.
        claimed_at = datetime.now(timezone.utc)
        claimed = (
            self.db.query(ChatMessage)
            .filter(
                ChatMessage.id == message_id,
                ChatMessage.organization_id == self.organization_id,
                ChatMessage.user_id == self.user_id,
                ChatMessage.pending_action.is_not(None),
                or_(ChatMessage.executed.is_(False), ChatMessage.executed.is_(None)),
                or_(
                    ChatMessage.action_status.is_(None),
                    ChatMessage.action_status == _ACTION_PENDING,
                ),
            )
            .update(
                {
                    ChatMessage.action_status: _ACTION_EXECUTING,
                    ChatMessage.action_claimed_at: claimed_at,
                    ChatMessage.action_error: None,
                },
                synchronize_session=False,
            )
        )
        if claimed != 1:
            self.db.rollback()
            raise ChatConfirmationError("הפעולה כבר נתפסה, בוצעה או בוטלה")
        self.db.commit()
        self.db.expire_all()
        msg = self.db.query(ChatMessage).filter(
            ChatMessage.id == message_id,
            ChatMessage.organization_id == self.organization_id,
            ChatMessage.user_id == self.user_id,
        ).one()

        try:
            call_kwargs = dict(msg.pending_action["input"])
            if tool.needs_user:
                call_kwargs["_user_id"] = self.user_id
                call_kwargs["_channel"] = self.channel
            result = await self._execute_tool_observed(
                tool=tool,
                call_kwargs=call_kwargs,
                logged_arguments=dict(msg.pending_action["input"]),
                session_id=msg.session_id,
                message_id=msg.id,
                propagate=True,
            )
        except ValueError as exc:
            # Never fake success: a business-validation failure (e.g.
            # register_office_client with no SUMIT key configured) must
            # surface as an honest refusal — msg.executed stays False and no
            # "בוצע" confirmation is posted, exactly as if nothing happened.
            # ValueError is the service layer's precondition/business-rule
            # failure contract; rollback any partial local work and return the
            # proposal to pending so the operator can correct configuration.
            self.db.rollback()
            self._set_action_state(
                message_id,
                status=_ACTION_PENDING,
                error=str(exc),
                completed_at=None,
                clear_claim=True,
            )
            raise ChatConfirmationError(str(exc)) from exc
        except Exception as exc:
            # A transport/process error may occur after an external provider
            # accepted the write.  Never retry automatically: record UNKNOWN
            # (with redacted diagnostics) and require reconciliation.
            self.db.rollback()
            self._set_action_state(
                message_id,
                status=_ACTION_UNKNOWN,
                error=str(exc),
                completed_at=datetime.now(timezone.utc),
            )
            raise ChatConfirmationError(
                "תוצאת הפעולה אינה ידועה; נדרש אימות ידני לפני ניסיון נוסף"
            ) from exc

        msg.executed = True
        msg.action_status = _ACTION_EXECUTED
        msg.action_completed_at = datetime.now(timezone.utc)
        msg.action_error = None

        confirmation_msg = ChatMessage(
            organization_id=self.organization_id, user_id=self.user_id,
            session_id=msg.session_id, role="assistant",
            content=f"בוצע: {tool.description}",
        )
        self.db.add(confirmation_msg)
        try:
            self.db.commit()
        except Exception as exc:
            # The provider may already have completed the write.  If local
            # finalization fails, preserve the earlier durable claim and lock
            # the action UNKNOWN instead of creating a duplicate on retry.
            self.db.rollback()
            self._set_action_state(
                message_id,
                status=_ACTION_UNKNOWN,
                error=str(exc),
                completed_at=datetime.now(timezone.utc),
            )
            raise ChatConfirmationError(
                "הפעולה ייתכן שבוצעה, אך שמירת האישור נכשלה; נדרש אימות ידני"
            ) from exc
        self.db.refresh(confirmation_msg)

        return {"result": result, "message_id": confirmation_msg.id}

    def _set_action_state(
        self,
        message_id: int,
        *,
        status: str,
        error: str | None,
        completed_at: datetime | None,
        clear_claim: bool = False,
    ) -> None:
        """Persist a post-claim terminal/retry state after rolling back any
        partial tool transaction.  This update is always tenant+user scoped."""
        values: dict[Any, Any] = {
            ChatMessage.action_status: status,
            ChatMessage.action_error: redact_sensitive_text(error)[:1000] if error else None,
            ChatMessage.action_completed_at: completed_at,
        }
        if clear_claim:
            values[ChatMessage.action_claimed_at] = None
        self.db.query(ChatMessage).filter(
            ChatMessage.id == message_id,
            ChatMessage.organization_id == self.organization_id,
            ChatMessage.user_id == self.user_id,
            ChatMessage.action_status == _ACTION_EXECUTING,
        ).update(values, synchronize_session=False)
        self.db.commit()
        self.db.expire_all()

    def cancel_action(self, message_id: int) -> dict[str, Any]:
        """Atomically cancel a proposal owned by the current user.

        Only pending (including legacy NULL-status) actions can be cancelled;
        executing/unknown/executed actions remain locked to prevent a UI tap
        from misrepresenting an external side effect as cancelled.
        """
        completed_at = datetime.now(timezone.utc)
        cancelled = (
            self.db.query(ChatMessage)
            .filter(
                ChatMessage.id == message_id,
                ChatMessage.organization_id == self.organization_id,
                ChatMessage.user_id == self.user_id,
                ChatMessage.pending_action.is_not(None),
                or_(ChatMessage.executed.is_(False), ChatMessage.executed.is_(None)),
                or_(
                    ChatMessage.action_status.is_(None),
                    ChatMessage.action_status == _ACTION_PENDING,
                ),
            )
            .update(
                {
                    ChatMessage.action_status: _ACTION_CANCELLED,
                    ChatMessage.action_completed_at: completed_at,
                    ChatMessage.action_error: None,
                },
                synchronize_session=False,
            )
        )
        if cancelled != 1:
            self.db.rollback()
            msg = self.db.query(ChatMessage).filter(
                ChatMessage.id == message_id,
                ChatMessage.organization_id == self.organization_id,
                ChatMessage.user_id == self.user_id,
            ).first()
            if msg is None:
                raise ChatConfirmationError(f"הודעה {message_id} לא נמצאה")
            if not msg.pending_action:
                raise ChatConfirmationError("אין פעולה ממתינה לביטול בהודעה זו")
            if msg.action_status == _ACTION_CANCELLED:
                raise ChatConfirmationError("הפעולה כבר בוטלה")
            if msg.executed or msg.action_status == _ACTION_EXECUTED:
                raise ChatConfirmationError("הפעולה כבר בוצעה ואינה ניתנת לביטול")
            raise ChatConfirmationError("הפעולה כבר בתהליך או דורשת אימות ידני")
        self.db.commit()
        return {"message_id": message_id, "status": _ACTION_CANCELLED}
