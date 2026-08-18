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
    # True only for tools that need to know WHO is acting (not just which
    # org) — e.g. propose_vat_filing_approval, which must load a real User
    # row to pass as IrreversibleActionService.propose(proposed_by=...).
    # ai_chat_service passes the caller's user_id as `_user_id` ONLY to
    # tools with this flag set, so the other ~39 existing tools' call
    # signature is completely unaffected (Moshko plan 2026-07-27, package D1).
    needs_user: bool = False
    # Stable policy-catalog action checked both when the write is proposed
    # and immediately before the atomic execution claim. Office-only tools
    # use the separate platform gate and deliberately leave this unset.
    policy_action: str | None = None


async def _find_capability(db, org_id: int, task: str = "", reads_only: bool = False, **_kwargs) -> dict:
    """היכולות של SUMIT ו-Open Finance שמשרתות משימה נתונה.

    הכלים הרשומים כאן מכסים 50 יכולות; ל-SumitIntegration ול-
    OpenFinanceClient יש יחד 172. הכלי הזה נותן למושקו לגלות מה קיים
    מעבר למה שנרשם ידנית, במקום להשיב "אין לי יכולת כזו" כשהיא קיימת.

    זהו כלי גילוי בלבד: הוא קורא את הקטלוג (introspection על הקוד) ואינו
    מפעיל דבר אצל הספק. `requires_approval` בכל תוצאה אומר למושקו מה
    יחייב אישור בעלים אם יתבקש להפעיל אותה בהמשך.
    """
    from .capability_catalog import find_capabilities

    matches = find_capabilities(task, reads_only=reads_only)
    return {
        "task": task,
        "count": len(matches),
        "capabilities": [
            {
                "system": entry["system"],
                "name": entry["name"],
                "parameters": entry["parameters"],
                "summary": entry["summary"],
                "kind": entry["kind"],
                "requires_approval": entry["requires_approval"],
            }
            for entry in matches
        ],
        "note": (
            "גילוי בלבד — היכולות האלה אינן ניתנות להפעלה ישירה מהשיחה. "
            "כל יכולת עם requires_approval עוברת דרך מנגנון האישורים."
        ),
    }


async def _suggest_expense_accounts(db, org_id: int, expense_id: int, **_kwargs) -> dict:
    """כרטיסים מועמדים לתיוק ההוצאה, מתוך אינדקס החשבונות של התיק."""
    from .expense_account_filing import suggest_accounts_for_expense

    matches = suggest_accounts_for_expense(db, org_id, expense_id)
    return {
        "expense_id": expense_id,
        "count": len(matches),
        "accounts": matches,
        "note": "אין התאמה = רשימה ריקה. אל תתייק לכרטיס שלא הוצע.",
    }


async def _file_expense_to_account(db, org_id: int, expense_id: int, account_id: int, **_kwargs) -> dict:
    """מתייק הוצאה לכרטיס באינדקס. תיוק חוזר מעביר לכרטיס אחר."""
    from .expense_account_filing import file_expense_to_account

    return file_expense_to_account(db, org_id, expense_id, account_id)


async def _list_my_capabilities(db, org_id: int, **_kwargs) -> dict:
    """מה מושקו יכול לבצע בתיק הזה, ומה חסום ולמה.

    הרשימה מלאה תמיד: משימה חסומה מופיעה עם הסיבה במקום להיעלם, כדי
    שהתשובה תהיה "היכולת קיימת אבל חסר חיבור X" ולא "אין לי יכולת כזו".
    """
    from .capability_tasks import executable_tasks_for_organization

    tasks = executable_tasks_for_organization(org_id)
    return {
        "organization_id": org_id,
        "executable": sum(1 for t in tasks if t["executable"]),
        "blocked": sum(1 for t in tasks if not t["executable"]),
        "tasks": tasks,
    }


async def _office_account_status(db, org_id: int, **_kwargs) -> dict:
    """מכסות ומצב חשבון המשרד — כמה תיקים מחויבים, והאם יש חסימת אובליגו.

    כלי משרד: מחזיר תמונה של פורטל ההנה"ח כולו, לא של תיק בודד. נגיש
    ל-SUPER_ADMIN בלבד (`office=True`).
    """
    from .office_capabilities import office_tasks_status

    status = office_tasks_status()
    if not status["configured"]:
        return {
            "configured": False,
            "reason": "חסרות הרשאות ברמת משרד (SUMIT_OFFICE_API_KEY / SUMIT_OFFICE_COMPANY_ID)",
            "tasks": status["tasks"],
        }

    from .office_capabilities import office_credentials
    from ..integrations.sumit_integration import SumitIntegration
    from .sumit_request_budget import SumitRequestLimiter

    creds = office_credentials()
    client = SumitIntegration(
        api_key=creds["api_key"],
        company_id=creds["company_id"],
        request_limiter=SumitRequestLimiter(org_id),
    )
    async with client:
        quotas = await client.list_quotas()

    rows = quotas.get("Data") or []
    return {
        "configured": True,
        "company_id": creds["company_id"],
        "quotas": [
            {
                "application": r.get("ApplicationName"),
                "statistic": r.get("StatisticName"),
                "usage": r.get("Usage"),
                "quota": r.get("Quota"),
            }
            for r in rows
        ],
        "note": "ValidBilling = רישיונות הנה\"ח בשימוש. תיקים שאינם נספרים שם אינם מחויבים.",
    }


async def _office_capabilities(db, org_id: int, **_kwargs) -> dict:
    """מה ניתן לבצע ברמת המשרד ומה חסום — בלי לחשוף את המפתח."""
    from .office_capabilities import office_tasks_status

    return office_tasks_status()


async def _get_ar_aging(db, org_id: int, **_kwargs) -> dict:
    from .dashboard_service import DashboardService
    return DashboardService(db, org_id).get_ar_aging()


async def _get_ap_aging(db, org_id: int, **_kwargs) -> dict:
    """AP aging עם דגל תנועת-בנק פר-חשבון (ר' DashboardService.get_ap_aging
    לממצא ולנימוק). קריאה בלבד."""
    from .dashboard_service import DashboardService
    return DashboardService(db, org_id).get_ap_aging()


async def _set_vehicle_profile(
    db, org_id: int, *, label: str, vehicle_kind: str,
    primarily_business: bool | None = None,
    attached_to_employee_with_use_value: bool = False,
    **_kwargs,
) -> dict:
    """יצירה/עדכון של פרופיל רכב — עיקר-השימוש קובע ניכוי מע"מ תשומות
    רכב (israeli_tax_rules.claimable_vat, KB02 §1).

    **honest-null, לא רק כלפי חוץ.** `primarily_business=None` הוא
    ברירת המחדל בחתימת הפונקציה עצמה — לא רק תיעוד. אם המודל לא מילא
    אותו כי המשתמש לא אמר במפורש, הוא נשאר None ו-`claimable_vat` ממשיך
    לתור הכרעה, בדיוק כמו היום. הכלי לעולם אינו מנחש 'עסקי בעיקר'
    מברירת מחדל.

    upsert לפי (org, label) — שיחה חוזרת על אותו רכב מעדכנת, לא מכפילה.
    """
    from ..models import VehicleProfile

    row = db.query(VehicleProfile).filter(
        VehicleProfile.organization_id == org_id,
        VehicleProfile.label == label,
    ).first()
    if row is None:
        row = VehicleProfile(organization_id=org_id, label=label)
        db.add(row)
    row.vehicle_kind = vehicle_kind
    row.primarily_business = primarily_business
    row.attached_to_employee_with_use_value = attached_to_employee_with_use_value
    db.commit()
    db.refresh(row)

    return {
        "status": "saved",
        "vehicle_profile": {
            "id": row.id, "label": row.label, "vehicle_kind": row.vehicle_kind,
            "primarily_business": row.primarily_business,
        },
    }


async def _get_ap_bills(db, org_id: int, days_ahead: int = 30, **_kwargs) -> dict:
    from .dashboard_service import DashboardService
    return {"bills": DashboardService(db, org_id).get_ap_bills(days_ahead=days_ahead)}


