"""Rezef in-app chatbot knowledge base ("How do I...?" / "What can Rezef do?").

Design goal: the bot must be able to answer ANY "how do I / what can Rezef
do / where is X" question about the system, in Hebrew, accurately —
WITHOUT paying the token cost of stuffing all of this into every request's
system prompt. So this module is a dict of topic -> Hebrew markdown
section, exposed to the model through a single on-demand read tool
(`rezef_help` in ai_chat_tools.py) instead of being embedded in
SYSTEM_PROMPT.

Honesty contract (this module is versioned code, reviewers will diff it
against reality): every capability line here corresponds to a route/
service verified against the actual code, not an aspiration. Partial
capabilities are marked "חלקי" with the concrete reason; capabilities that
don't exist yet are marked "בהמשך". Sources used to derive this content:
- frontend/src/App.tsx (navigationConfig + <Routes>) for the screen list
- src/cfo/api/routes/*.py + src/cfo/api/__init__.py for real endpoints
- docs/PRODUCT_AUDIT_AND_ROADMAP.md + SUMIT_MODULE_COVERAGE.md +
  docs/superpowers/plans/2026-07-04-account-transaction-decision-dossier.md
  for capability status (what's real/derived/frozen/gated)

The `test_rezef_kb.py` suite parametrizes over every `api_path` cited in
SCREENS and asserts it exists in the live FastAPI route table — this is
what keeps the overview section honest as the app evolves.
"""
from __future__ import annotations

from typing import NamedTuple, Optional


class ScreenEntry(NamedTuple):
    path: str                    # frontend SPA route (what the user navigates to)
    label: str                   # Hebrew display label (matches sidebar where possible)
    summary: str                 # one Hebrew line: what it does + honesty flag if partial
    api_path: Optional[str]      # ONE real backing FastAPI GET endpoint that screen
                                  # calls on load, verified against the live route
                                  # table; None if the screen has no working data
                                  # fetch of its own (static/stub/entry-form screens).


