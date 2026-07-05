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
    # Office-manager tier (Wave — office bot). True only for the 5 tools that
    # give a SUPER_ADMIN cross-client, accounting-office-manager capability
    # (roster, rollup, per-client overview, sync, register). ai_chat_service
    # uses this flag as the single gate for BOTH schema visibility (a non-
    # super-admin never sees these tool definitions at all) AND execution
    # (defense in depth — refused even if somehow requested by name).
    office: bool = False


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


async def _search_contacts(db, org_id: int, *, query: str, contact_type: str | None = None, **_kwargs) -> dict:
    from .contact_service import search_contacts
    from ..models import ContactType
    contacts = search_contacts(
        db, org_id, query, contact_type=ContactType(contact_type) if contact_type else None,
    )
    return {"contacts": [
        {
            "id": c.id, "name": c.name,
            "contact_type": getattr(c.contact_type, "value", c.contact_type),
            "email": c.email, "phone": c.phone, "external_id": c.external_id,
        }
        for c in contacts
    ]}


async def _get_ledger_card(db, org_id: int, *, contact_id: int, **_kwargs) -> dict:
    from .ledger_service import contact_card
    card = contact_card(db, org_id, contact_id)
    return card if card is not None else {"error": "איש קשר לא נמצא"}


async def _get_vat_position(db, org_id: int, **_kwargs) -> dict:
    from .financial_synthesis import compute_vat_position
    return compute_vat_position(db, org_id)


async def _get_cashflow(db, org_id: int, weeks: int = 12, **_kwargs) -> dict:
    from .dashboard_service import DashboardService
    return {"projection": DashboardService(db, org_id).get_cashflow_projection(weeks=weeks)}


async def _list_invoices(db, org_id: int, status: str | None = None, limit: int = 20, **_kwargs) -> dict:
    from .document_issuance_service import DocumentIssuanceService
    service = DocumentIssuanceService(db, org_id)
    return {"documents": service.list_documents(status=status, limit=limit)}


async def _get_engine_status(db, org_id: int, **_kwargs) -> dict:
    from . import engine_service
    return engine_service.status(db, org_id)


async def _create_payment_link(db, org_id: int, *, invoice_id: int, **_kwargs) -> dict:
    from .document_issuance_service import DocumentIssuanceService
    service = DocumentIssuanceService(db, org_id)
    return await service.create_payment_link(invoice_id)


# ------------------------------------------------------------------------ #
# Office-manager tools (SUPER_ADMIN tier). `org_id` here means the CALLER's
# own organization acting as the office — same as every other tool, injected
# by ai_chat_service, never model-supplied. Where a tool needs to reach a
# DIFFERENT organization (a specific client file), that target is an
# explicit, differently-named input (`client_org_id` / `client_id`) — never
# `org_id` itself, since block.input is spread as **kwargs onto a call that
# already binds org_id positionally; a same-named key would raise
# "got multiple values for argument 'org_id'" instead of silently doing
# anything, but using a distinct name avoids relying on that crash as a
# safety net.
# ------------------------------------------------------------------------ #
async def _list_office_clients(db, org_id: int, **_kwargs) -> dict:
    from . import office_service
    roster = office_service.list_clients(db, org_id)
    rollup = office_service.office_rollup(db, org_id)
    by_company = {c["company_id"]: c for c in rollup["clients"]}
    for c in roster:
        synth = by_company.get(c["company_id"], {})
        c["required_actions"] = synth.get("required_actions", 0)
        c["net_vat"] = synth.get("net_vat", 0)
        c["reconciliation"] = synth.get("reconciliation", {})
    return {"totals": rollup["totals"], "clients": roster}


async def _get_office_rollup(db, org_id: int, **_kwargs) -> dict:
    from . import office_service
    return office_service.office_rollup(db, org_id)


async def _get_client_overview(db, org_id: int, *, client_org_id: int, **_kwargs) -> dict:
    from . import engine_service, financial_synthesis
    return {
        "organization_id": client_org_id,
        "engine_status": engine_service.status(db, client_org_id),
        "synthesis": financial_synthesis.synthesize_organization(db, client_org_id),
    }


async def _run_client_sync(
    db, org_id: int, *, client_id: int, entity_types: str | None = None, **_kwargs,
) -> dict:
    from . import office_service
    return await office_service.run_client_sync(
        db, org_id, client_id=client_id, entity_types=entity_types,
    )