async def _get_pnl(db, org_id: int, months: int = 6, **_kwargs) -> dict:
    """דוח רווח והפסד — מבוסס financial_reports_service.generate_profit_loss
    (ledger חי: Invoice/Bill/Expense בסכומי נטו מפוצלי-מע"מ), לא
    DashboardService (מקור כפול — הכרעת מועצה 2026-07-26: כלי P&L אחד).
    מחזיר את דוח ה-ProfitLossReport המלא (revenue/expenses/gross/operating/
    net לתקופה) + source='ledger' לזיהוי המקור."""
    from datetime import date
    from dateutil.relativedelta import relativedelta
    from .financial_reports_service import FinancialReportsService

    end_date = date.today()
    start_date = end_date - relativedelta(months=months)
    report = FinancialReportsService(db).generate_profit_loss(
        org_id, start_date, end_date, compare_previous=False,
    )
    result = report.to_dict()
    result["source"] = "ledger"
    return result


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


async def _get_trial_balance(db, org_id: int, *, start: str | None = None,
                             end: str | None = None, **_kwargs) -> dict:
    """מאזן בוחן — מחושב מה-ledger של רצף, **לא נמשך מ-SUMIT**.

    SUMIT אינה חושפת endpoint למאזן בוחן (ראו
    `docs/bookkeeper_kb/09-sumit-operations-map.md`), ואין בכך חיסרון:
    רצף מחזיקה הנהלת חשבונות כפולה משלה ומחשבת אותו מהנתונים שנמשכו
    בסנכרון היומי. שאלת משתמש לעולם אינה מייצרת קריאת API — זה מה
    שהוביל לחסימת ה-IP ב-13/08/2026.

    `balanced` הוא השדה שקובע אם אפשר להסתמך על המספר. מאזן שאינו
    מאוזן, או שנשען על מנות פתוחות, אינו סופי.
    """
    from .ledger_service import trial_balance

    report = trial_balance(
        db, org_id,
        start=_parse_date_safe(start), end=_parse_date_safe(end),
    )
    payload = report.as_dict() if hasattr(report, "as_dict") else dict(report)
    payload["source"] = "rezef_ledger"
    payload["balanced"] = bool(payload.get("balanced"))

    # SUMIT אינה חושפת קריאת מאזן בוחן בשום הרשאה, ולכן רצף **אינה
    # יכולה** לאמת תכנותית שהמספר תואם לספר הרשמי. הגרסה הראשונה קבעה
    # `is_final` על סמך חובה=זכות בלבד — וזה מדד את הדבר הלא-נכון:
    # מאזן יכול להיות מאוזן אצלנו ובכל זאת לא לתאום, למשל כשפקודה
    # נשלחה ב-createbatch, חזרה `executed_unverified`, ולא נקלטה.
    payload["sumit_parity"] = "not_checked"
    payload["is_final"] = bool(payload["balanced"]) and payload["sumit_parity"] == "verified"
    payload["not_final_reason"] = (
        "המספר מחושב מהספרים של רצף ו**לא הוצלב מול SUMIT**. SUMIT היא "
        "התוכנה המאושרת שמפיקה את הדיווח, ואין ב-API שלה קריאת מאזן — "
        "ההצלבה נעשית מול מאזן שמורידים מהפורטל. שים לב גם למנות פתוחות: "
        "מאזן שהופק כשהן פתוחות כולל אותן ואינו סופי. "
        "אין לדווח לפי מספר זה לפני הצלבה."
    )
    return payload


async def _get_open_batches(db, org_id: int, **_kwargs) -> dict:
    """מנות פתוחות — **SUMIT אינה חושפת קריאת מנות בשום הרשאה.**

    honest-null: מחזיר `unavailable` עם סיבה, ולא רשימה ריקה. רשימה
    ריקה הייתה נקראת כ"אין מנות פתוחות" — קביעה שאין לה בסיס, והיא
    בדיוק סוג הטעות שמובילה לדווח לפי מאזן לא-סופי.
    """
    return {
        "status": "unavailable",
        "reason_he": (
            "SUMIT אינה חושפת קריאת מנות ב-API (מודול הספרים חושף "
            "createbatch בלבד). מצב המנות נבדק במסך 'כל המנות הפתוחות' "
            "בפורטל."
        ),
        "portal_path": "הנהלת חשבונות ← תנועות יומן ← כל המנות הפתוחות",
        "what_rezef_knows": (
            "רצף יודעת אילו פקודות היא שלחה ומתי, אך לא אם המנה נסגרה."
        ),
    }


async def _propose_books_batch(db, org_id: int, *, description: str,
                               **_kwargs) -> dict:
    """הצעת מנה לספרים — רישום **בלתי-הפיך** אצל הספק.

    אינו מבצע. יוצר הצעה שדורשת אישור מפורש, לפי חוזה
    `IRREVERSIBLE_ACTION_CONTROL.md`. הביצוע עצמו עובר ב-adapter
    שצורך payload מאושר ושמור, תופס ביצוע פעם אחת, ועוצר ב-
    `executed_unverified` — כי אין readback.
    """
    return {
        "status": "proposed",
        "action_type": "books_batch",
        "description": description,
        "requires_owner_approval": True,
        "irreversible": True,
        "note_he": (
            "יצירת מנה היא רישום לספרים. אחרי הביצוע לא ניתן לאמת "
            "תכנותית שהמנה נקלטה — נדרש אימות בפורטל, וסגירתה ידנית."
        ),
    }


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
    from .kb_loader import kb_index
    result = engine_service.status(db, org_id)
    # kb_files_available: a cheap, org-agnostic presence check so prod can be
    # verified to have the KB actually packaged (see kb_lookup) — 0 rather
    # than a missing key when the KB isn't available, honest-null style.
    idx = kb_index()
    result["kb_files_available"] = idx.get("file_count", 0) if idx.get("available") else 0
    return result


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
    """שינוי קטגוריה דרך מושקו — סוגר את לולאת הלמידה: כל תיקון בשיחה נרשם
    גם כ-classifier_feedback (record_classifier_feedback הקיים, ר'
    manual_reconciliation.py — לא משוכפל כאן), כך שתיקון חוזר של אותו ספק
    הופך בהמשך לכלל נלמד שהמסווג צורך (expense_classifier.classify_expense
    עם learned_rules, ר' חבילה I 2026-07-27).

    סדר הפעולות קריטי: record_classifier_feedback רץ *ראשון* כי הוא זה
    שקורא את exp.category הנוכחי (האמיתי, טרם השינוי) כ-old_category — אם
    update_expense היה רץ קודם, old_category שנרשם היה כבר שווה ל-new
    category והפידבק היה חסר-משמעות. update_expense רץ אחריו רק כדי
    לחשב מחדש שדות נגזרים (vat_claimable/ניכוי) לפי הקטגוריה החדשה — הוא
    אינו כותב יותר ל-classifier_feedback, כדי לא לשכפל את לוגיקת הלמידה."""
    from .expense_filing_service import ExpenseFilingService
    from .manual_reconciliation import ManualReconciliationService
    from .expense_classifier import VALID_CATEGORIES
    from . import expense_category_service

    valid_keys = VALID_CATEGORIES | expense_category_service.org_category_keys(db, org_id)
    if category not in valid_keys:
        raise ValueError(f"קטגוריה לא מוכרת: {category}")

    ManualReconciliationService(db, org_id).record_classifier_feedback(
        entity_id=expense_id, entity_type="expense", corrected_category=category,
    )
    service = ExpenseFilingService(db, organization_id=org_id)
    return service.update_expense(expense_id, {"category": category})


