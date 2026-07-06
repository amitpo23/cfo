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
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models import ChatMessage
from .ai_chat_tools import TOOLS, anthropic_tool_schemas

SYSTEM_PROMPT = (
    "אתה עוזר CFO דיגיטלי של רצף. ענה בעברית, תמציתי ומדויק, ורק על סמך "
    "הנתונים שהכלים מחזירים — אל תמציא מספרים. אתה יכול להציג הוצאות (עם "
    "סינון לפי סטטוס/קטגוריה/תאריכים/ספק), לפתוח קטגוריות/כרטיסי הוצאה "
    "מותאמים אישית לפי הנחיית המשתמש (עם מילות מפתח לסיווג אוטומטי), לשנות "
    "סיווג של הוצאה בודדת, להריץ סיווג אוטומטי גורף על הוצאות ממתינות, "
    "ולבדוק מוכנות דיווח מע\"מ (PCN874). לפני כל פעולת כתיבה (הפקת מסמך, "
    "רישום ניסיון גבייה, פתיחת כרטיס הוצאה, שינוי סיווג הוצאה, סיווג גורף "
    "של הוצאות) המערכת תבקש אישור מהמשתמש בעצמה; אתה לא צריך (ואסור לך) "
    "להניח שאושר."
)

# Appended to SYSTEM_PROMPT only when the caller is SUPER_ADMIN (see
# AIChatService.is_super_admin) — i.e. only when the office tools are also
# present in the schema, so the model is never told about a persona whose
# tools it can't actually see.
OFFICE_SYSTEM_PROMPT_ADDENDUM = (
    "אתה פועל כרגע במצב מנהל משרד רואי-חשבון (Office Manager): מעבר לתיק "
    "לקוח בודד, יש לך כלים נוספים לצפייה בכל תיקי הלקוחות של המשרד, סטטוס "
    "הסנכרון וחיבור SUMIT שלהם, רולאפ פיננסי חוצה-לקוחות, וסקירת תיק לקוח "
    "ספציפי. פעולות כתיבה (הרצת סנכרון, רישום תיק לקוח חדש) עדיין דורשות "
    "אישור מפורש של המשתמש לפני ביצוע — בדיוק כמו כל פעולת כתיבה אחרת; "
    "לעולם אל תניח שאושרו."
)

_MAX_TOOL_TURNS = 6


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


class AIChatService:
    def __init__(
        self, db: Session, organization_id: int, user_id: int,
        *, is_super_admin: bool = False,
    ):
        self.db = db
        self.organization_id = organization_id
        self.user_id = user_id
        # Re-derived by the caller on EVERY request from the authenticated
        # user's current role (see routes/ai_chat.py) — never persisted,
        # never trusted from a prior turn. This is the single gate for both
        # office-tool schema visibility and office-tool execution below.
        self.is_super_admin = is_super_admin

    def _history(self, session_id: str) -> list[ChatMessage]:
        # Scoped to (org, user) — a chat session is a private conversation,
        # not shared team data. Without the user_id check, any authenticated
        # user in the same org could read another user's session just by
        # knowing/guessing its session_id.
        return (
            self.db.query(ChatMessage)
            .filter(
                ChatMessage.organization_id == self.organization_id,
                ChatMessage.user_id == self.user_id,
                ChatMessage.session_id == session_id,
            )
            .order_by(ChatMessage.id.asc())
            .all()
        )

    def _make_client(self):
        import anthropic
        if not settings.anthropic_api_key:
            raise AIChatNotConfiguredError(
                "עוזר ה-AI לא הוגדר: ANTHROPIC_API_KEY חסר בהגדרות המערכת"
            )
        return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def send_message(self, session_id: str, text: str) -> dict[str, Any]:
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
        # mentions these tools exist (see anthropic_tool_schemas).
        tool_schemas = anthropic_tool_schemas(include_office=self.is_super_admin)
        system_prompt = (
            f"{SYSTEM_PROMPT}\n\n{OFFICE_SYSTEM_PROMPT_ADDENDUM}"
            if self.is_super_admin else SYSTEM_PROMPT
        )

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
                pending_action = {
                    "tool": write_call.name,
                    "input": write_call.input,
                    "description": TOOLS[write_call.name].description,
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
                else:
                    result = await tool.fn(self.db, self.organization_id, **block.input)
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
        )
        self.db.add(assistant_msg)
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
        if msg.executed:
            raise ChatConfirmationError("הפעולה כבר בוצעה")

        tool = TOOLS[msg.pending_action["tool"]]
        if tool.office and not self.is_super_admin:
            # Defense in depth: role is re-derived on THIS request, not
            # trusted from whatever it was when the action was proposed. A
            # demoted/former-super-admin user (or any other caller) must not
            # be able to execute an office write via a stale pending_action.
            raise ChatConfirmationError(_OFFICE_REFUSAL_TEXT)

        try:
            result = await tool.fn(self.db, self.organization_id, **msg.pending_action["input"])
        except ValueError as exc:
            # Never fake success: a business-validation failure (e.g.
            # register_office_client with no SUMIT key configured) must
            # surface as an honest refusal — msg.executed stays False and no
            # "בוצע" confirmation is posted, exactly as if nothing happened.
            raise ChatConfirmationError(str(exc)) from exc
        msg.executed = True

        confirmation_msg = ChatMessage(
            organization_id=self.organization_id, user_id=self.user_id,
            session_id=msg.session_id, role="assistant",
            content=f"בוצע: {tool.description}",
        )
        self.db.add(confirmation_msg)
        self.db.commit()
        self.db.refresh(confirmation_msg)

        return {"result": result, "message_id": confirmation_msg.id}