# Every path here was verified (2026-07) against frontend/src/App.tsx and the
# component's actual api.get() call, then cross-checked against the live
# FastAPI route table (`{r.path for r in app.routes}`). See the module
# docstring — do not add a screen line without doing the same.
SCREENS: tuple[ScreenEntry, ...] = (
    # --- CFO ---
    ScreenEntry("/", "מרכז הפיקוד (Command Center)",
                "תמונת מצב כללית של העסק — עיקרי הנתונים הפיננסיים במבט אחד.",
                "/api/dashboard/overview"),
    ScreenEntry("/ai-chat", "עוזר AI",
                "שיחה בעברית עם עוזר ה-CFO — עונה רק על סמך נתונים אמיתיים; "
                "פעולות כתיבה דורשות אישור מפורש (ר' נושא `bot`).",
                "/api/ai/chat/{session_id}"),
    ScreenEntry("/executive", "דשבורד מנהלים",
                "8 פאנלים של מצב העסק (הכנסות/הוצאות/תזרים/KPI).",
                "/api/dashboard/executive"),
    ScreenEntry("/cashflow", "Cash Flow",
                "תחזית תזרים שבועית עם תרחישים (בסיס/אופטימי/שמרני).",
                "/api/dashboard/cashflow"),
    ScreenEntry("/cashflow-detail", "תזרים — מפורט",
                "תזרים חודשי/יומי, burn-rate ויחסי נזילות. **חלקי** — מבוסס "
                "טבלת תנועות ישנה שכבר לא גדלה מסנכרון חי; למספר עדכני "
                "העדיפו /ar, /ap ואת נושא `reports`.",
                "/api/cashflow/monthly"),
    ScreenEntry("/ar", "AR / גבייה",
                "גיול חובות לקוחות אמיתי (0-30/31-60/61-90/91-120/120+), DSO וניקוד אשראי.",
                "/api/ar/aging"),
    ScreenEntry("/ap", "AP / ספקים",
                "גיול חשבונות ספקים לתשלום, נגזר מהמסמכים בפועל.",
                "/api/daily-reports/ap-aging"),
    ScreenEntry("/budget", "Budget",
                "תקציב מול בפועל. **חלקי** — טור ה\"בפועל\" מבוסס אותה טבלת "
                "תנועות קפואה כמו /cashflow-detail.",
                "/api/financial/budget/vs-actual"),
    ScreenEntry("/budget-entry", "הזנת תקציב",
                "הזנה ידנית של תקציב או ייבוא מ-Excel; מסך הזנה בלבד, לא טוען נתון בפתיחה.",
                None),
    ScreenEntry("/year-comparison", "השוואה שנתית",
                "השוואת ביצועים מול אותה תקופה אשתקד.",
                "/api/reports/year-comparison"),
    # --- Operations ---
    ScreenEntry("/invoices", "Invoices",
                "הפקה וניהול חשבוניות ללקוחות, כולל שליחה אמיתית ל-SUMIT.",
                "/api/financial/invoices"),
    ScreenEntry("/documents", "הוצאת מסמכים",
                "חשבונית/הצעת מחיר/הזמנה/תעודת משלוח/זיכוי — נכתב בפועל מול SUMIT.",
                "/api/financial/documents"),
    ScreenEntry("/payment-requests", "Payment Requests",
                "בקשות תשלום והוראות קבע ללקוחות.",
                "/api/financial/payments/requests"),
    ScreenEntry("/agreements", "Agreements",
                "חוזים/הסכמים והתזרים הנגזר מהם — persist ב-DB (לא ב-memory).",
                "/api/financial/agreements"),
    ScreenEntry("/expenses", "תיוק הוצאות",
                "קליטה, OCR, סיווג ותיוק הוצאות ב-SUMIT — ר' נושא `expenses`.",
                "/api/expenses"),
    ScreenEntry("/payments", "Payments",
                "עיבוד תשלומים: סליקה, אמצעי תשלום, הוראות קבע מול SUMIT/Open Finance.",
                "/api/payments/"),
    ScreenEntry("/masav", "תשלומי ספקים (מס\"ב)",
                "הפקת קובץ זיכויים מס\"ב (128 תווים) לבנק — ר' נושא `masav`.",
                "/api/masav/settings"),
    ScreenEntry("/inventory", "מלאי",
                "דוח מלאי קיים, מסונכרן מ-SUMIT.",
                "/api/inventory/report"),
    # --- Monitoring ---
    ScreenEntry("/alerts", "Alerts & Tasks",
                "התראות ומשימות פעולה (alert_engine + cfo_brain).",
                "/api/alerts"),
    ScreenEntry("/kpis", "KPIs",
                "מדדי ביצוע מרכזיים, עם מגמת-שינוי אמיתית לכל KPI מול "
                "התקופה הקודמת. **חלקי** — השוואת תקציב/תקופה הכוללת "
                "בסיכום המנהלים (`executive-summary`) היא honest-null "
                "כרגע (אין נתון-אמת אמין זמין, לא ממציאה מספר).",
                "/api/financial/kpis"),
    ScreenEntry("/reports", "Reports",
                "דוחות: רווח/הפסד (אמין, מבוסס-ledger). **חלקי** — המאזן במסך "
                "זה מעורב (assets/liabilities מטבלה קפואה); למאזן אמין ר' /ledger.",
                "/api/reports/profit-loss"),
    ScreenEntry("/bank-report", "דוח לבנק",
                "דוח מצב עסקי מוכן להגשה לבנק.",
                "/api/reports/bank-status"),
    ScreenEntry("/business-menu", "תפריט יכולות",
                "סילבוס מלא של כל מה שהמערכת עושה לעסק — עם סטטוס חי לכל יכולת.",
                "/api/business/menu"),
    ScreenEntry("/sumit-coverage", "כיסוי מודולי SUMIT",
                "מפת-מידע (מוכן/חלקי/חסום) על כיסוי ה-API של SUMIT — מסך "
                "תיעוד סטטי, לא קורא API בפועל.",
                None),
    ScreenEntry("/engine", "המנוע המאחד",
                "מרכז בקרה אחד: סטטוס הנה\"ח, סינתזה, אנומליות ודוחות.",
                "/api/engine/run"),
    ScreenEntry("/bank-insights", "תובנות בנק",
                "אנומליות, מנויים, עמלות וחיסכון מדפי הבנק — תלוי חיבור "
                "Open Finance פעיל (ר' נושא `integrations`).",
                "/api/open-finance/insights"),
    ScreenEntry("/office", "ניהול משרד",
                "תיקי לקוחות, רולאפ פיננסי חוצה-לקוחות וסנכרון — ר' נושא `office`.",
                "/api/office/clients"),
    ScreenEntry("/admin-clients", "אדמין — כל הלקוחות",
                "תצוגת-על אדמין של כל תיקי הלקוחות במערכת.",
                "/api/admin/control/clients"),
    ScreenEntry("/calculators", "מחשבונים",
                "חישובי שכר/מס/ביטוח-לאומי דטרמיניסטיים, ללא צ'אט/AI.",
                "/api/calculators"),
    ScreenEntry("/payroll", "שכר",
                "עובדים, תלושים ודוחות 102/126 (מבנה dict מובנה, לא קובץ XML רשמי).",
                "/api/payroll/employees"),
    ScreenEntry("/ledger", "הנה\"ח כפולה",
                "יומן מאוזן, כרטסת, מאזן בוחן ומאזן — נגזר מהמסמכים; ר' נושא `bookkeeping`.",
                "/api/ledger/trial-balance"),
    ScreenEntry("/daily-reports", "דוחות יומיים",
                "רווח/הפסד מצטבר, גיול חובות/ספקים ומע\"מ תוך-חודשי.",
                "/api/daily-reports/cumulative-pl"),
    ScreenEntry("/annual-reports", "דוחות שנתיים",
                "טיוטת 1301 (יחיד)/1214 (חברה) — לבדיקת רו\"ח, לא להגשה ישירה.",
                "/api/annual-reports/1214"),
    ScreenEntry("/of-ops", "Open Finance תפעול",
                "תשלומים, אשראי, לקוחות וסוחרים דרך Open Finance — תלוי consent+env.",
                "/api/open-finance/payments"),
    # --- Analysis ---
    ScreenEntry("/forecasting", "Forecasting",
                "תחזיות ML לתזרים/הכנסות. **חלקי** — אותה טבלת-תנועות קפואה כמו /cashflow-detail.",
                "/api/cashflow/forecast/revenue"),
    ScreenEntry("/ai-analytics", "AI Analytics",
                "תובנות AI. **חלקי** — לשונית אנומליות מבוססת נתון קפוא; "
                "תובנות/המלצות אחרות מסומנות `is_illustrative` כשרלוונטי.",
                "/api/financial/ai/anomalies"),
    # --- System ---
    ScreenEntry("/sync", "Data Sync",
                "הרצות סנכרון עם SUMIT/בנק ולוגים.",
                "/api/sync/runs"),
    ScreenEntry("/customers", "Customers",
                "ניהול לקוחות. **לא מחובר כרגע בפועל** — המסך לא טוען נתון "
                "אמיתי; לניהול לקוחות בפועל השתמשו ב-/ar, /documents או כלי "
                "הצ'אט `search_contacts`.",
                None),
    ScreenEntry("/bank", "Bank Import",
                "ייבוא דפי בנק וזיהוי דפוסי הוצאה.",
                "/api/sync/bank/parse"),
    ScreenEntry("/settings", "Settings",
                "הגדרות מערכת: פרטי ארגון וסטטוס חיבורי SUMIT/Open Finance.",
                "/api/admin/auth/me"),
)


