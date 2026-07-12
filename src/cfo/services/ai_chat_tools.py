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


async def _create_bank_payment_request(
    db,
    org_id: int,
    *,
    amount: float,
    description: str,
    creditor_name: str,
    creditor_account_number: str,
    creditor_account_type: str = "bban",
    **_kwargs,
) -> dict:
    from ..api.routes.open_finance import get_open_finance_client

    client = get_open_finance_client(db, org_id)
    try:
        payload = await client.create_payment({
            "paymentInformation": {
                "amount": amount,
                "currency": "ILS",
                "description": description,
                "creditorName": creditor_name,
                "creditorAccountNumber": creditor_account_number,
                "creditorAccountType": creditor_account_type,
            },
        })
    finally:
        await client.close()
    return {
        "payment_id": payload.get("id") or payload.get("paymentId"),
        "pay_url": payload.get("payUrl"),
        "note": "קישור התשלום נוצר; המשלם מאשר את ההעברה מול הבנק שלו דרך הקישור.",
    }


async def _connect_bank_account(
    db,
    org_id: int,
    *,
    psu_id: str | None = None,
    psu_corporate_id: str | None = None,
    provider_ids: list[str] | None = None,
    **_kwargs,
) -> dict:
    from .open_finance_onboarding import start_bank_connection

    result = await start_bank_connection(
        db, org_id,
        psu_id=psu_id, psu_corporate_id=psu_corporate_id, provider_ids=provider_ids,
    )
    result["note"] = "יש לשלוח ללקוח את הקישור (connect_url) להשלמת מסע ההסכמה מול הבנק."
    return result


def _parse_date_safe(value: str | None):
    """Best-effort ISO date parse for model-supplied filter args. A read tool
    executes inline in the chat loop with no surrounding try/except (unlike
    write tools, which are only ever run from confirm_action's ValueError
    guard) — a malformed string here must not raise and turn into an
    unhandled 500; it's simply treated as "no filter" instead."""
    from datetime import date as date_type
    if not value:
        return None
    try:
        return date_type.fromisoformat(value)
    except (ValueError, TypeError):
        return None


async def _list_expenses(
    db, org_id: int, *, status: str | None = None, category: str | None = None,
    from_date: str | None = None, to_date: str | None = None, supplier: str | None = None,
    **_kwargs,
) -> dict:
    """הצגת הוצאות — קריאה בלבד. עד 50 שורות מוחזרות, אך count/totals
    משקפים את כל הסט המסונן (לא רק את 50 השורות המוצגות)."""
    from sqlalchemy import func
    from ..models import Expense

    q = db.query(Expense).filter(Expense.organization_id == org_id)
    if status:
        q = q.filter(Expense.status == status)
    if category:
        q = q.filter(Expense.category == category)
    parsed_from = _parse_date_safe(from_date)
    if parsed_from:
        q = q.filter(Expense.expense_date >= parsed_from)
    parsed_to = _parse_date_safe(to_date)
    if parsed_to:
        q = q.filter(Expense.expense_date <= parsed_to)
    if supplier:
        q = q.filter(Expense.supplier_name.ilike(f"%{supplier}%"))

    count = q.count()
    total_amount, total_vat = q.with_entities(
        func.sum(Expense.amount), func.sum(Expense.vat_amount)
    ).first()
    rows = q.order_by(Expense.expense_date.desc()).limit(50).all()

    return {
        "count": count,
        "totals": {
            "amount": round(float(total_amount or 0), 2),
            "vat": round(float(total_vat or 0), 2),
        },
        "expenses": [
            {
                "id": e.id,
                "supplier": e.supplier_name,
                "amount": float(e.amount or 0),
                "vat": float(e.vat_amount or 0),
                "date": e.expense_date.isoformat() if e.expense_date else None,
                "category": e.category,
                "status": e.status,
            }
            for e in rows
        ],
    }


async def _get_pcn874_readiness(db, org_id: int, **_kwargs) -> dict:
    from .expense_filing_service import ExpenseFilingService
    return ExpenseFilingService(db, organization_id=org_id).pcn874_readiness()


async def _create_expense_category(
    db, org_id: int, *, key: str, name_he: str, keywords: list[str] | None = None, **_kwargs,
) -> dict:
    from . import expense_category_service
    return expense_category_service.create_category(
        db, org_id, key=key, name_he=name_he, keywords=keywords,
    )


async def _set_expense_category(db, org_id: int, *, expense_id: int, category: str, **_kwargs) -> dict:
    from .expense_filing_service import ExpenseFilingService
    service = ExpenseFilingService(db, organization_id=org_id)
    return service.update_expense(expense_id, {"category": category})