async def _get_learned_rules(db, org_id: int, **_kwargs) -> dict:
    """מה מושקו למד על סיווג הוצאות מתיקוני משתמש קודמים — לכל כלל: ספק,
    קטגוריה, וכמה תיקונים ביססו אותו (סף: 3). כולל גם ספקים שעדיין מתחת
    לסף כדי שהמשתמש יראה — ויוכל לתקן — גם מה שעוד לא הפך לכלל בפועל."""
    from .classifier_ml_training import ClassifierMLTrainingService

    result = ClassifierMLTrainingService(db, org_id).get_learned_rules()
    rules = [
        {
            "supplier": supplier,
            "category": info["category"],
            "correction_count": info["correction_count"],
        }
        for supplier, info in result["rules"].items()
    ]
    return {
        "learned_rules": rules,
        "below_threshold": result["below_threshold"],
        "min_corrections_required": result["min_corrections"],
    }


async def _classify_pending_expenses(db, org_id: int, **_kwargs) -> dict:
    from .expense_filing_service import ExpenseFilingService
    return ExpenseFilingService(db, organization_id=org_id).classify_pending()


async def _file_expense(db, org_id: int, *, expense_id: int, **_kwargs) -> dict:
    """תיוק הוצאה בפועל ב-SUMIT — עוטף ExpenseFilingService.file_to_sumit
    הקיים (כולל שער הכפילויות שכבר בתוכו). פעולה בלתי-הפיכה (יוצרת מסמך
    אמיתי ב-SUMIT) — לכן category="write" למטה."""
    from .expense_filing_service import ExpenseFilingService
    service = ExpenseFilingService(db, organization_id=org_id)
    return await service.file_to_sumit(expense_id)


async def _get_expense_intake_status(db, org_id: int, **_kwargs) -> dict:
    """כמה קבלות נקלטו היום דרך הצ'אט מול התקרה היומית, וכמה טיוטות
    ממתינות לתיוק — קריאה בלבד, ללא הרצת LLM/תיוק."""
    from ..config import settings
    from ..models import Expense
    from .chat_expense_intake import count_receipts_today

    intake_today = count_receipts_today(db, org_id, "telegram")
    pending_filing = (
        db.query(Expense)
        .filter(Expense.organization_id == org_id, Expense.status == "pending")
        .count()
    )
    return {
        "intake_today": intake_today,
        "daily_limit": settings.chat_receipt_daily_limit,
        "intake_enabled": settings.chat_receipt_intake_enabled,
        "pending_filing": pending_filing,
    }


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


async def _get_credit_line_status(db, org_id: int, days: int = 30, **_kwargs) -> dict:
    """מסגרת אשראי בנקאית — עד מתי צפויה חריגה/התקרבות למסגרת, על בסיס
    הליכת יתרה יומית מול Account.credit_limit הידוע (org-level, לא לפי
    חשבון בודד — ראו הסתייגות credit_line_service)."""
    from .credit_line_service import get_credit_line_status
    return get_credit_line_status(db, org_id, days=days)


async def _get_ar_health(db, org_id: int, months: int = 12, target_dso: int = 30, **_kwargs) -> dict:
    """בריאות גבייה — מגמת DSO אמיתית (ממוצע ימי-תשלום בפועל) + סיכומי
    סיכון/גבייה מדוח הגיול. לא כולל את פירוט הלקוחות המלא (זמין דרך
    get_ar_aging) — רק המדדים המצטברים."""
    from .ar_service import AccountsReceivableService

    svc = AccountsReceivableService(db, org_id)
    dso_trend = svc.get_dso_trend(months=months, target_dso=target_dso)
    aging = svc.get_aging_report()
    return {
        "dso_trend": dso_trend,
        "current_dso": dso_trend[-1]["dso"] if dso_trend else None,
        "target_dso": target_dso,
        "total_receivables": aging.total_receivables,
        "weighted_average_days": aging.weighted_average_days,
        "risk_summary": aging.risk_summary,
        "collection_summary": aging.collection_summary,
    }


async def _get_cfo_insights(
    db, org_id: int, *, status: str = "active", severity: str | None = None,
    limit: int = 20, **_kwargs,
) -> dict:
    """תובנות CFO קיימות (persisted CfoInsight) — קריאה בלבד מהמאגר; אינו
    מריץ ניתוח מלא (run_analysis) כברירת מחדל, כדי לא להריץ עיבוד כבד על
    כל שאלת צ'אט."""
    from .cfo_brain_service import CFOBrainService
    insights = CFOBrainService(db, org_id).list_insights(
        status=status, severity=severity, limit=limit,
    )
    return {"insights": insights}


async def _get_daily_brief(db, org_id: int, **_kwargs) -> dict:
    """בריף הבוקר של היום (טקסט טהור) — אותו תוכן שנשלח באימייל/SMS,
    מבוסס DailySnapshot/CfoInsight קיימים; אינו מריץ מחזור-בוקר חדש."""
    from datetime import date
    from .morning_brief_service import compose_brief, render_hebrew

    brief = compose_brief(db, org_id, date.today())
    subject, text, _html = render_hebrew(brief)
    return {"subject": subject, "text": text}


async def _get_tax_estimate(
    db, org_id: int, *, year: int | None = None, month: int | None = None, **_kwargs,
) -> dict:
    """אומדן מקדמת מס גס — לא תחליף לחישוב מחייב. חובה method+caveat+
    confidence=low בפלט (הכרעת מועצה 2026-07-26: אף אומדן מס בלי הסתייגות
    מפורשת)."""
    from datetime import date
    from .tax_service import TaxComplianceService

    today = date.today()
    y = year or today.year
    m = month or today.month
    advance = TaxComplianceService(db, org_id).calculate_tax_advance(y, m)
    return {
        "period": advance.period,
        "due_date": advance.due_date,
        "calculated_amount": advance.calculated_amount,
        "previous_payments": advance.previous_payments,
        "remaining_amount": advance.remaining_amount,
        "payment_status": advance.payment_status,
        "method": "רווח שנתי מוערך × שיעור מס חברות ÷ 12",
        "caveat": (
            "אומדן גס — ללא מדרגות מס ליחיד, ללא נתוני שומה; לחישוב מחייב "
            "יש לפנות לרו\"ח."
        ),
        "confidence": "low",
    }


async def _verify_filing(
    db, org_id: int, *, year: int, month: int, months: int = 1,
    basis: str = "document", **_kwargs,
) -> dict:
    """אימות משולש (3 בדיקות בלתי-תלויות) של דיווח המע"מ לתקופה — קריאה
    בלבד, יש להריץ לפני כל שידור בפועל לרשות."""
    from .filing_verification import verify_filing
    return verify_filing(db, org_id, year, month, months=months, basis=basis)


async def _kb_lookup(db, org_id: int, *, query: str | None = None, **_kwargs) -> dict:
    """מרכז ידע חשבונאי/מיסויי (docs/bookkeeper_kb + docs/sumit_help_kb).

    מ-17/08/2026 החיפוש עובר דרך `kb_index` — אחזור אינדקסי מה-DB במקום
    סריקת regex על הקבצים בכל בקשה. `kb_index.search` נופל אוטומטית חזרה
    לקבצים כשהאינדקס ריק (סביבה חדשה, זריעה שטרם רצה), ולכן זו אינה
    נקודת כשל חדשה.

    אין query -> אינדקס המרכזים (כמו rezef_kb.get_topic(None)).
    honest-null אם ה-KB לא ארוז בסביבה זו.
    """
    from .kb_index import search as index_search
    from .kb_loader import kb_index
    if not query or not query.strip():
        return kb_index()
    return index_search(query)