def _render_overview() -> str:
    lines = [
        "## סקירת המערכת והמסכים",
        "",
        "כ-40 מסכים בתפריט הצד, מאורגנים ב-5 קבוצות (CFO / תפעול / ניטור / "
        "ניתוח / מערכת). שורה אחת לכל מסך — נתיב, מה הוא עושה, ודגל חלקיות "
        "היכן שרלוונטי:",
        "",
    ]
    for s in SCREENS:
        lines.append(f"- **{s.path}** — {s.label}: {s.summary}")
    return "\n".join(lines)


def _expenses_section() -> str:
    return (
        "## תהליך הוצאות: קליטה, OCR, כרטיסים מותאמים, סיווג, תיוק\n\n"
        "מסך `/expenses` (ExpenseFiling). זרימת עבודה טיפוסית:\n\n"
        "1. **קליטה** — ידנית (`POST /api/expenses`) או משיכה אוטומטית של "
        "טיוטות הוצאה מ-SUMIT (`POST /api/expenses/sync-pending`, וגם "
        "בקרון תקופתי `GET /api/cron/enrich-expenses`).\n"
        "2. **OCR** — `ExpenseOCRPipeline`: משיכת צילום הקבלה (getpdf) → "
        "חילוץ בראייה של מודל-שפה (ספק/ח.פ/סכום/מע\"מ/תאריך) → אימות ח.פ "
        "מול רשם החברות (מתקן שם ספק שגוי מ-OCR) → סיווג → עדכון. בודד: "
        "`POST /api/expenses/{expense_id}/ocr` (עם `auto_file=true` לתיוק "
        "אוטומטי אם אומת). גורף: `POST /api/expenses/ocr-pending`. עיקרון "
        "מנחה: מתייקים אוטומטית רק כשח.פ+שם ספק+סכום חולצו בביטחון — מה "
        "שלא קריא מסומן לבדיקה ולא מתויק בכוח.\n"
        "3. **כרטיסים מותאמים (קטגוריות)** — קטגוריות מובנות + כרטיסי הוצאה "
        "מותאמים אישית לארגון, עם מילות מפתח לסיווג אוטומטי: "
        "`GET/POST /api/expenses/categories`, מחיקה "
        "`DELETE /api/expenses/categories/{category_id}` (מסורבת 409 עם "
        "כמות אם עדיין בשימוש).\n"
        "4. **סיווג** — אוטומטי לפי מילות מפתח: `POST /api/expenses/classify` "
        "(בודד/הכל).\n"
        "5. **תיוק** — ל-SUMIT בפועל: בודד `POST /api/expenses/{expense_id}/file`, "
        "גורף `POST /api/expenses/file-all`. מוכנות דיווח מע\"מ: "
        "`GET /api/expenses/pcn874-readiness` — אילו הוצאות מתויקות חסרות "
        "ח.פ/מע\"מ.\n\n"
        "דרך הצ'אט (כלי read/write תואמים): `list_expenses`, "
        "`create_expense_category`, `set_expense_category`, "
        "`classify_pending_expenses`, `get_pcn874_readiness`."
    )