async def _classify_pending_expenses(db, org_id: int, **_kwargs) -> dict:
    from .expense_filing_service import ExpenseFilingService
    return ExpenseFilingService(db, organization_id=org_id).classify_pending()


async def _query_bank_transactions(
    db, org_id: int, *, date_from: str | None = None, date_to: str | None = None,
    search: str | None = None, txn_type: str | None = None, direction: str | None = None,
    only_unmatched: bool = False, limit: int = 50, **_kwargs,
) -> dict:
    from .bank_query_service import query_bank_transactions
    return query_bank_transactions(
        db, org_id, date_from=date_from, date_to=date_to, search=search,
        txn_type=txn_type, direction=direction, only_unmatched=only_unmatched, limit=limit,
    )


async def _get_bank_position(db, org_id: int, **_kwargs) -> dict:
    from .bank_query_service import get_bank_position
    return get_bank_position(db, org_id)


async def _get_missing_documents(db, org_id: int, *, date_from: str | None = None, **_kwargs) -> dict:
    from .bank_query_service import classify_missing_documents
    return classify_missing_documents(db, org_id, date_from=date_from)


async def _get_bank_expense_gap_alerts(db, org_id: int, **_kwargs) -> dict:
    from .bank_expense_gap import list_open_alerts
    return list_open_alerts(db, org_id)


async def _get_suppliers_missing_invoices(
    db, org_id: int, *, date_from: str | None = None, date_to: str | None = None, **_kwargs,
) -> dict:
    """ספקים ששולם להם ללא מסמך הוצאה/חשבונית תואם — אגרגציה ברמת ספק
    מעל bank_expense_gap.suppliers_missing_invoices. ברירת מחדל: 90 הימים
    האחרונים. מחזיר עד 20 ספקים מובילים (לפי סכום)."""
    from datetime import date as date_type, timedelta

    from .bank_expense_gap import suppliers_missing_invoices

    def _parse(s: str | None):
        if not s:
            return None
        try:
            return date_type.fromisoformat(s)
        except ValueError:
            return None

    parsed_to = _parse(date_to) or date_type.today()
    parsed_from = _parse(date_from) or (parsed_to - timedelta(days=90))

    result = suppliers_missing_invoices(db, org_id, parsed_from, parsed_to)
    result["suppliers"] = result["suppliers"][:20]
    return result


