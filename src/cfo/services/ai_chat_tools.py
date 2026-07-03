"""Tool layer for the AI chat assistant (Wave 2 Step 9.1).

Thin wrappers over existing, already org-scoped services — this module adds
no new business logic. `org_id` is injected by the caller from the
authenticated request context; it is NEVER a parameter the model supplies,
so a tool call can't be used to reach across organizations.

Tools are split into "read" (safe — the chat loop executes these
automatically) and "write" (side-effecting — the chat loop must never
auto-execute these; see ai_chat_service.py for the confirmation gate that
enforces this)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass(frozen=True)
class ChatTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    category: str  # "read" | "write"
    fn: Callable[..., Awaitable[dict[str, Any]]]


async def _get_ar_aging(db, org_id: int, **_kwargs) -> dict:
    from .dashboard_service import DashboardService
    return DashboardService(db, org_id).get_ar_aging()


async def _get_ap_bills(db, org_id: int, days_ahead: int = 30, **_kwargs) -> dict:
    from .dashboard_service import DashboardService
    return {"bills": DashboardService(db, org_id).get_ap_bills(days_ahead=days_ahead)}


async def _get_pnl(db, org_id: int, months: int = 6, **_kwargs) -> dict:
    from .dashboard_service import DashboardService
    return {"months": DashboardService(db, org_id).get_pnl(months=months)}


async def _get_collection_cases(db, org_id: int, status: str | None = None, **_kwargs) -> dict:
    from . import collection_case_service as svc
    cases = svc.list_cases(db, org_id, status=status)
    return {"cases": [svc.case_to_dict(c) for c in cases]}


async def _issue_document(
    db, org_id: int, *, document_type: str, customer_id: str, customer_name: str,
    items: list[dict], send_to_sumit: bool = True, original_invoice_id: int | None = None,
    **_kwargs,
) -> dict:
    from .document_issuance_service import DocumentIssuanceService
    service = DocumentIssuanceService(db, org_id)
    return await service.create_document(
        document_type=document_type,
        customer_id=customer_id,
        customer_name=customer_name,
        items=items,
        send_to_sumit=send_to_sumit,
        original_invoice_id=original_invoice_id,
    )


async def _log_collection_attempt(
    db, org_id: int, *, case_id: int, channel: str, outcome: str,
    notes: str = "", promise_date: str | None = None, **_kwargs,
) -> dict:
    from datetime import date as date_type
    from . import collection_case_service as svc
    case = svc.log_attempt(
        db, org_id, case_id, channel=channel, outcome=outcome, notes=notes,
        promise_date=date_type.fromisoformat(promise_date) if promise_date else None,
    )
    return svc.case_to_dict(case)


TOOLS: dict[str, ChatTool] = {
    "get_ar_aging": ChatTool(
        name="get_ar_aging",
        description="קבלת דוח גיול חובות לקוחות (aging) — יתרות פתוחות לפי טווחי איחור.",
        input_schema={"type": "object", "properties": {}},
        category="read",
        fn=_get_ar_aging,
    ),
    "get_ap_bills": ChatTool(
        name="get_ap_bills",
        description="קבלת רשימת חשבוניות ספקים לתשלום בטווח הימים הקרוב.",
        input_schema={
            "type": "object",
            "properties": {"days_ahead": {"type": "integer", "description": "טווח ימים קדימה", "default": 30}},
        },
        category="read",
        fn=_get_ap_bills,
    ),
    "get_pnl": ChatTool(
        name="get_pnl",
        description="קבלת דוח רווח והפסד חודשי לטווח החודשים האחרונים.",
        input_schema={
            "type": "object",
            "properties": {"months": {"type": "integer", "description": "מספר חודשים", "default": 6}},
        },
        category="read",
        fn=_get_pnl,
    ),
    "get_collection_cases": ChatTool(
        name="get_collection_cases",
        description="קבלת רשימת תיקי גבייה ידניים, אופציונלית מסוננת לפי סטטוס.",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["open", "promised", "paid", "escalated"]},
            },
        },
        category="read",
        fn=_get_collection_cases,
    ),
    "issue_document": ChatTool(
        name="issue_document",
        description=(
            "הפקת מסמך חדש (חשבונית/קבלה/הצעת מחיר/זיכוי וכו') עבור לקוח. "
            "פעולת כתיבה אמיתית מול SUMIT — דורשת אישור מפורש של המשתמש לפני ביצוע."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "document_type": {"type": "string"},
                "customer_id": {"type": "string"},
                "customer_name": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit_price": {"type": "number"},
                            "vat_rate": {"type": "number"},
                        },
                        "required": ["description", "unit_price"],
                    },
                },
                "original_invoice_id": {"type": "integer", "description": "למסמכי זיכוי בלבד"},
            },
            "required": ["document_type", "customer_id", "customer_name", "items"],
        },
        category="write",
        fn=_issue_document,
    ),
    "log_collection_attempt": ChatTool(
        name="log_collection_attempt",
        description=(
            "רישום ניסיון גבייה (שיחה/מייל) על תיק גבייה קיים, כולל התוצאה. "
            "פעולת כתיבה — דורשת אישור מפורש של המשתמש לפני ביצוע."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "case_id": {"type": "integer"},
                "channel": {"type": "string", "enum": ["phone", "email", "sms"]},
                "outcome": {"type": "string", "enum": ["promised", "paid", "escalate", "no_answer", "refused"]},
                "notes": {"type": "string"},
                "promise_date": {"type": "string", "description": "ISO date, רק אם outcome=promised"},
            },
            "required": ["case_id", "channel", "outcome"],
        },
        category="write",
        fn=_log_collection_attempt,
    ),
}


def anthropic_tool_schemas() -> list[dict[str, Any]]:
    """Tool schemas in the shape the Anthropic Messages API expects."""
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in TOOLS.values()
    ]