def _vat_section() -> str:
    return (
        "## מע\"מ ו-PCN874\n\n"
        "**מצב מע\"מ נוכחי** — מבוסס שדות מע\"מ אמיתיים מהמסמכים (לא אומדן "
        "net×18%): כלי צ'אט `get_vat_position`, ותוך-חודשי "
        "`GET /api/daily-reports/vat`.\n\n"
        "**הפקת PCN874** — `GET /api/daily-reports/pcn874?year=&month=` "
        "מייצר קובץ טקסט fixed-width (מבנה-אחיד: רשומות O/S1/L/X) מהמסמכים "
        "האמיתיים (חשבוניות=עסקאות, חשבונות/הוצאות מתויקות=תשומות). "
        "**מגבלה חשובה**: זו **טיוטה** בלבד — הקוד עצמו מסמן "
        "`draft=true` + disclaimer \"לאימות מול מפרט רשות המסים העדכני לפני "
        "הגשה\", כי מבנה-הרשומות (סדר שדות/היסטים) עלול להשתנות לפי גרסת "
        "מפרט. **השידור הרשמי לרשות המסים מתבצע רק דרך ממשק SUMIT עצמו** — "
        "אין ב-Rezef נתיב שמגיש את הדוח בפועל לרשות המסים.\n\n"
        "דוח מע\"מ תמציתי נוסף: `POST /api/financial/tax/vat-report` "
        "(`tax_service.generate_vat_report`)."
    )


def _bookkeeping_section() -> str:
    return (
        "## הנהלת חשבונות: יומן, כרטסת, מאזן בוחן, מאזן, יתרות פתיחה\n\n"
        "מסך `/ledger` (LedgerDashboard), מגובה ע\"י `ledger_service.py` — "
        "שכבת הנה\"ח כפולה **נגזרת דטרמיניסטית** מהמסמכים בפועל "
        "(Invoice/Bill/Expense/Payment), לא ספרים רשמיים חלופיים ל-SUMIT:\n\n"
        "- יומן מאוזן: `GET /api/ledger/journal`\n"
        "- מאזן בוחן: `GET /api/ledger/trial-balance`\n"
        "- כרטסת לקוח/ספק: `GET /api/ledger/contact/{contact_id}/card` "
        "(גם דרך כלי צ'אט `get_ledger_card`)\n"
        "- כרטיס חשבון בודד: `GET /api/ledger/account/{account_code}`\n"
        "- תרשים חשבונות: `GET /api/ledger/chart`\n"
        "- מאזן (derived): `GET /api/ledger/balance-sheet` — מסומן "
        "`derived: true` + disclaimer בתשובה עצמה; זהו המאזן **האמין**, "
        "מאוזן-בבנייה (Assets = Liabilities + Equity).\n"
        "- יתרות פתיחה: `GET/POST /api/ledger/opening-balances`\n\n"
        "**חשוב להבחין**: יש נתיב שני, נפרד, `/api/reports/balance-sheet` "
        "(מסך `/reports`) שמעורב חלקית מטבלאות ישנות (Account/Transaction) "
        "שאינן גדלות יותר מסנכרון חי — אל תשתמשו בו לדיווח אמיתי; "
        "`/ledger/balance-sheet` הוא מקור-האמת הנכון כרגע."
    )