async def _get_bank_reconciliation(db, org_id: int, **_kwargs) -> dict:
    """מצב ההתאמות בין תנועות הבנק למסמכי ההנה"ח.

    **קריאה בלבד** (`persist=False`). התאמה היא רישום שמשנה נתונים,
    ולכן היא אינה נעשית כתופעת-לוואי של שאלה בצ'אט — אחרת "מה מצב
    ההתאמות?" היה מבצע התאמות. שינוי מצב עובר במסלול האישור.

    שני הצדדים מדווחים תמיד: "X הותאמו" בלי "Y לא" מסתיר בדיוק את מה
    שמנהל החשבונות מחפש.
    """
    from .bank_reconciliation import reconcile_organization

    result = reconcile_organization(db, org_id, persist=False)
    matches = result.get("matches") or []
    # תוקן 18/08/2026: המפתח האמיתי מהמנוע הוא unmatched_txns (ר'
    # bank_reconciliation.reconcile). "unmatched"/"unmatched_bank" אינם
    # קיימים בתשובה — הכלי דיווח unmatched=0 **תמיד**, מאז שנבנה,
    # והבטחת "X הותאמו, Y לא" הופרה מהיום הראשון. נתפס רק ע"י בדיקת
    # מכלול חוצה-כלים, לא ע"י הטסט המבודד שבדק רק key-presence.
    unmatched = result.get("unmatched_txns") or []
    return {
        "matched": len(matches),
        "unmatched": len(unmatched) if isinstance(unmatched, list) else unmatched,
        "matches_sample": matches[:10],
        "unmatched_sample": unmatched[:10] if isinstance(unmatched, list) else [],
        "persisted": False,
        "note_he": (
            "קריאה בלבד — ההתאמות לא נשמרו. שמירה מתבצעת במחזור הבוקר "
            "או במסלול אישור ייעודי."
        ),
    }


async def _rezef_help(db, org_id: int, *, topic: str | None = None, **_kwargs) -> dict:
    """Project knowledge-base lookup — "how do I / what can Rezef do / where
    is X". Ignores db/org_id (same signature as every other tool for
    uniform dispatch in ai_chat_service, but this one tool is pure content,
    no query) — see rezef_kb.py for the KB itself and why it lives outside
    SYSTEM_PROMPT (token cost)."""
    from . import rezef_kb
    return {"content": rezef_kb.get_topic(topic)}


# ------------------------------------------------------------------------ #
# Package C (Moshko plan 2026-07-27) — email_report. Recipient safety: the
# model must never invent a recipient. The tool itself can only check one
# half of that rule (is recipient_email a known org Contact?) — the other
# half (did the USER type this address explicitly in the conversation?)
# lives in the tool description below, since the tool has no access to chat
# history. `recipient_verified_as` in the result makes the source visible on
# the confirmation card the user sees before the write actually executes.
# ------------------------------------------------------------------------ #
async def _email_report(
    db, org_id: int, *,
    report_type: str, recipient_email: str,
    period_months: int | None = None,
    year: int | None = None, month: int | None = None,
    note: str | None = None,
    **_kwargs,
) -> dict:
    from datetime import date
    import calendar
    from dateutil.relativedelta import relativedelta
    from ..config import settings
    from ..models import Contact, Organization
    from .email_sender import send_email_smtp
    from .financial_reports_service import FinancialReportsService

    if not (settings.smtp_host and settings.smtp_from):
        return {
            "status": "not_configured",
            "message": "שליחת מייל אינה מוגדרת במערכת זו (חסר SMTP_HOST/SMTP_FROM) — לא נשלח דבר.",
        }

    contact = (
        db.query(Contact)
        .filter(
            Contact.organization_id == org_id,
            Contact.email == recipient_email,
            Contact.is_active.is_(True),
        )
        .first()
    )
    recipient_verified_as = f"contact:{contact.name}" if contact is not None else "user_supplied"

    org = db.query(Organization).filter(Organization.id == org_id).first()
    org_name = org.name if org is not None else "הארגון"

    svc = FinancialReportsService(db)
    xlsx_subtype = "vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    if report_type == "profit_loss":
        months = period_months or 6
        end_date = date.today()
        start_date = end_date - relativedelta(months=months)
        report = svc.generate_profit_loss(org_id, start_date, end_date, compare_previous=False)
        excel_bytes = svc.export_profit_loss_excel(report)
        period_label = f"{start_date.isoformat()} עד {end_date.isoformat()}"
        filename = f"רווח-והפסד-{end_date.strftime('%Y-%m')}.xlsx"
    elif report_type == "balance_sheet":
        if year and month:
            as_of = date(year, month, calendar.monthrange(year, month)[1])
        else:
            as_of = date.today()
        report = svc.generate_balance_sheet(org_id, as_of, compare_previous=False)
        excel_bytes = svc.export_balance_sheet_excel(report)
        period_label = f"נכון ל-{as_of.isoformat()}"
        filename = f"מאזן-{as_of.strftime('%Y-%m-%d')}.xlsx"
    elif report_type == "cash_flow":
        months = period_months or 12
        report = svc.generate_cash_flow_projection(org_id, months=months)
        excel_bytes = svc.export_cash_flow_projection_excel(report)
        period_label = f"{months} חודשים קדימה"
        filename = f"תזרים-חזוי-{date.today().strftime('%Y-%m')}.xlsx"
    else:
        return {"status": "failed", "message": f"סוג דוח לא מוכר: {report_type}"}

    subject = f"{org_name} — דוח {report_type} ({period_label})"
    body_lines = ["שלום,", "", f"מצורף הדוח המבוקש: {subject}."]
    if note:
        body_lines += ["", note]
    body_lines += ["", "בברכה,", f"{org_name} — נשלח אוטומטית על ידי מושקו"]
    body = "\n".join(body_lines)

    sent = await send_email_smtp(
        recipient_email, subject, body, settings,
        attachments=[(filename, excel_bytes, xlsx_subtype)],
    )
    if not sent:
        return {
            "status": "failed",
            "message": "שליחת המייל נכשלה בפועל (ראו לוג SMTP) — הדוח לא הגיע.",
            "recipient_verified_as": recipient_verified_as,
        }

    return {
        "status": "sent",
        "recipient_email": recipient_email,
        "recipient_verified_as": recipient_verified_as,
        "report_type": report_type,
        "period": period_label,
        "filename": filename,
        "message": f"הדוח נשלח בהצלחה אל {recipient_email}.",
    }


# ------------------------------------------------------------------------ #
# Package D (Moshko plan 2026-07-27) — VAT filing approval. Rezef has NO
# transmission mechanism to the tax authority (rezef_kb.py:244 — transmission
# happens only through the SUMIT UI). This tool never claims otherwise: it
# records the OWNER's approval of the numbers as an IrreversibleActionRequest
# (action_type="filing_submission") after the mandatory triple verification,
# and is explicit in both its description and its output that actual
# transmission is a separate, manual, SUMIT-side step.
# ------------------------------------------------------------------------ #
async def _propose_vat_filing_approval(
    db, org_id: int, *,
    year: int, month: int, months: int = 1, basis: str = "document",
    _user_id: int | None = None,
    **_kwargs,
) -> dict:
    from ..models import User
    from .daily_reports_service import vat_report_period
    from .filing_verification import verify_filing
    from .irreversible_action_service import IrreversibleActionService

    verification = verify_filing(db, org_id, year, month, months=months, basis=basis)

    if verification["status"] == "fail":
        return {
            "status": "blocked_by_verification",
            "verification": verification,
            "message": "האימות המשולש נכשל — לא ניתן לאשר דיווח לפני תיקון",
        }

    user = db.query(User).filter(User.id == _user_id).first() if _user_id else None
    from . import membership_service
    if user is None or not membership_service.is_member(db, user.id, org_id):
        return {
            "status": "failed",
            "message": "לא ניתן לאמת את זהות המשתמש המבקש — הפעולה בוטלה.",
        }

    report = vat_report_period(db, org_id, year, month, months=months, basis=basis)
    period_label = f"{year}-{month:02d}"
    caveat = (
        "רצף אינו משדר לרשות המסים. אישור זה מתעד את אישור הבעלים למספרים; "
        "השידור בפועל מתבצע בממשק SUMIT."
    )
    # The hashed payload must be a STABLE snapshot of the reviewed numbers.
    # verification["checks"] as returned by verify_filing carries volatile
    # per-call fields (check 3's free-text `details` embeds sync age/dates,
    # plus a separate `sync_age_hours`) — hashing that directly would break
    # idempotency: proposing the exact same period a few minutes apart would
    # hash differently and hit ActionConflictError instead of returning the
    # existing request (proven by test_idempotent_double_call_with_real_
    # unmocked_verify_filing, which runs the real verify_filing twice —
    # a mocked verify_filing can't catch this). Only a stable projection
    # (name + passed) goes into the hashed payload; the full, rich
    # verification object is still returned in the tool's output below
    # (never hashed) so the model/user sees the complete picture.
    stable_checks = [
        {"name": c["name"], "passed": c["passed"]} for c in verification["checks"]
    ]
    payload = {
        "period": report["period"],
        "basis": basis,
        "months": months,
        "output_vat": float(report["output_vat"]),
        "input_vat": float(report["input_vat"]),
        "net_vat": float(report["net_vat"]),
        "verification_status": verification["status"],
        "verification_checks": stable_checks,
    }

    service = IrreversibleActionService(db, org_id)
    try:
        row = service.propose(
            proposed_by=user,
            action_type="filing_submission",
            payload=payload,
            idempotency_key=f"vat-filing:{org_id}:{period_label}:{basis}",
            description=(
                f"אישור בעלים למספרי דיווח מע\"מ לתקופה {period_label} "
                f"(basis={basis}) — לא כולל שידור בפועל, שנעשה ידנית ב-SUMIT."
            ),
            channel=str(_kwargs.get("_channel") or "web"),
        )
    except ValueError as exc:
        return {"status": "failed", "message": str(exc)}

    return {
        "status": "proposed",
        "request_id": row.id,
        "action_type": row.action_type,
        "period": report["period"],
        "basis": basis,
        "verification_status": verification["status"],
        "verification": verification,
        "transmission": "manual_via_sumit",
        "caveat": caveat,
        "message": (
            f"נרשמה בקשת אישור למספרי דיווח מע\"מ {period_label} (בקשה #{row.id}). {caveat}"
        ),
    }