async def _rezef_help(db, org_id: int, *, topic: str | None = None, **_kwargs) -> dict:
    """Project knowledge-base lookup — "how do I / what can Rezef do / where
    is X". Ignores db/org_id (same signature as every other tool for
    uniform dispatch in ai_chat_service, but this one tool is pure content,
    no query) — see rezef_kb.py for the KB itself and why it lives outside
    SYSTEM_PROMPT (token cost)."""
    from . import rezef_kb
    return {"content": rezef_kb.get_topic(topic)}


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
    "create_bank_payment_request": ChatTool(
        name="create_bank_payment_request",
        description=(
            "יצירת בקשת תשלום בהעברה בנקאית דרך Open Finance (בנקאות פתוחה): מחזירה "
            "קישור תשלום (payUrl) שנשלח למשלם, והמשלם מאשר את ההעברה ישירות מול הבנק "
            "שלו. פעולת כתיבה אמיתית מול Open Finance — דורשת אישור מפורש של המשתמש "
            "לפני ביצוע. הכסף עובר רק לאחר אישור המשלם בבנק."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "סכום בש\"ח (חיובי)"},
                "description": {"type": "string", "description": "תיאור התשלום"},
                "creditor_name": {"type": "string", "description": "שם המוטב"},
                "creditor_account_number": {
                    "type": "string",
                    "description": "חשבון המוטב: bban בפורמט בנק-סניף-חשבון (למשל 12-345-67890) או IBAN",
                },
                "creditor_account_type": {
                    "type": "string",
                    "enum": ["bban", "iban"],
                    "default": "bban",
                },
            },
            "required": ["amount", "description", "creditor_name", "creditor_account_number"],
        },
        category="write",
        fn=_create_bank_payment_request,
    ),
    "connect_bank_account": ChatTool(
        name="connect_bank_account",
        description=(
            "מתחיל מסע חיבור חשבון בנק בבנקאות פתוחה (Open Finance) ומחזיר קישור "
            "(connect_url) שיש לשלוח ללקוח כדי שישלים את מסך אישור שיתוף המידע מול "
            "הבנק שלו. פעולת כתיבה אמיתית — יוצרת חיבור חדש מול Open Finance — דורשת "
            "אישור מפורש של המשתמש לפני ביצוע."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "psu_id": {"type": "string", "description": "ת.ז. בעל החשבון (אופציונלי)"},
                "psu_corporate_id": {"type": "string", "description": "ח.פ. לחשבון עסקי (אופציונלי)"},
                "provider_ids": {
                    "type": "array", "items": {"type": "string"},
                    "description": "סינון לבנק/ים ספציפיים; השמטה מציגה מסך בחירת בנק (אופציונלי)",
                },
            },
        },
        category="write",
        fn=_connect_bank_account,
    ),
    "list_expenses": ChatTool(
        name="list_expenses",
        description=(
            "רשימת הוצאות עם סינון (סטטוס, קטגוריה, טווח תאריכים, חיפוש חופשי לפי "
            "שם ספק) — עד 50 שורות מוחזרות, עם count וסה\"כ (amount/vat) על כל "
            "הסט המסונן, לא רק על השורות המוצגות."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["pending", "filed", "error"]},
                "category": {"type": "string", "description": "מפתח קטגוריה, מובנית או כרטיס מותאם אישית"},
                "from_date": {"type": "string", "description": "ISO date"},
                "to_date": {"type": "string", "description": "ISO date"},
                "supplier": {"type": "string", "description": "התאמה חלקית לשם ספק"},
            },
        },
        category="read",
        fn=_list_expenses,
    ),
    "get_pcn874_readiness": ChatTool(
        name="get_pcn874_readiness",
        description="דוח מוכנות PCN874 — אילו הוצאות מתויקות חסרות ח.פ/מע\"מ וסיכום סכומים.",
        input_schema={"type": "object", "properties": {}},
        category="read",
        fn=_get_pcn874_readiness,
    ),
    "create_expense_category": ChatTool(
        name="create_expense_category",
        description=(
            "פתיחת קטגוריית/כרטיס הוצאה מותאם אישית לארגון, עם מילות מפתח "
            "אופציונליות לסיווג אוטומטי עתידי. פעולת כתיבה — דורשת אישור מפורש."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "מזהה ייחודי (slug) לכרטיס"},
                "name_he": {"type": "string", "description": "שם תצוגה בעברית"},
                "keywords": {
                    "type": "array", "items": {"type": "string"},
                    "description": "מילות מפתח לסיווג אוטומטי (אופציונלי)",
                },
            },
            "required": ["key", "name_he"],
        },
        category="write",
        fn=_create_expense_category,
    ),
    "set_expense_category": ChatTool(
        name="set_expense_category",
        description=(
            "שינוי קטגוריית הוצאה בודדת (לפי מזהה) — מובנית או כרטיס מותאם "
            "אישית קיים. פעולת כתיבה — דורשת אישור מפורש."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "expense_id": {"type": "integer"},
                "category": {"type": "string"},
            },
            "required": ["expense_id", "category"],
        },
        category="write",
        fn=_set_expense_category,
    ),
    "classify_pending_expenses": ChatTool(
        name="classify_pending_expenses",
        description=(
            "סיווג אוטומטי גורף של הוצאות ממתינות (status=pending) שעדיין ללא "
            "קטגוריה אמיתית — מחזיר פירוט כמות לפי קטגוריה. פעולת כתיבה — "
            "דורשת אישור מפורש."
        ),
        input_schema={"type": "object", "properties": {}},
        category="write",
        fn=_classify_pending_expenses,
    ),
    "query_bank_transactions": ChatTool(
        name="query_bank_transactions",
        description=(
            "חיפוש/סינון תנועות בנק ואשראי (Open Finance) — לפי טווח תאריכים, "
            "טקסט חופשי בתיאור, סוג חשבון (CHECKING/CARD), כיוון (in=זיכוי/"
            "out=חיוב), ורק תנועות שלא הותאמו (only_unmatched). שימושי לשאלות "
            "כמו 'כמה הוצאתי על X' או 'מה נכנס/יצא מהחשבון החודש'. עד 50 שורות "
            "מוחזרות, אך count/total_amount משקפים את כל הסט המסונן (לא רק את "
            "השורות המוצגות)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "תאריך התחלה (ISO)"},
                "date_to": {"type": "string", "description": "תאריך סיום (ISO)"},
                "search": {"type": "string", "description": "חיפוש חופשי בתיאור התנועה"},
                "txn_type": {"type": "string", "enum": ["CHECKING", "CARD"]},
                "direction": {"type": "string", "enum": ["in", "out"], "description": "in=זיכוי, out=חיוב"},
                "only_unmatched": {"type": "boolean", "description": "רק תנועות שלא הותאמו למסמך", "default": False},
                "limit": {"type": "integer", "default": 50},
            },
        },
        category="read",
        fn=_query_bank_transactions,
    ),
    "get_bank_position": ChatTool(
        name="get_bank_position",
        description=(
            "תמונת מצב עדכנית לכל חשבון בנק/אשראי — יתרה, תאריך התנועה האחרונה "
            "וכמות תנועות. מסמן בפירוש אם קיימים נתונים 'זמניים' (is_provisional, "
            "טרם אושרו סופית דרך מסע ה-Open Finance) כדי שלא יוצגו כעובדה סופית."
        ),
        input_schema={"type": "object", "properties": {}},
        category="read",
        fn=_get_bank_position,
    ),
    "get_missing_documents": ChatTool(
        name="get_missing_documents",
        description=(
            "איתור תנועות בנק יוצאות שלא הותאמו למסמך הנה\"ח וסיווגן: תשלומי "
            "מס/ביטוח לאומי, העברות, משיכות מזומן, סליקת אשראי (card_settlement), "
            "הוראות קבע, עמלות בנק, הלוואות ושכר — מול 'missing_document' שהן "
            "התנועות שבאמת חסר להן מסמך. מחזיר סה\"כ לכל קטגוריה ורשימת הספקים/"
            "התיאורים החוזרים (top_candidates) לפי ערוץ (בנק/אשראי)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "תאריך התחלה (ISO) — ברירת מחדל: כל ההיסטוריה"},
            },
        },
        category="read",
        fn=_get_missing_documents,
    ),
    "get_bank_expense_gap_alerts": ChatTool(
        name="get_bank_expense_gap_alerts",
        description=(
            "התרעות פתוחות ('missing_document') על הוצאות בבנק ללא מסמך הנה\"ח, "
            "שנוצרו ע\"י הסריקה היומית האוטומטית (cron/bank-gap-scan, מנוע פער "
            "בנק-חשבוניות) — לא סיווג בזמן אמת כמו get_missing_documents, אלא "
            "רשימת ההתרעות ששמורות כבר במערכת. שימושי לשאלה 'אילו הוצאות בלי "
            "חשבונית' / 'מה עוד לא תויק מהבנק' כשרוצים את הרשימה הרשמית "
            "שהתעדה נוצרה עליה."
        ),
        input_schema={"type": "object", "properties": {}},
        category="read",
        fn=_get_bank_expense_gap_alerts,
    ),
    "get_suppliers_missing_invoices": ChatTool(
        name="get_suppliers_missing_invoices",
        description=(
            "ספקים ששולם להם (בבנק/אשראי) אך אין כנגד התשלום מסמך הוצאה/"
            "חשבונית — אגרגציה ברמת ספק (לא תנועה בודדת) מעל מנוע פער "
            "בנק-חשבוניות, לטווח תאריכים חופשי (ברירת מחדל: 90 הימים "
            "האחרונים). מחזיר לכל ספק: מס' תשלומים, סה\"כ ששולם, מע\"מ "
            "משוער אבוד וטווח תאריכים; בנפרד — 'unidentified_transfers', "
            "העברות גנריות (כמו 'העברה לבנק אחר'/'הוראת קבע') שלא ניתן "
            "לזהות בהן ספק ספציפי. שימושי לשאלה 'מאילו ספקים חסרה לי "
            "חשבונית' / 'איפה אני מפסיד מע\"מ תשומות'."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "תאריך התחלה (ISO) — ברירת מחדל: 90 יום אחורה"},
                "date_to": {"type": "string", "description": "תאריך סיום (ISO) — ברירת מחדל: היום"},
            },
        },
        category="read",
        fn=_get_suppliers_missing_invoices,
    ),
    "rezef_help": ChatTool(
        name="rezef_help",
        description=(
            "מדריך/מאגר-ידע פנימי על רצף עצמו — מה כל מסך במערכת עושה, איך "
            "מבצעים תהליך מסוים (הוצאות/מע\"מ/גבייה/מס\"ב/הנה\"ח וכו'), אילו "
            "כלים זמינים לעוזר עצמו, ומה המגבלות הידועות. ללא topic מחזיר "
            "אינדקס נושאים עם תקציר שורה לכל אחד; עם topic ידוע מחזיר את "
            "התוכן המלא של אותו נושא. יש להשתמש בכלי הזה לפני שעונים על "
            "שאלות 'איך עושים X' / 'מה רצף יודע לעשות' / 'איפה נמצא Y' — "
            "ולא לנחש מהזיכרון."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "מפתח נושא (למשל expenses/vat/bookkeeping/reports/"
                        "collections/masav/office/bot/integrations/"
                        "limitations/overview). ריק או לא ידוע מחזיר את "
                        "אינדקס הנושאים."
                    ),
                },
            },
        },
        category="read",
        fn=_rezef_help,
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