def _reports_section() -> str:
    return (
        "## דוחות: P&L, תזרים, דוח בנק, דוחות יומיים, 1301/1214\n\n"
        "- **P&L** — `GET /api/dashboard/pnl` וגם `GET /api/reports/profit-loss` "
        "— שניהם מבוססי-ledger (אמין).\n"
        "- **תזרים** — תחזית שבועית עם תרחישים: `GET /api/dashboard/cashflow` "
        "(מסך `/cashflow`, אמין). מסך `/cashflow-detail` (חודשי/יומי/"
        "burn-rate/נזילות) **חלקי** — טבלת תנועות קפואה, לא גדלה מסנכרון חי.\n"
        "- **דוח לבנק** — `GET /api/reports/bank-status` (מסך `/bank-report`).\n"
        "- **דוחות יומיים תוך-חודשיים** — `/api/daily-reports/`: "
        "`cumulative-pl`, `ar-aging`, `ap-aging`, `vat`, `pcn874`, `suppliers` "
        "(מסך `/daily-reports`, כולם נגזרים ממסמכים אמיתיים).\n"
        "- **1301/1214** — `GET /api/annual-reports/1301` (יחיד) / "
        "`/1214` (חברה): **טיוטות בלבד** — לבדיקת רו\"ח, ללא התאמות מס "
        "(הוצאות לא מוכרות, פחת מואץ, הפסדים מועברים) וללא הגשה בפועל.\n"
        "- **דוח מאזן ב-`/reports`** — חלקי, ר' נושא `bookkeeping` להסבר "
        "ולחלופה האמינה.\n"
        "- **תקציב מול בפועל** (`/budget`) ו**תחזיות ML** (`/forecasting`) — "
        "חלקיים מאותה סיבה (טבלת תנועות קפואה)."
    )


def _collections_section() -> str:
    return (
        "## גבייה: תיקי גבייה, תזכורות, DSO\n\n"
        "**תיקי גבייה ידניים** (`CollectionCase`, מסך `/ar`): פתיחה אוטומטית "
        "לחשבוניות באיחור, מעקב סטטוס (open/promised/paid/escalated), רישום "
        "ניסיונות (ערוץ/תוצאה/הערות/תאריך-הבטחה). "
        "`GET /api/collections/cases`, `POST /api/collections/cases/{id}/attempt`, "
        "`POST /api/collections/cases/{id}/status`, "
        "`POST /api/collections/open` (פתיחה גורפת לפי איחור). דרך הצ'אט: "
        "`get_collection_cases`, `log_collection_attempt`.\n\n"
        "**תזכורות אוטומטיות** — cron יומי `GET /api/cron/collection-reminders`, "
        "ותצוגה/הרצה ידנית: `GET /api/financial/collection/due` (תצוגה "
        "מקדימה), `POST /api/financial/collection/run`. שערים להפעלה חיה: "
        "(1) **opt-in פר-ארגון** — נשלח רק כש-`Organization."
        "collection_reminders_enabled=True` (ברירת מחדל כבוי, דרישה "
        "רגולטורית). (2) **SMS מוכן** דרך SUMIT. (3) **מייל דורש הגדרת "
        "SMTP** ב-env — בלי זה המייל מדלג בכנות (לא מזייף הצלחה).\n\n"
        "**DSO וניקוד אשראי** — מחושבים בפועל מ-Invoice/Payment אמיתיים "
        "(לא ערכים קבועים) — חלק מדוח גיול ה-AR ב-`/ar` "
        "(`GET /api/ar/aging`, כלי צ'אט `get_ar_aging`)."
    )


def _masav_section() -> str:
    return (
        "## מס\"ב ותשלומים\n\n"
        "מסך `/masav` — הפקת קובץ זיכויים מס\"ב (רשומת כותרת K + תנועות + "
        "רשומת סה\"כ, 128 תווים לשורה) לתשלומי ספקים.\n\n"
        "- הגדרת מוסד (חד-פעמי, ניתן ע\"י מס\"ב): "
        "`GET/POST /api/masav/settings` — קוד מוסד/נושא (8 ספרות), מוסד "
        "שולח (5 ספרות), שם מוסד. **בלי הגדרה זו הפקת קובץ נכשלת בכנות "
        "(400)** — לא מייצרת קובץ עם נתוני ברירת-מחדל.\n"
        "- תצוגה מקדימה ללא הפקה: `POST /api/masav/preview`.\n"
        "- הפקת הקובץ בפועל: `POST /api/masav/generate` — לפי בחירת "
        "חשבוניות ספק פתוחות או כולן.\n"
        "- ולידציה: קוד בנק/מוסד נבדק מול רשימת חברי מס\"ב הפעילה "
        "(masav.co.il/participants-list), ות.ז ישראלית עם ספרת ביקורת."
    )