async def _list_pending_approvals(db, org_id: int, **_kwargs) -> dict:
    from .irreversible_action_service import IrreversibleActionService

    rows = IrreversibleActionService(db, org_id).list(status="proposed")
    return {
        "pending": [
            {
                "id": row.id,
                "action_type": row.action_type,
                "description": row.description,
                "proposed_at": row.proposed_at.isoformat() if row.proposed_at else None,
            }
            for row in rows
        ],
    }


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


# ------------------------------------------------------------------------ #
# Package E (2026-07-27b moshko-memory-and-whatsapp plan) — Moshko's learned
# memory. `memory` is category="write": a memory write is a persisted state
# change (not a one-off answer), and needs_user=True so the caller's real
# identity (never model-supplied) is used to resolve scope="user" writes —
# same needs_user pattern as propose_vat_filing_approval. `search_history`
# is category="read": it complements the 30-message history cap in
# ai_chat_service.py by letting Moshko look further back on demand instead
# of the memory layer trying to hold everything.
# ------------------------------------------------------------------------ #
async def _memory(
    db, org_id: int, *,
    action: str, content: str | None = None, scope: str = "org",
    match: str | None = None, category: str = "business_fact",
    _user_id: int | None = None, **_kwargs,
) -> dict:
    """Raises ValueError (never returns a "failed"-shaped dict) for every
    outcome that did NOT actually write — cap_reached, not_found,
    ambiguous, bad input. ai_chat_service.confirm_action's existing
    `except ValueError` path is what keeps msg.executed False and skips
    the "בוצע: ..." confirmation message on these outcomes (same contract
    register_office_client relies on) — a status dict would instead have
    been silently treated as success (msg.executed=True, a fake "בוצע"
    row persisted into the next 30 turns of model input), which would
    let the model believe a capped/ambiguous write actually happened and
    never prompt the user to consolidate. "ok" and "already_known" are
    the only pass-through (real or no-op-but-honest) successes."""
    from . import moshko_memory

    target_user_id = _user_id if scope == "user" else None

    if action == "add":
        if not content:
            raise ValueError("content נדרש לפעולת add")
        result = moshko_memory.remember(
            db, org_id, content=content, scope=scope, user_id=target_user_id,
            category=category, source="conversation",
        )
    elif action == "update":
        if not match or not content:
            raise ValueError("match ו-content נדרשים לפעולת update")
        result = moshko_memory.update_memory(
            db, org_id, match=match, content=content, user_id=target_user_id,
        )
    elif action == "forget":
        if not match:
            raise ValueError("match נדרש לפעולת forget")
        result = moshko_memory.forget(db, org_id, match=match, user_id=target_user_id)
    else:
        raise ValueError(f"action לא מוכר: {action}")

    if result["status"] == "ambiguous":
        candidates = "; ".join(c["content"] for c in result["candidates"])
        raise ValueError(f"{result['message']} מועמדים: {candidates}")
    if result["status"] in ("cap_reached", "not_found", "failed"):
        raise ValueError(result["message"])
    return result


async def _search_history(db, org_id: int, *, query: str, _user_id: int | None = None, **_kwargs) -> dict:
    from ..models import ChatMessage

    query = (query or "").strip()
    if not query:
        return {"results": []}

    rows = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.organization_id == org_id,
            ChatMessage.user_id == _user_id,
            ChatMessage.content.ilike(f"%{query}%"),
            # Same rule as ai_chat_service._history: an unconfirmed proposal
            # never happened — it must not surface here as if it were real
            # history (a search for "תייק את הוצאה 42" must not let Moshko
            # conclude the filing occurred just because it was PROPOSED).
            # The separate "בוצע: ..." confirmation message still matches
            # normally, so real executions stay findable.
            ChatMessage.pending_action.is_(None),
        )
        .order_by(ChatMessage.id.desc())
        .limit(20)
        .all()
    )
    return {
        "results": [
            {
                "date": r.created_at.isoformat() if r.created_at else None,
                "role": r.role,
                "excerpt": r.content[:280],
            }
            for r in rows
        ],
    }


# Moshko Stage 3 — tasks use the existing Task table. create/update are
# registered as writes below, so the chat loop persists a pending_action and
# never reaches these wrappers until the user explicitly confirms.
async def _create_task(
    db, org_id: int, *, title: str, description: str | None = None,
    due_date: str | None = None, entity_type: str | None = None,
    entity_id: int | None = None, alert_id: int | None = None, **_kwargs,
) -> dict:
    from . import moshko_tasks
    return moshko_tasks.create_task(
        db, org_id, title=title, description=description, due_date=due_date,
        entity_type=entity_type, entity_id=entity_id, alert_id=alert_id,
    )


async def _list_tasks(
    db, org_id: int, *, status: str | None = None,
    due_from: str | None = None, due_to: str | None = None,
    limit: int = 100, **_kwargs,
) -> dict:
    from . import moshko_tasks
    return moshko_tasks.list_tasks(
        db, org_id, status=status, due_from=due_from, due_to=due_to, limit=limit,
    )


async def _update_task(
    db, org_id: int, *, task_id: int, status: str | None = None,
    due_date: str | None = None, clear_due_date: bool = False, **_kwargs,
) -> dict:
    from . import moshko_tasks
    return moshko_tasks.update_task(
        db, org_id, task_id=task_id, status=status, due_date=due_date,
        clear_due_date=clear_due_date,
    )


