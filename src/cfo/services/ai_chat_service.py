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
    "הנתונים שהכלים מחזירים — אל תמציא מספרים. לפני כל פעולת כתיבה (הפקת "
    "מסמך, רישום ניסיון גבייה) המערכת תבקש אישור מהמשתמש בעצמה; אתה לא "
    "צריך (ואסור לך) להניח שאושר."
)

_MAX_TOOL_TURNS = 6


class ChatConfirmationError(ValueError):
    """Raised when confirm_action can't proceed (not found / wrong org /
    nothing pending / already executed)."""


class AIChatService:
    def __init__(self, db: Session, organization_id: int, user_id: int):
        self.db = db
        self.organization_id = organization_id
        self.user_id = user_id

    def _history(self, session_id: str) -> list[ChatMessage]:
        return (
            self.db.query(ChatMessage)
            .filter(
                ChatMessage.organization_id == self.organization_id,
                ChatMessage.session_id == session_id,
            )
            .order_by(ChatMessage.id.asc())
            .all()
        )

    def _make_client(self):
        import anthropic
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
        tool_schemas = anthropic_tool_schemas()

        pending_action: Optional[dict[str, Any]] = None
        final_text = ""

        for _ in range(_MAX_TOOL_TURNS):
            response = await client.messages.create(
                model=settings.ai_chat_model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=tool_schemas,
            )

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
        msg = self.db.query(ChatMessage).filter(
            ChatMessage.id == message_id,
            ChatMessage.organization_id == self.organization_id,
        ).first()
        if msg is None:
            raise ChatConfirmationError(f"הודעה {message_id} לא נמצאה")
        if not msg.pending_action:
            raise ChatConfirmationError("אין פעולה ממתינה לאישור בהודעה זו")
        if msg.executed:
            raise ChatConfirmationError("הפעולה כבר בוצעה")

        tool = TOOLS[msg.pending_action["tool"]]
        result = await tool.fn(self.db, self.organization_id, **msg.pending_action["input"])
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