def _office_section() -> str:
    return (
        "## ניהול משרד: רישום תיקי לקוחות, rollup, סנכרון, החלפת ארגון\n\n"
        "למי שמנהל כמה תיקי-לקוח (משרד רו\"ח) — מסכים `/office` (רוחבי) "
        "ו-`/admin-clients` (תצוגת-על אדמין):\n\n"
        "- רישום תיק לקוח חדש (ארגון-שוכר נפרד, אימות SUMIT משלו): "
        "`POST /api/office/clients`. נכשל בכנות (ValueError) בלי מפתח SUMIT "
        "אמיתי — אף פעם לא 'מצליח' בלי חיבור אמיתי.\n"
        "- רשימת כל תיקי הלקוחות + סטטוס סנכרון/SUMIT: "
        "`GET /api/office/clients`.\n"
        "- רולאפ פיננסי חוצה-כל-הלקוחות (סה\"כ מע\"מ, פעולות נדרשות, "
        "התאמות): `GET /api/office/rollup`.\n"
        "- סקירת תיק לקוח בודד: `GET /api/office/clients/{client_id}/synthesis`.\n"
        "- הרצת סנכרון על-פי דרישה לתיק לקוח ספציפי: "
        "`POST /api/office/clients/{client_id}/sync`.\n"
        "- מפתח SUMIT ברירת-מחדל למשרד: `GET/POST /api/office/settings`.\n\n"
        "**החלפת ארגון (org switcher)** — זמינה רק ל-SUPER_ADMIN: header "
        "`X-Active-Org-Id` דורס את הארגון הפעיל בכל קריאת API (לא רק "
        "במסכי המשרד) — כך אפשר לפעול בהקשר תיק-לקוח ספציפי מכל מסך "
        "במערכת. הבחירה נבדקת/נרשמת בשרת, לא נסמכת על קלט-לקוח עיוור.\n\n"
        "בצ'אט — כלי \"משרד\" (tier נפרד, SUPER_ADMIN בלבד — לא מוצגים "
        "בכלל למשתמש רגיל): `list_office_clients`, `get_office_rollup`, "
        "`get_client_overview`, `run_client_sync`, `register_office_client`."
    )


def _bot_section() -> str:
    return (
        "## הבוט עצמו: כל הכלים הזמינים, ומנגנון האישור לפעולות\n\n"
        "כלי **קריאה** (מבוצעים אוטומטית, בלי אישור): `get_ar_aging`, "
        "`get_ap_bills`, `get_pnl`, `get_collection_cases`, `search_contacts`, "
        "`get_ledger_card`, `get_vat_position`, `get_cashflow`, "
        "`list_invoices`, `get_engine_status`, `list_expenses`, "
        "`get_pcn874_readiness`, `rezef_help` (המדריך הזה), ובמצב מנהל-"
        "משרד גם `list_office_clients`/`get_office_rollup`/`get_client_overview`.\n\n"
        "כלי **כתיבה** (side-effecting): `issue_document`, "
        "`log_collection_attempt`, `create_payment_link`, "
        "`create_expense_category`, `set_expense_category`, "
        "`classify_pending_expenses`, ובמצב מנהל-משרד גם `run_client_sync`/"
        "`register_office_client`.\n\n"
        "**מנגנון האישור** — קריטי: כשהמודל מבקש כלי כתיבה, השיחה נעצרת "
        "ונשמרת כ-`pending_action` על הודעת העוזר — הכלי **לעולם לא רץ** "
        "כתוצאה ישירה מבקשת המודל, לא בתור הראשון ולא בתור מאוחר יותר. רק "
        "קריאה נפרדת ומפורשת `confirm_action(message_id)` מריצה אותו בפועל "
        "— והיא קוראת את שם-הכלי/הקלט **מהרשומה בדאטהבייס עצמה** (לא מקלט "
        "שהלקוח שולח שוב), מוגבלת לארגון ולמשתמש המבקש, ופעם אחת בלבד "
        "(`executed` guard). כלי-משרד נבדקים גם בזמן ההצעה וגם שוב בזמן "
        "האישור מול תפקיד-המשתמש הנוכחי (הגנה כפולה)."
    )