TOOLS: dict[str, ChatTool] = {
    "find_capability": ChatTool(
        name="find_capability",
        description=(
            "חיפוש יכולות של SUMIT ו-Open Finance שמשרתות משימה נתונה. "
            "השתמש בזה כשמבקשים ממך משהו שאין לו כלי ייעודי ברשימה, כדי "
            "לבדוק אם היכולת בכל זאת קיימת במערכות. מחזיר יכולות מקבילות "
            "משתי המערכות יחד. זהו כלי גילוי — הוא אינו מפעיל דבר; תוצאה "
            "עם requires_approval תדרוש אישור בעלים כדי לפעול בפועל."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "המשימה או המונח לחיפוש (למשל: expense, transactions, customer)"},
                "reads_only": {"type": "boolean", "description": "להחזיר יכולות קוראות בלבד", "default": False},
            },
            "required": ["task"],
        },
        category="read",
        fn=_find_capability,
    ),
    "office_account_status": ChatTool(
        name="office_account_status",
        description=(
            "מכסות ומצב חשבון המשרד ב-SUMIT — כמה רישיונות הנה\"ח בשימוש, "
            "מצב אובליגו, מיילים ואחסון. השתמש בזה כשנשאל אם תיק מסוים "
            "מחויב, או אם יש חסימת אובליגו. מחזיר תמונה של הפורטל כולו."
        ),
        input_schema={"type": "object", "properties": {}},
        category="read",
        office=True,
        fn=_office_account_status,
    ),
    "office_capabilities": ChatTool(
        name="office_capabilities",
        description=(
            "מה אני יכול לבצע ברמת המשרד ומה חסום. כולל ציון מפורש של מה "
            "ש-SUMIT לא חושפת בשום הרשאה (קריאת מנות ופקודות יומן)."
        ),
        input_schema={"type": "object", "properties": {}},
        category="read",
        office=True,
        fn=_office_capabilities,
    ),
    "suggest_expense_accounts": ChatTool(
        name="suggest_expense_accounts",
        description=(
            "הצעת כרטיסים לתיוק הוצאה, מתוך אינדקס החשבונות של התיק "
            "(למשל 1,004 כרטיסי חשבשבת שיובאו). השתמש בזה לפני תיוק — "
            "רשימה ריקה משמעה שאין התאמה, ואז אין לתייק בניחוש."
        ),
        input_schema={
            "type": "object",
            "properties": {"expense_id": {"type": "integer", "description": "מזהה ההוצאה"}},
            "required": ["expense_id"],
        },
        category="read",
        fn=_suggest_expense_accounts,
    ),
    "file_expense_to_account": ChatTool(
        name="file_expense_to_account",
        description=(
            "תיוק הוצאה לכרטיס באינדקס החשבונות. זה מה שמחבר הוצאה "
            "שנקלטה מהעסק לספרים. תיוק חוזר מעביר לכרטיס אחר — תיקון "
            "תיוק שגוי מותר. כרטיס של ארגון אחר נחסם."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "expense_id": {"type": "integer"},
                "account_id": {"type": "integer", "description": "מזהה הכרטיס מ-suggest_expense_accounts"},
            },
            "required": ["expense_id", "account_id"],
        },
        category="write",
        policy_action="expenses.file",
        fn=_file_expense_to_account,
    ),
    "list_my_capabilities": ChatTool(
        name="list_my_capabilities",
        description=(
            "מה אני יכול לבצע בתיק הזה ומה חסום ולמה. השתמש בזה כשנשאל "
            "'מה אתה יכול לעשות' או כשמשימה נראית בלתי-אפשרית — התשובה "
            "תהיה 'היכולת קיימת אבל חסר חיבור X' ולא 'אין לי יכולת כזו'."
        ),
        input_schema={"type": "object", "properties": {}},
        category="read",
        fn=_list_my_capabilities,
    ),
    "get_ar_aging": ChatTool(
        name="get_ar_aging",
        description="קבלת דוח גיול חובות לקוחות (aging) — יתרות פתוחות לפי טווחי איחור.",
        input_schema={"type": "object", "properties": {}},
        category="read",
        fn=_get_ar_aging,
    ),
    "get_ap_aging": ChatTool(
        name="get_ap_aging",
        description=(
            "דוח גיול חובות לספקים (AP aging) — יתרות פתוחות לפי טווחי "
            "איחור, עם דגל bank_movement_seen פר-חשבון: True = יש תנועת "
            "בנק תואמת (כנראה עיכוב סנכרון, הכסף כבר יצא); False = אין "
            "שום תנועת בנק — סיכון אמיתי שדורש תשומת לב."
        ),
        input_schema={"type": "object", "properties": {}},
        category="read",
        fn=_get_ap_aging,
    ),
    "set_vehicle_profile": ChatTool(
        name="set_vehicle_profile",
        description=(
            "יצירה/עדכון פרופיל רכב (עיקר-שימוש עסקי/פרטי) — קובע ניכוי "
            "מע\"מ תשומות רכב. השתמש בו רק אחרי שהמשתמש אמר במפורש את "
            "עיקר השימוש; אל תמלא primarily_business מברירת מחדל או "
            "מניחוש. פעולת כתיבה — דורשת אישור מפורש."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "כינוי/מספר רישוי לזיהוי הרכב"},
                "vehicle_kind": {
                    "type": "string",
                    "enum": ["private", "commercial", "taxi", "rental",
                             "driving_school", "dealer_stock"],
                },
                "primarily_business": {
                    "type": ["boolean", "null"],
                    "description": "רק אם המשתמש אמר במפורש — אחרת השאר null",
                },
                "attached_to_employee_with_use_value": {"type": "boolean"},
            },
            "required": ["label", "vehicle_kind"],
        },
        category="write",
        policy_action="expenses.manage_vehicle_profile",
        fn=_set_vehicle_profile,
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
        description=(
            "דוח רווח והפסד — מבוסס ledger חי (Invoice/Bill/Expense בנטו), "
            "לא הערכה. מחזיר סכום מצטבר אחד עבור כל התקופה שנבחרה (revenue/"
            "cost_of_goods_sold/operating_expenses/net_income וכו'), ו-"
            "source='ledger'. זהו סיכום לתקופה כולה — אין כאן פירוט חודש-"
            "בחודש; לשאלה 'כמה הרווחתי בכל חודש בנפרד' אין לענות ממספר "
            "מצטבר זה."
        ),
        input_schema={
            "type": "object",
            "properties": {"months": {"type": "integer", "description": "אורך התקופה אחורה מהיום, בחודשים", "default": 6}},
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
        policy_action="invoices.issue",
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
        policy_action="collections.contact",
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
    "get_trial_balance": ChatTool(
        name="get_trial_balance",
        description=(
            "מאזן בוחן — סך חובה מול זכות פר כרטיס, מחושב מהספרים של רצף. "
            "מחזיר `is_final`: מאזן שאינו מאוזן או שיש מנות פתוחות אינו "
            "סופי ואין לדווח לפיו."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "start": {"type": "string", "description": "תאריך התחלה YYYY-MM-DD"},
                "end": {"type": "string", "description": "תאריך סיום YYYY-MM-DD"},
            },
        },
        category="read",
        fn=_get_trial_balance,
    ),
    "get_open_batches": ChatTool(
        name="get_open_batches",
        description=(
            "מנות פתוחות בספרים. SUMIT אינה חושפת קריאת מנות ב-API — "
            "הכלי מחזיר זאת במפורש ומפנה למסך בפורטל, במקום להעמיד פנים "
            "שאין מנות פתוחות."
        ),
        input_schema={"type": "object", "properties": {}},
        category="read",
        fn=_get_open_batches,
    ),
    "propose_books_batch": ChatTool(
        name="propose_books_batch",
        description=(
            "הצעת יצירת מנה בספרים (רישום בלתי-הפיך). אינו מבצע — יוצר "
            "הצעה שדורשת אישור בעלים מפורש."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "תיאור המנה"},
            },
            "required": ["description"],
        },
        category="write",
        fn=_propose_books_batch,
        # רישום לספרים הוא writeback חשבונאי — אותה משפחת הרשאות של
        # כל כתיבה חוזרת למערכת ההנה"ח, ולא פעולת חתימה נפרדת: ההצעה
        # עצמה אינה מבצעת דבר. הביצוע עובר בחוזה הפעולות הבלתי-הפיכות.
        policy_action="accounting.writeback.propose",
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
        policy_action="payment_link.create",
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
        policy_action="bank_payment.propose",
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
        policy_action="bank_connection.create",
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
        policy_action="expenses.manage_categories",
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
        policy_action="expenses.review",
        fn=_set_expense_category,
    ),
    "get_learned_rules": ChatTool(
        name="get_learned_rules",
        description=(
            "מה מושקו למד על סיווג הוצאות מתיקוני משתמש קודמים בצ'אט/במסך "
            "הוצאות — לכל כלל: ספק, קטגוריה, וכמה תיקונים ביססו אותו (סף: 3 "
            "תיקונים לאותו ספק). מציג גם ספקים שעדיין מתחת לסף, כדי לראות "
            "מה עוד לא הפך לכלל בפועל. קריאה בלבד."
        ),
        input_schema={"type": "object", "properties": {}},
        category="read",
        fn=_get_learned_rules,
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
        policy_action="expenses.classify",
        fn=_classify_pending_expenses,
    ),
    "file_expense": ChatTool(
        name="file_expense",
        description=(
            "תיוק הוצאה בפועל ב-SUMIT (קריאת addexpense אמיתית) — הופך "
            "טיוטה שנקלטה (מהצ'אט/מהבנק/מ-SUMIT) להוצאה מתויקת בספרים, "
            "כולל שער הכפילויות הקיים. פעולת כתיבה — דורשת אישור מפורש; "
            "בלתי-הפיכה (יוצרת מסמך אמיתי ב-SUMIT)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "expense_id": {"type": "integer", "description": "מזהה ההוצאה לתיוק"},
            },
            "required": ["expense_id"],
        },
        category="write",
        policy_action="expenses.file",
        fn=_file_expense,
    ),
    "get_expense_intake_status": ChatTool(
        name="get_expense_intake_status",
        description=(
            "סטטוס קליטת קבלות דרך הצ'אט: כמה נקלטו היום מול התקרה היומית, "
            "וכמה הוצאות (טיוטות) ממתינות לתיוק. קריאה בלבד."
        ),
        input_schema={"type": "object", "properties": {}},
        category="read",
        fn=_get_expense_intake_status,
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
    "get_bank_reconciliation": ChatTool(
        name="get_bank_reconciliation",
        description=(
            "מצב ההתאמות בין תנועות הבנק למסמכי ההנה\"ח: כמה הותאמו, כמה "
            "לא, ודוגמאות משני הצדדים. קריאה בלבד — אינו שומר התאמות."
        ),
        input_schema={"type": "object", "properties": {}},
        # "read" ולא "write" — הכלי מריץ את מנוע ההתאמות עם persist=False
        # ואינו משנה שום שורה. שאלה בצ'אט לא מבצעת התאמות.
        category="read",
        fn=_get_bank_reconciliation,
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
    "get_credit_line_status": ChatTool(
        name="get_credit_line_status",
        description=(
            "מסגרת אשראי בנקאית — האם/מתי צפויה חריגה או התקרבות (עד 10%) "
            "למסגרת האשראי הידועה, לפי הליכת יתרה יומית קדימה. עונה ישירות "
            "'מתי צפוי מינוס' (breach_date/warning_date) ו-min_headroom "
            "(המרווח המינימלי הצפוי). status='unknown' כשלא ידועה מסגרת "
            "אשראי לאף חשבון בנק."
        ),
        input_schema={
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "טווח ימים קדימה", "default": 30}},
        },
        category="read",
        fn=_get_credit_line_status,
    ),
    "get_ar_health": ChatTool(
        name="get_ar_health",
        description=(
            "בריאות גבייה — מגמת DSO אמיתית (ממוצע ימי-תשלום בפועל, לא "
            "יעד) לאורך מספר חודשים, וסיכומי סיכון/גבייה מדוח הגיול "
            "(total_receivables, risk_summary, collection_summary). לפירוט "
            "לקוח-לקוח יש להשתמש ב-get_ar_aging."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "months": {"type": "integer", "description": "טווח חודשים למגמת DSO", "default": 12},
                "target_dso": {"type": "integer", "description": "יעד DSO להשוואה", "default": 30},
            },
        },
        category="read",
        fn=_get_ar_health,
    ),
    "get_cfo_insights": ChatTool(
        name="get_cfo_insights",
        description=(
            "תובנות CFO קיימות (persisted) — התרעות/המלצות שכבר נוצרו על "
            "ידי מנוע הניתוח (חיבורים, התאמות, גבייה, תזרים, ספקים, "
            "רווחיות, סגירת חודש, תקציב). קריאה בלבד — אינו מריץ ניתוח כבד "
            "מחדש."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["active", "acknowledged", "resolved"], "default": "active"},
                "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
                "limit": {"type": "integer", "default": 20},
            },
        },
        category="read",
        fn=_get_cfo_insights,
    ),
    "get_daily_brief": ChatTool(
        name="get_daily_brief",
        description=(
            "בריף הבוקר של היום בעברית (טקסט טהור, subject+text) — אדומים "
            "שדורשים טיפול היום, מזומן, תורים, וחייבים מובילים. מבוסס "
            "נתונים שכבר קיימים (DailySnapshot/CfoInsight) — אינו מריץ "
            "מחזור-בוקר חדש."
        ),
        input_schema={"type": "object", "properties": {}},
        category="read",
        fn=_get_daily_brief,
    ),
    "get_tax_estimate": ChatTool(
        name="get_tax_estimate",
        description=(
            "אומדן גס של מקדמת מס (הכנסה) לחודש — לא חישוב מחייב ולא ייעוץ "
            "מס. מחזיר תמיד method (הנוסחה) ו-caveat (הסתייגות מפורשת) "
            "ו-confidence='low'."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "year": {"type": "integer", "description": "ברירת מחדל: השנה הנוכחית"},
                "month": {"type": "integer", "description": "ברירת מחדל: החודש הנוכחי"},
            },
        },
        category="read",
        fn=_get_tax_estimate,
    ),
    "verify_filing": ChatTool(
        name="verify_filing",
        description=(
            "אימות משולש (3 בדיקות בלתי-תלויות: תיאום מול PCN874, חישוב "
            "עצמאי ובדיקות שפיות, שלמות קליטה והצלבה חיצונית) של דיווח "
            "המע\"מ לתקופה — קריאה בלבד. יש להריץ ולבדוק pass/warn/fail "
            "לפני כל שידור בפועל לרשות."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "year": {"type": "integer"},
                "month": {"type": "integer"},
                "months": {"type": "integer", "description": "אורך התקופה בחודשים", "default": 1},
                "basis": {"type": "string", "enum": ["document", "captured"], "default": "document"},
            },
            "required": ["year", "month"],
        },
        category="read",
        fn=_verify_filing,
    ),
    "email_report": ChatTool(
        name="email_report",
        description=(
            "שליחת דוח כספי (רווח והפסד / מאזן / תזרים חזוי) כקובץ Excel "
            "מצורף במייל. פעולת כתיבה — דורשת אישור מפורש של המשתמש לפני "
            "שליחה בפועל. "
            "אבטחת נמען — חובה: recipient_email מותר להיות אך ורק כתובת "
            "שהמשתמש הקליד במפורש בשיחה הנוכחית, או כתובת של איש קשר קיים "
            "של הארגון (יש לאתר אותו קודם עם search_contacts/get_ledger_card "
            "אם לא ידוע בוודאות) — לעולם אין להמציא או לנחש כתובת מייל."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "report_type": {
                    "type": "string",
                    "enum": ["profit_loss", "balance_sheet", "cash_flow"],
                },
                "recipient_email": {
                    "type": "string",
                    "description": "כתובת שהמשתמש כתב במפורש, או מייל של איש קשר קיים",
                },
                "period_months": {
                    "type": "integer",
                    "description": "P&L: חודשים אחורה (ברירת מחדל 6). תזרים: חודשי חיזוי קדימה (ברירת מחדל 12).",
                },
                "year": {"type": "integer", "description": "מאזן: שנה ל'נכון ל-תאריך' (ברירת מחדל: היום)"},
                "month": {"type": "integer", "description": "מאזן: חודש ל'נכון ל-תאריך' (ברירת מחדל: היום)"},
                "note": {"type": "string", "description": "טקסט חופשי אופציונלי לגוף המייל"},
            },
            "required": ["report_type", "recipient_email"],
        },
        category="write",
        policy_action="reports.email",
        fn=_email_report,
    ),
    "propose_vat_filing_approval": ChatTool(
        name="propose_vat_filing_approval",
        description=(
            "רישום אישור בעלים למספרי דיווח מע\"מ לתקופה, אחרי אימות משולש "
            "חובה (verify_filing). אם האימות נכשל (fail) — הבקשה נחסמת ולא "
            "נוצרת. פעולת כתיבה בלתי-הפיכה — דורשת אישור מפורש של המשתמש. "
            "חשוב: לרצף אין מנגנון שידור לרשות המסים. פעולה זו רק מתעדת את "
            "אישור הבעלים למספרים; השידור בפועל לרשות נעשה ידנית בממשק "
            "SUMIT, לא על ידי רצף."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "year": {"type": "integer"},
                "month": {"type": "integer"},
                "months": {"type": "integer", "description": "אורך התקופה בחודשים", "default": 1},
                "basis": {"type": "string", "enum": ["document", "captured"], "default": "document"},
            },
            "required": ["year", "month"],
        },
        category="write",
        policy_action="filing.prepare",
        fn=_propose_vat_filing_approval,
        needs_user=True,
    ),
    "list_pending_approvals": ChatTool(
        name="list_pending_approvals",
        description="רשימת בקשות אישור פעולה בלתי-הפיכה הממתינות לאישור הבעלים בארגון (סטטוס proposed).",
        input_schema={"type": "object", "properties": {}},
        category="read",
        fn=_list_pending_approvals,
    ),
    "kb_lookup": ChatTool(
        name="kb_lookup",
        description=(
            "מרכז ידע חשבונאי/מיסויי: דיני הכרה בהוצאות (מס הכנסה), ניכוי מס "
            "תשומות (מע\"מ), גשר סיווגים, ונהלי SUMIT (פורטל, הכנסות/הוצאות, "
            "חיוב וגבייה, אינטגרציה). חפשו כאן לפני שעונים על שאלת דין/נוהל — "
            "אל תנחשו כלל מס או צעד ב-SUMIT. honest-null (available=False + "
            "סיבה) אם ה-KB אינו ארוז בסביבה הנוכחית — לא רשימה ריקה שקטה."
        ),
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "מונח/שאלה לחיפוש במרכז הידע"}},
            "required": ["query"],
        },
        category="read",
        fn=_kb_lookup,
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
    "memory": ChatTool(
        name="memory",
        description=(
            "זיכרון לומד: הוספה/עדכון/מחיקה של עובדה אחת. scope='org' לעובדה "
            "על העסק (גלויה לכל הארגון), scope='user' לזיכרון אישי (גלוי רק "
            "למשתמש הנוכחי). ראו הנחיית הזיכרון המלאה בהוראות המערכת. "
            "פעולת כתיבה — דורשת אישור מפורש."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "update", "forget"]},
                "content": {"type": "string", "description": "עובדה הצהרתית אחת (נדרש ל-add/update)"},
                "scope": {"type": "string", "enum": ["org", "user"], "default": "org"},
                "match": {"type": "string", "description": "תת-מחרוזת לזיהוי הזיכרון הקיים (נדרש ל-update/forget)"},
                "category": {
                    "type": "string",
                    "enum": ["preference", "business_fact", "correction", "convention"],
                    "default": "business_fact",
                },
            },
            "required": ["action"],
        },
        category="write",
        policy_action="moshko.memory.write",
        fn=_memory,
        needs_user=True,
    ),
    "create_task": ChatTool(
        name="create_task",
        description=(
            "יצירת משימת מעקב חדשה בטבלת המשימות של הארגון. תאריך היעד יכול "
            "להיות ISO או ניסוח ישראלי מפורש כמו 'מחר' או 'ב-15'. אם המשימה "
            "נובעת מהתראה קיימת, יש להעביר alert_id כדי לשמר את הקישור. "
            "פעולת כתיבה — דורשת אישור מפורש לפני יצירה."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "כותרת קצרה ומעשית"},
                "description": {"type": "string"},
                "due_date": {
                    "type": "string",
                    "description": "היום, מחר, ב-15, YYYY-MM-DD או DD/MM/YYYY",
                },
                "entity_type": {"type": "string"},
                "entity_id": {"type": "integer"},
                "alert_id": {"type": "integer"},
            },
            "required": ["title"],
        },
        category="write",
        policy_action="tasks.write",
        fn=_create_task,
    ),
    "list_tasks": ChatTool(
        name="list_tasks",
        description=(
            "רשימת משימות הארגון מתוך טבלת Task הקיימת, עם סינון לפי סטטוס "
            "וטווח תאריך יעד. קריאה בלבד ומבודדת לארגון הנוכחי."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["open", "in_progress", "done"]},
                "due_from": {"type": "string", "description": "תחילת טווח תאריך יעד"},
                "due_to": {"type": "string", "description": "סוף טווח תאריך יעד"},
                "limit": {"type": "integer", "default": 100},
            },
        },
        category="read",
        fn=_list_tasks,
    ),
    "update_task": ChatTool(
        name="update_task",
        description=(
            "עדכון סטטוס או תאריך יעד של משימה קיימת בארגון. אפשר להסיר תאריך "
            "יעד עם clear_due_date=true. פעולת כתיבה — דורשת אישור מפורש."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "status": {"type": "string", "enum": ["open", "in_progress", "done"]},
                "due_date": {"type": "string"},
                "clear_due_date": {"type": "boolean", "default": False},
            },
            "required": ["task_id"],
        },
        category="write",
        policy_action="tasks.write",
        fn=_update_task,
    ),
    "search_history": ChatTool(
        name="search_history",
        description=(
            "חיפוש טקסט חופשי בהיסטוריית השיחות הישנות שלך עם מושקו (מעבר "
            "ל-30 ההודעות האחרונות שתמיד נטענות) — עד 20 תוצאות אחרונות "
            "תואמות, עם תאריך ותפקיד. משלים את תקרת ההיסטוריה: השתמש בו "
            "לפני שאתה אומר שאין לך מידע על שיחה קודמת."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "מונח חיפוש חופשי"},
            },
            "required": ["query"],
        },
        category="read",
        fn=_search_history,
        needs_user=True,
    ),
}