async def _register_office_client(
    db, org_id: int, *, name: str, company_id: str, api_key: str | None = None,
    business_type: str | None = None, tax_id: str | None = None,
    open_finance: dict | None = None, **_kwargs,
) -> dict:
    from . import office_service
    return office_service.register_client(
        db, org_id,
        name=name,
        sumit_company_id=company_id,
        sumit_api_key=api_key,
        business_type=business_type,
        tax_id=tax_id,
        open_finance=open_finance,
    )


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
    "search_contacts": ChatTool(
        name="search_contacts",
        description="חיפוש אנשי קשר (לקוחות/ספקים) לפי חלק משם.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "חלק משם איש הקשר"},
                "contact_type": {"type": "string", "enum": ["customer", "vendor"]},
            },
            "required": ["query"],
        },
        category="read",
        fn=_search_contacts,
    ),
    "get_ledger_card": ChatTool(
        name="get_ledger_card",
        description="כרטסת של לקוח/ספק ספציפי — חשבוניות/חשבונות ותשלומים כרונולוגית עם יתרה רצה.",
        input_schema={
            "type": "object",
            "properties": {"contact_id": {"type": "integer", "description": "מזהה איש הקשר"}},
            "required": ["contact_id"],
        },
        category="read",
        fn=_get_ledger_card,
    ),
    "get_vat_position": ChatTool(
        name="get_vat_position",
        description="מצב מע\"מ נוכחי (עסקאות/תשומות/נטו לתשלום או להחזר), מבוסס על המסמכים בפועל.",
        input_schema={"type": "object", "properties": {}},
        category="read",
        fn=_get_vat_position,
    ),
    "get_cashflow": ChatTool(
        name="get_cashflow",
        description="תחזית תזרים מזומנים שבועית קדימה.",
        input_schema={
            "type": "object",
            "properties": {"weeks": {"type": "integer", "description": "מספר שבועות", "default": 12}},
        },
        category="read",
        fn=_get_cashflow,
    ),
    "list_invoices": ChatTool(
        name="list_invoices",
        description="רשימת מסמכים שהופקו (חשבוניות וכו'), אופציונלית מסוננת לפי סטטוס.",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
        category="read",
        fn=_list_invoices,
    ),
    "get_engine_status": ChatTool(
        name="get_engine_status",
        description="סטטוס מנוע ההנהלת-חשבונות הנגזר (כמות תנועות, האם מאוזן).",
        input_schema={"type": "object", "properties": {}},
        category="read",
        fn=_get_engine_status,
    ),
    "create_payment_link": ChatTool(
        name="create_payment_link",
        description=(
            "יצירת קישור תשלום מאובטח (עמוד תשלום מאוחסן ב-SUMIT) עבור היתרה הפתוחה "
            "בחשבונית. פעולת כתיבה אמיתית מול SUMIT — דורשת אישור מפורש של המשתמש לפני ביצוע."
        ),
        input_schema={
            "type": "object",
            "properties": {"invoice_id": {"type": "integer", "description": "מזהה החשבונית"}},
            "required": ["invoice_id"],
        },
        category="write",
        fn=_create_payment_link,
    ),
    "list_office_clients": ChatTool(
        name="list_office_clients",
        description=(
            "רשימת כל תיקי הלקוחות של המשרד — סטטוס סנכרון וחיבור SUMIT לכל תיק. "
            "כלי משרד — זמין רק במצב מנהל משרד (SUPER_ADMIN)."
        ),
        input_schema={"type": "object", "properties": {}},
        category="read",
        fn=_list_office_clients,
        office=True,
    ),
    "get_office_rollup": ChatTool(
        name="get_office_rollup",
        description=(
            "רולאפ פיננסי רוחבי על כל תיקי הלקוחות של המשרד — סה\"כ מע\"מ, פעולות "
            "נדרשות והתאמות, לפי לקוח וסה\"כ. כלי משרד — זמין רק במצב מנהל משרד."
        ),
        input_schema={"type": "object", "properties": {}},
        category="read",
        fn=_get_office_rollup,
        office=True,
    ),
    "get_client_overview": ChatTool(
        name="get_client_overview",
        description=(
            "סקירת מצב של תיק לקוח ספציפי (כל ארגון במערכת) — סטטוס מנוע ההנה\"ח "
            "ומספרים מרכזיים (מע\"מ, התאמות נדרשות). כלי משרד — זמין רק במצב מנהל משרד."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "client_org_id": {"type": "integer", "description": "מזהה הארגון (Organization ID) של תיק הלקוח"},
            },
            "required": ["client_org_id"],
        },
        category="read",
        fn=_get_client_overview,
        office=True,
    ),
    "run_client_sync": ChatTool(
        name="run_client_sync",
        description=(
            "הרצת סנכרון על-פי דרישה לתיק לקוח ספציפי של המשרד. פעולת כתיבה אמיתית "
            "(מושכת נתונים חדשים) — דורשת אישור מפורש. כלי משרד — זמין רק במצב מנהל משרד."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "client_id": {"type": "integer", "description": "מזהה תיק הלקוח ברשימת המשרד (roster id)"},
                "entity_types": {"type": "string", "description": "רשימת סוגי ישויות מופרדת בפסיקים, ריק=הכול"},
            },
            "required": ["client_id"],
        },
        category="write",
        fn=_run_client_sync,
        office=True,
    ),
    "register_office_client": ChatTool(
        name="register_office_client",
        description=(
            "רישום תיק לקוח חדש למשרד (ארגון-שוכר נפרד משלו עם אימות SUMIT משלו). "
            "פעולת כתיבה — דורשת אישור מפורש. אם אין מפתח SUMIT (לא של המשרד ולא "
            "ספציפי) הפעולה נכשלת בכנות — לעולם לא 'מצליחה' בלי חיבור אמיתי. "
            "כלי משרד — זמין רק במצב מנהל משרד."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "company_id": {"type": "string", "description": "מזהה חברה ב-SUMIT (תיק)"},
                "api_key": {"type": "string", "description": "מפתח SUMIT ספציפי ללקוח זה; אופציונלי אם למשרד יש מפתח ברירת מחדל"},
                "business_type": {"type": "string"},
                "tax_id": {"type": "string"},
            },
            "required": ["name", "company_id"],
        },
        category="write",
        fn=_register_office_client,
        office=True,
    ),
}


def anthropic_tool_schemas(*, include_office: bool = False) -> list[dict[str, Any]]:
    """Tool schemas in the shape the Anthropic Messages API expects.

    Fails closed: office tools are excluded unless include_office=True is
    passed explicitly. ai_chat_service passes True only when the requesting
    user's role is SUPER_ADMIN (see ai_chat_service.py) — a regular user's
    tool schema never even mentions these tools exist.
    """
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in TOOLS.values()
        if include_office or not t.office
    ]