def _integrations_section() -> str:
    return (
        "## אינטגרציות: SUMIT ו-Open Finance\n\n"
        "**SUMIT = מקור-האמת למסמכים** (חשבוניות/חשבונות/קבלות/הוצאות), "
        "לקוחות ופריטים — **לא** פקודות יומן/כרטסת (אלה נגזרות דטרמיניסטית "
        "אצלנו, ר' נושא `bookkeeping`). לפי מפת הכיסוי "
        "(`SUMIT_MODULE_COVERAGE.md`):\n"
        "- **מוכן**: לקוחות, מסמכי הכנסה, הוצאות, דוחות חוב, תשלומים, "
        "אמצעי תשלום, חיוב חוזר, CRM (ישויות/תיקיות/תצוגות), רשימות "
        "SMS/מייל, מלאי, משתמשים/הרשאות, חברות, דשבורדי הנה\"ח כפולה, "
        "הכנת דוח שנתי, רישום תשלום מזומן/צ'ק על מסמך, קישור זיכוי למסמך "
        "מקור, שכפול מסמך לתזמון עתידי, **דפי תשלום** (`create_payment_link`) "
        "ו**חיבור ארנק Upay** (`POST /api/payments/upay/setup`).\n"
        "- **חלקי**: התראות זיכוי/chargeback, מנדטים/החזרות מס\"ב **דרך "
        "SUMIT עצמו** (שונה מבניית קובץ המס\"ב שלנו — ר' נושא `masav`), "
        "בניית דשבורדים/תצוגות מותאמות, הגדרות מייל/דומיין יוצא, מכסות "
        "אחסון-קבצים.\n"
        "- **חסום/דורש מתאם**: BlueSnap, PayPal, מתאמי Bit, ייצוא HTML "
        "חופשי לרשימת CRM, יצירת מנדט חיוב-חוזר חדש מאפס (רק חיוב על "
        "פריט קיים נתמך), רשימת עסקאות מסוף-אשראי לפי טווח-תאריכים.\n\n"
        "**דף תשלום ללקוח** (`create_payment_link`) דורש שהארגון כבר חיבר "
        "את חשבון ה-Upay שלו (`POST /api/payments/upay/setup`) — אחרת "
        "SUMIT מחזיר \"מודול הסליקה לא מותקן בעסק\".\n\n"
        "**Open Finance** — קליינט מלא (כ-84 מתודות): חשבונות, תנועות, "
        "תשלומים, מנדטים, סקורינג אשראי, ולקוחות. **דורש הגדרה לפני שימוש "
        "חי**: `OPEN_FINANCE_USER_ID` ב-env + מסע consent שהלקוח משלים. "
        "עד אז נתוני Open Finance מסומנים provisional/לא-מאומתים, וחלק "
        "מהנתיבים (16+) מחזירים 400 כנה. מסכים: `/of-ops`, "
        "`/bank-insights`, `/bank`."
    )


def _limitations_section() -> str:
    return (
        "## מגבלות ידועות + מה בדרך\n\n"
        "**מגבלות קיימות (לא באגים — עיצוב/מצב-פרויקט מכוון וכן)**:\n"
        "- **שידור רשמי של מע\"מ/PCN874 לרשות המסים** — לא קיים ב-Rezef; "
        "מתבצע רק דרך ממשק SUMIT עצמו (ר' נושא `vat`).\n"
        "- **דוחות 1301/1214/102/126** — טיוטות/מבנה dict בלבד, לא קובצי "
        "הגשה רשמיים; לבדיקת רו\"ח לפני שימוש.\n"
        "- **`/cashflow-detail`, `/budget`, `/forecasting`, ולשונית "
        "אנומליות ב-`/ai-analytics`** — מבוססים טבלת תנועות ישנה שהפסיקה "
        "לגדול מסנכרון חי; לא משקפים פעילות עדכנית.\n"
        "- **מאזן ב-`/reports`** — מעורב (assets/liabilities מטבלה קפואה, "
        "retained_earnings אמיתי); עדיף `/ledger/balance-sheet`.\n"
        "- **השוואת תקציב/תקופה בסיכום המנהלים** (`/kpis`'s "
        "`executive-summary`) — honest-null: אין נתון-אמת אמין זמין כרגע, "
        "מחזירה `available: false` + סיבה, לא מספר מומצא.\n"
        "- **`/customers`** — המסך לא טוען נתון אמיתי כרגע (stub); לניהול "
        "לקוחות בפועל להשתמש ב-`/ar`, `/documents` או בכלי `search_contacts`.\n"
        "- **הנחת ספק/תשלום מוקדם (AP discount)** — honest-null: אין "
        "מקור-נתון אמיתי במערכת, לא ערך מזויף.\n"
        "- **Open Finance** — provisional עד השלמת consent + הגדרת env "
        "(ר' נושא `integrations`).\n\n"
        "**מה בדרך (טרם מומש)**:\n"
        "- **פחת (depreciation)** — בהמשך. כרגע אין רישום פחת נפרד "
        "בשום דוח (מוצהר במפורש בקוד ה-KPI ובדוחות השנתיים).\n"
        "- **שידור/הגשה דרך דפדפן אוטומטי לגורמים חיצוניים** (כשאין API "
        "רשמי מספק) — בהמשך.\n"
        "- **טופס 856 (ניכוי ספקים) מלא, טופס 6111** — בהמשך."
    )


