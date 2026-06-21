# Accounting Engine Buildout — Design Spec

תאריך: 2026-06-16
החלטת המשתמש: לעזוב כפילויות (#26) לעת אימות; לבנות #27–#30 לפי spec זה ולצאת לביצוע.

## עקרון-על
SUMIT הוא מקור-האמת לספרים. ה-API שלו **אינו** חושף פקודות יומן/כרטסת — רק מסמכים
(חשבוניות/חשבונות/קבלות/הוצאות), לקוחות, פריטי הכנסה. לכן כל שכבת ההנה"ח שלנו היא
**נגזרת דטרמיניסטית מהמסמכים**, מסומנת מפורשות "נגזר — לא הספרים הרשמיים, לבדיקת רו"ח".
צד Open Finance טרם אומת על נתון בנק חי; כל תלוי-OF נשאר provisional.

## #27 — מנוע הנה"ח כפולה (shadow ledger)
`services/ledger_service.py` — חישוב on-the-fly, ללא טבלה חדשה. אם נדרש persist → JournalEntry (lines JSON קיים, source="derived").

תרשים חשבונות מינימלי (ישראלי), קבוע במודול:
| קוד | שם | סוג |
|-----|-----|-----|
| 1100 | לקוחות (AR) | asset |
| 1200 | עו"ש בנק | asset |
| 2100 | ספקים (AP) | liability |
| 2200 | מע"מ עסקאות (output) | liability |
| 1300 | מע"מ תשומות (input) | asset |
| 4000 | הכנסות | revenue |
| 5000 | הוצאות/קניות | expense |

כללי פקידה (כל פקודה מאוזנת במבנה):
- חשבונית מכירה: DR 1100 (total), CR 4000 (subtotal), CR 2200 (tax)
- קבלה/תקבול: DR 1200, CR 1100
- חשבון ספק/הוצאה: DR 5000 (subtotal), DR 1300 (tax), CR 2100 (total)
- תשלום לספק: DR 2100, CR 1200
- חשבונית זיכוי: היפוך חשבונית מכירה (סכומים שליליים שכבר מגיעים כך מ-SUMIT)

API:
- `build_journal(db, org_id, start=None, end=None) -> list[entry]` — entry={date, memo, source_ref, lines[]}
- `trial_balance(db, org_id, start, end) -> {accounts[], total_debit, total_credit, balanced: bool}`
- `general_ledger(db, org_id, account_code, start, end) -> {opening, movements[], closing}` (כרטסת)

**אינוריאנט קשיח:** Σdebit == Σcredit גלובלית וגם בכל פקודה. נבדק בטסט.
Route: `/api/ledger/journal|trial-balance|ledger/{code}`. UI: `LedgerDashboard.tsx`.

## #28 — דוחות מצטברים-יומיים תוך-חודשיים
`services/daily_reports_service.py` — מעל financial_reports_service הקיים.
- `cumulative_pl(db, org_id, year, month) -> [{day, revenue_cum, expense_cum, profit_cum}]`
- `cumulative_cashflow(...)`, `ar_aging(...)`, `ap_aging(...)`, `supplier_breakdown(...)`
- בסיס: מסמכי SUMIT אמיתיים. Route `/api/daily-reports/*`, UI `DailyReportsDashboard.tsx`.

## #29 — דוחות שנתיים 1301 (יחיד) / 1214 (חברה)
`services/annual_report_service.py` — **טיוטה בלבד**, כל פלט נושא `draft: true` ו-`disclaimer: "לבדיקת רו"ח"`.
- `form_1301(db, org_id, year)` — נגזר מ-P&L נגזר; מיפוי שדות עיקריים.
- `form_1214(db, org_id, year)` — חברה; P&L + מאזן נגזרים.
- Route `/api/annual-reports/{1301|1214}`, UI `AnnualReportsDashboard.tsx`. באנר אזהרה ברור.

## #30 — המנוע המאחד (orchestrator)
`services/engine_service.py` — שכבת פקודה אחת מעל הכל:
- `status(db, org_id)` — בריאות חיבורים (SUMIT/OF), ספירות, חוסרים.
- `run_pipeline(db, org_id)` — sync → insights → reconciliation → synthesis → ledger → reports; מחזיר סיכום מובנה + caveats לכל שלב (real/derived/unvalidated).
- Route `/api/engine/status|run`. UI: כרטיס-על ב-dashboard.

## בדיקות
טסט לכל שירות. הקריטי: trial-balance balanced על נתוני SUMIT אמיתיים. כל הפלטים הרשמיים/נגזרים מסומנים. הרצת מלוא הסוויטה בסוף.