# Explicit target classification, reviewed against each wrapper above. Most
# tools query or mutate Rezef's normalized DB. Only wrappers that actually
# cross a provider boundary are classified as provider calls; bank queries
# over already-normalized BankTransaction rows remain rezef_db. Knowledge and
# SMTP helpers are local because the reporting taxonomy intentionally has only
# sumit/open_finance/rezef_db/local.
_SUMIT_TOOLS = {"issue_document", "create_payment_link", "file_expense"}
_OPEN_FINANCE_TOOLS = {"create_bank_payment_request", "connect_bank_account"}
_LOCAL_TOOLS = {"rezef_help", "kb_lookup", "email_report"}
_REZEF_DB_TOOLS = set(TOOLS) - _SUMIT_TOOLS - _OPEN_FINANCE_TOOLS - _LOCAL_TOOLS


def tool_target_system(
    tool_name: str,
    *,
    arguments: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> str:
    """Return the implementation-backed system actually targeted by a call.

    Two wrappers are data-dependent: issue_document can explicitly create a
    local draft (send_to_sumit=false), and run_client_sync reports the source
    selected by the existing connector resolver.
    """
    if tool_name not in TOOLS:
        raise KeyError(f"Unknown Moshko tool: {tool_name}")
    if tool_name == "issue_document" and (arguments or {}).get("send_to_sumit") is False:
        return "rezef_db"
    if tool_name == "run_client_sync":
        source = (result or {}).get("source")
        if source in {"sumit", "open_finance"}:
            return source
        return "local"  # connector orchestration; exact source unavailable on failure
    if tool_name in _SUMIT_TOOLS:
        return "sumit"
    if tool_name in _OPEN_FINANCE_TOOLS:
        return "open_finance"
    if tool_name in _LOCAL_TOOLS:
        return "local"
    if tool_name in _REZEF_DB_TOOLS:
        return "rezef_db"
    # Tests and extensions may inject an ephemeral ChatTool after module
    # initialization. It has no reviewed provider boundary, so classify that
    # synthetic call as local. Every built-in tool is still covered by the
    # explicit sets above and by the mapping contract test.
    return "local"


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