# key -> one-line summary (for the topic index — the model sees this BEFORE
# fetching a full section, so it stays cheap even when unsure which topic fits).
TOPIC_SUMMARIES: dict[str, str] = {
    "overview": "כל כ-40 מסכי המערכת ומה כל אחד עושה, כולל דגלי חלקיות",
    "expenses": "תהליך הוצאות: קליטה, OCR, כרטיסים מותאמים, סיווג, תיוק ב-SUMIT",
    "vat": "מע\"מ ו-PCN874: איך מפיקים, ומה המגבלה על שידור רשמי",
    "bookkeeping": "יומן, כרטסת, מאזן בוחן, מאזן ויתרות פתיחה (הנה\"ח נגזרת)",
    "reports": "P&L, תזרים, דוח בנק, דוחות יומיים, טיוטות 1301/1214",
    "collections": "תיקי גבייה, תזכורות אוטומטיות (SMS/מייל) ו-DSO",
    "masav": "הפקת קובץ מס\"ב לתשלומי ספקים",
    "office": "ניהול משרד: תיקי לקוחות, רולאפ, סנכרון, החלפת ארגון",
    "bot": "כל כלי הצ'אט הזמינים ומנגנון האישור לפעולות כתיבה",
    "integrations": "SUMIT ו-Open Finance: מה עובד ומה דורש הגדרה נוספת",
    "limitations": "מגבלות ידועות ומה עוד לא מומש",
}

# Small alias map so a slightly different phrasing of the topic still hits —
# canonical keys (TOPIC_SUMMARIES' keys) always win; this is a convenience
# layer on top, not a replacement for them.
_ALIASES: dict[str, str] = {
    "screens": "overview", "routes": "overview", "מסכים": "overview", "מסך": "overview",
    "expense": "expenses", "הוצאות": "expenses", "ocr": "expenses",
    "vat_pcn874": "vat", "pcn874": "vat", "מעמ": "vat", 'מע"מ': "vat",
    "ledger": "bookkeeping", 'הנה"ח': "bookkeeping", "הנהח": "bookkeeping",
    "report": "reports", "דוחות": "reports",
    "collection": "collections", "גבייה": "collections", "dso": "collections",
    "masav_payments": "masav", 'מס"ב': "masav", "מסב": "masav",
    "office_management": "office", "משרד": "office",
    "chatbot": "bot", "tools": "bot", "בוט": "bot", "עוזר": "bot",
    "integration": "integrations", "sumit": "integrations", "open_finance": "integrations",
    "אינטגרציות": "integrations",
    "limitation": "limitations", "מגבלות": "limitations", "roadmap": "limitations",
}

TOPICS: dict[str, str] = {
    "overview": _render_overview(),
    "expenses": _expenses_section(),
    "vat": _vat_section(),
    "bookkeeping": _bookkeeping_section(),
    "reports": _reports_section(),
    "collections": _collections_section(),
    "masav": _masav_section(),
    "office": _office_section(),
    "bot": _bot_section(),
    "integrations": _integrations_section(),
    "limitations": _limitations_section(),
}


def topic_index() -> str:
    """The full topic list with one-line summaries — returned when no topic
    (or an unknown topic) is requested, so the model can pick the right one
    on a follow-up call instead of the whole KB being paid for up front."""
    lines = ["# מדריך רצף — נושאים זמינים", ""]
    for key in TOPICS:
        lines.append(f"- `{key}` — {TOPIC_SUMMARIES[key]}")
    lines.append("")
    lines.append("בקשו נושא ספציפי (topic) כדי לקבל את התוכן המלא של אותו נושא.")
    return "\n".join(lines)


def get_topic(topic: Optional[str] = None) -> str:
    """Look up a KB section by topic key. No topic -> the index. Unknown
    topic -> the index + an explicit "not found" note (never a silent
    empty/guessed answer)."""
    if not topic or not topic.strip():
        return topic_index()
    key = topic.strip().lower()
    key = _ALIASES.get(key, key)
    if key not in TOPICS:
        return f'{topic_index()}\n\n---\nלא נמצא נושא בשם "{topic}".'
    return TOPICS[key]
