# CFO Platform — אודיט מוצר ומפת-דרכים ל-Production

> תאריך: 2026-06-19 · מבוסס על אודיט רב-סוכני (20 סוכנים) קריאה-בלבד מול קוד חי.
> **מסמך זה הוא הצעה בלבד — לא בוצעו שינויי קוד.** כל ממצא נושא ראיה (file:line / route / test).

## עקרון-על — אופי המערכת (לא לשנות)
- **SUMIT = מקור-האמת לספרים.** ה-API שלו חושף מסמכים (חשבוניות/חשבונות/קבלות/הוצאות), לקוחות, פריטים — **לא** פקודות יומן/כרטסת.
- **שכבת ההנה"ח שלנו נגזרת דטרמיניסטית מהמסמכים**, מסומנת מפורשות `derived: true` + "לבדיקת רו"ח". זה לא תחליף לספרים הרשמיים.
- **Multi-tenancy ברמת ארגון** במסד Postgres יחיד, עם credentials מוצפנים פר-org ל-SUMIT/Open Finance.
- **Open Finance (בנק) = provisional/לא-מאומת** על נתון חי עד השלמת מסע consent + `OPEN_FINANCE_USER_ID`.

כל ההמלצות במסמך זה **מעשירות בתוך האופי הזה**. כל מה שדורש ארכיטקטורה אחרת (להפוך את היומן הנגזר לספרים רשמיים, DB פיזי פר-משתמש, נטישת SUMIT כמקור-אמת) — מסומן מפורשות כ"מחוץ-לאופי" ונדחה.

## מצב כללי
- **216 טסטים עוברים** (`pytest -q`, 14.4s). חבילה בריאה.
- **DB**: 29 טבלאות קיימות (SQLite מקומי). 834 הוצאות, 13 חשבוניות, 101 תנועות בנתוני הבדיקה.
- **audit_routes.py**: 176 routes — 110 OK (62%), 21 WARN (4xx/auth תקין), 45 FAIL — **רובם env-gated** (SUMIT/OF/Email לא מחוברים), לא באגי-קוד.
- **חוסמי deploy (env, לא קוד)**: `DATABASE_URL` (Supabase), `OPEN_FINANCE_USER_ID`, Google OAuth client IDs, סודות נפרדים (JWT/encryption/cron/webhook). פירוט ב-`docs/PRODUCTION_READINESS.md`.

---

## גריד היכולות — מול הרשימה שביקשת

| # | יכולת | סטטוס | מה עובד | פער עיקרי | חומרה |
|---|-------|-------|---------|-----------|-------|
| 1 | **מי חייב לנו (AR)** | 🟢 real | backend אמיתי: גיול 0-30/31-60/61-90/91-120/120+, credit-score, תזכורות, תחזית גבייה. **אומת live: `/ar/aging` שטוח, total 155,320, 11 חשבוניות — הדשבורד תקין** | ערכים hardcoded ב-`ar_service` (DSO, credit_limit, last_payment) שמאחורי ה-endpoint ה-nested `/api/financial/ar/aging` בלבד; קיימים **שני** endpoints ל-AR aging (שטוח ב-cfo_dashboard, nested ב-financial_management) — שקול לאחד | P2 |
| 2 | **מה אנחנו חייבים (AP)** | 🟡 partial | backend אמיתי: Bills מסונכרנים מ-SUMIT, גיול ספקים, לוח תשלומים — נבדק ע"י טסטים חיים | route `/ap` מרנדר **קומפוננטה שגויה** (`CFOARDashboard`) → מציג נתוני AR; שדות discount/early-payment מאופסים hardcoded; אין טסט ל-ap-aging | P1 |
| 3 | **רווח/הפסד מצטבר חודשי+יומי** | 🟢 derived | `daily_reports_service`: P&L מצטבר יומי, גיול, פירוק ספקים — מבוסס מסמכי SUMIT אמיתיים; דשבורד מחווט | הוצאות מתבססות על `Expense` (manual/SUMIT-filed), אין `fetch_expenses` ייעודי מ-SUMIT | P2 |
| 4 | **תזרים מזומנים + תחזית** | 🟡 partial | `/dashboard/cashflow` אמיתי; forecasting (exp-smoothing/regression/ensemble) + תרחישים | **`AgreementCashFlow` ב-memory בלבד — אין טבלאות** (נתונים נעלמים ב-restart); `CashFlowDashboard` לא ב-nav; aging-stubs מאפסים | **P0** + P1 |
| 5 | **הנהלת חשבונות כפולה (יומן/כרטסת/מאזן בוחן)** | 🟢 real | `ledger_service`: יומן מאוזן, מאזן-בוחן, כרטסת, source_ref לכל פקודה; אינווריאנט Σdebit==Σcredit נבדק; דשבורד מחווט | אין יתרות פתיחה (carry-forward); `fetch_journal_entries` ריק (נגזר, by design) | P1 |
| 6 | **מאזן + דוחות פיננסיים** | 🟡 partial | `financial_reports_service`: מאזן, P&L, תזרים, השוואת שנים; דשבורד מחווט | `generate_balance_sheet` **חסר `derived:true`+disclaimer** (בניגוד ל-ledger); תחזית תזרים משתמשת ב-`random.uniform` | P1/P2 |
| 7 | **שליחה לבנקים (מס"ב/דוחות)** | 🟢 real | `masav_service`: קובץ מס"ב 128-תווים; `bank_report_service`; דשבורד מחווט | דורש הגדרת מוסד-שולח (Masav settings); אין ולידציית פרטי-בנק ספק; אין טסטים ל-bank_report | P1/P2 |
| 8 | **קליטת בנק + התאמות (Open Finance)** | 🟡 partial | client ~84 מתודות; `bank_reconciliation` (התאמת תנועות→מסמכים, חלון ±7 ימים, token-overlap); insights; דשבורד מחווט | **`OPEN_FINANCE_USER_ID` חסר** (חוסם חי); אין UI הגדרת credentials פר-org; תווית "provisional" לא מוצגת; אין שכבת trust/idempotency | **P0** + P1 |
| 9 | **הוצאות/רכש/OCR** | 🟢 real | `expense_ocr_pipeline` (getpdf→ראייה LLM→אימות ח.פ→סיווג→תיוק); `expense_filing`; `inventory`; `DocumentManager` | סיווג בלבד — **אין מנגנוני ניכוי** (רכב/בית/טלפון %) לפי פקודת מס הכנסה; אין זיהוי כפילויות מסמכים | P1 |
| 10 | **שכר (Payroll)** | 🟢 real | `payroll_service` + `calculators`: מס הכנסה, ב"ל, מס בריאות, פנסיה, נקודות זיכוי, שווי-רכב; דשבורד מחווט | עובדים מוזנים ידנית (לא מסונכרנים); אין העברה בנקאית לשכר; שכר לא מוזרם ליומן; קבועי-מס 2026 hardcoded; אין XML ל-102/126 | P1/P2 |
| 11 | **מיסוי (מע"מ/1301/1214/ניכוי/מקדמות)** | 🟡 partial | `tax_service`, `vat_utils`, `annual_report_service` (1301/1214 טיוטה); calculators | ח.פ hardcoded `123456789`; היסטוריית-מס לא נשמרת; **ניכוי ספקים (856) מחזיר ריק**; ייצוא מע"מ לא בפורמט PCN874; אין דשבורד-מס | P1/P2 |
| 12 | **דשבורדים / חוויית CFO / KPI / alerts** | 🟢 real | ~40 דשבורדים מחווטים; CFOOverview/Executive/KPI/Office/AdminClients; `alert_engine`+`cfo_brain` | `alert_engine`/`cfo_brain` ללא טסטים; קריאות `/analytics/*` ללא router תואם; alerts נבלעים ב-try/except אילם | P1/P2 |

🟢 real/derived = backend מחשב מנתונים אמיתיים · 🟡 partial = backend אמיתי אך פער חיווט/נתון · 🔴 mock/missing = (אין כאלה ברשימה — כל היכולות שמנית **קיימות** עם backend אמיתי).

---

## באג data-integrity שאומת ידנית — VAT split בנתיב החי (P1, לא נסגר!)
סוכן הדיאגנוסטיקה הכריז ש"VAT split נסגר" — אבל **בדק את הקובץ הלא-נכון**. אימות ידני:
- הנתיב החי הוא `SumitConnector` (`sync_engine.get_connector_for_org` → `sumit_connector.py:620`).
- `sumit_connector.fetch_invoices` (שורות 222-223) ו-`fetch_bills`:
  ```python
  tax = Decimal(str(getattr(doc, "vat_amount", 0) or 0))
  subtotal = Decimal(str(getattr(doc, "subtotal", None) or (total - tax)))
  ```
  **אין fallback של `split_inclusive`.** אם מסמך SUMIT מגיע בלי `vat_amount` → `tax=0`, `subtotal=total`.
- ה-fallback קיים רק ב-`sumit_integration.py:337` — **נתיב שאינו בשימוש** ע"י ה-sync.
- הזיכרון `accounting-engine-buildout` תיעד את התסמין אמפירית: "VAT לא מפוצל במסמכים המסונכרנים → פלט VAT=0".
- **השפעה:** שורת מע"מ ביומן/כרטסת, דוח מע"מ, ו-P&L עלולים להתאפס בשקט.
- **תיקון מוצע:** להעביר את `split_inclusive(total, issue_date)` כ-fallback ל-`sumit_connector.fetch_invoices/fetch_bills` כשחסר `vat_amount`, זהה ל-`sumit_integration`. **P1**.

---

## P0 — חוסמי production
1. **`AgreementCashFlow` ללא persistence** — Agreement/Milestone/CashFlowEntry ב-dict בזיכרון; נעלמים ב-restart. צריך טבלאות + migration. (יכולת 4)
2. **Open Finance לא חי** — `OPEN_FINANCE_USER_ID` חסר ב-prod; 16 routes מחזירים 400. חוסם את כל זרימת הבנק החיה. (env + UI consent, יכולת 8)
3. **אימות יצירת-תנועה ב-SUMIT** — `SumitConnector` כרגע מנרמל וסופר בלבד; אין verification של write-backs (יצירת חשבונית/קבלה חזרה ל-SUMIT). (יכולת מנוע-סנכרון)
4. **חוסמי env/deploy** — `DATABASE_URL` (Supabase), Google OAuth, סודות נפרדים. (ראה `PRODUCTION_READINESS.md`)

## P1 — נכונות וחיווט (ה-backend אמיתי, ה-UI/נתון לא משקף אותו)
> אלה ההכי גבוהי-מינוף: "לדעת מי חייב/איפה אנחנו עומדים" נשבר כי ה-UI מציג אפסים מעל backend תקין.
1. ~~**AR schema mismatch**~~ — **בוטל אחרי אימות-ריצה:** `/ar/aging` (cfo_dashboard, שטוח) נקרא נכון ע"י `CFOARDashboard` המקורי. הבלבול היה מול `/api/financial/ar/aging` (endpoint שונה עם prefix). אין באג כאן.
2. **AP route שגוי** — `App.tsx:314` `/ap`→`CFOARDashboard` (קורא `/ar/aging`). צריך `APDashboard` ייעודי מול `/daily-reports/ap-aging` או `/financial/ap/*`. → תכנית TDD.
3. **VAT split fallback** ב-`sumit_connector` (ראה למעלה).
4. **`CashFlowDashboard` לא ב-nav** — קומפוננטה מוכנה, לא מחווטת. → תכנית TDD.
5. **balance_sheet חסר `derived:true`+disclaimer** — חוסר-עקביות מול ledger; סיכון רגולטורי (מצג כ"רשמי"). → תכנית TDD.
6. **AR ערכים hardcoded** — DSO `35+(i%5)*3`, credit_limit `100000`, last_payment_date `None`, email `{id}@example.com`. (יכולת 1)
7. **AP discount fields hardcoded 0** + פרטי-בנק dummy ב-bank-reconciliation. (יכולת 2)
8. **ניכוי ספקים (856) מחזיר ריק** + ח.פ hardcoded ב-`TaxComplianceService`. (יכולת 11)
9. **יתרות פתיחה ביומן/מאזן** — carry-forward מתקופות קודמות. (יכולת 5)
10. **`date_trunc` על SQLite** (`forecasting_service.py:678-710`) — נכשל מקומית/בטסטים, **עובד ב-prod Postgres**. באג נאמנות-טסט, לא חוסם-פרודקשן. תיקון: ביטוי portable (strftime/extract לפי dialect).

## P1/P2 — העשרות שעברו שער-ביקורת (8 מתוך 28 מועמדות)
> מבוססות על מחקר ה-skills הישראליים + מערכות OSS, **כל אחת אומתה כלא-קיימת ותואמת-אופי**.

| המלצה | יכולת | חומרה | מאמץ |
|-------|-------|-------|------|
| **workflow גבייה מתמשך** — לשמר `collection_status` כ-state, לעקוב אחר ניסיונות (תאריך/אמצעי/promise-to-pay), לחבר ל-alert_engine ו-DSO | AR | P1 | M |
| **Open Finance provisional staging** — `is_provisional` ב-`BankTransaction`; OF→provisional; סינון ב-reconciliation; תווית UI | בנק | P1 | M |
| **מנגנוני ניכוי הוצאה** — רכב (ק"מ), בית (% שכ"ד), טלפון/אינטרנט (%) לפי פקודת מס הכנסה | הוצאות | P1 | M |
| **ייצוא מע"מ PCN874 (מבנה אחיד)** — fixed-width רשמי במקום pipe-delimited; דגל zero-rated/Eilat | מע"מ | P1 | M |
| **ריבית חוק מוסר תשלומים** — Pruta = Prime+2%, צבירה על חשבוניות באיחור | AR | P2 | M |
| **מכתבי התראה עבריים + תביעות קטנות** — מעבר לתבניות email/SMS | AR | P2 | M |
| **טופס 856 + ishur nikui** — `_get_supplier_withholding` מחזיר ריק כיום | מיסוי | P2 | M |
| **טופס 6111** — declared ב-ReportType ללא generator | מיסוי | P2 | S |

## מה כבר קיים (לא לבנות מחדש — אומת ע"י שער-הביקורת)
11 מועמדות נדחו כי **כבר ממומשות**: גיול AR/AP + DSO/DPO · התאמת-בנק exception-based · תחזיות תזרים (det/heuristic/scenario) · budget-vs-actual variance · זיהוי אנומליות מסמכים · roll-forward מאזן-בוחן · drill-down ל-source_ref · תבניות חוזרות (budget/forecast) · credit-scoring לקוח/ספק + concentration-risk · השוואת תקופות.

## מחוץ-לאופי (נדחה במכוון)
- **CSV→GL posting rules גנרי** (כמו hledger) — יוצר נתיב-קליטה שני סמכותי שעוקף מסמכי SUMIT. נגד החוזה.
- **להפוך את היומן הנגזר לספרים הרשמיים** — סותר את SUMIT-as-source-of-truth.

---

## מפת-דרכים מוצעת (לאישורך — לא בוצע)
- **שלב 0 — Deploy gates (env)**: `DATABASE_URL`, `OPEN_FINANCE_USER_ID`, OAuth, סודות; הרצת migrations; אימות `/api/health`.
- **שלב 1 — "להראות את האמת" (P1 wiring)**: AR schema, AP dashboard, VAT fallback, CashFlow nav, balance-sheet flag. → **תכנית TDD מצורפת**: `docs/superpowers/plans/2026-06-19-production-readiness-wiring-fixes.md`.
- **שלב 2 — persistence + יתרות**: טבלאות AgreementCashFlow (P0); יתרות פתיחה ביומן; ניקוי ערכי-hardcoded ב-AR/AP.
- **שלב 3 — העשרות מיסוי/גבייה**: provisional staging, workflow גבייה, מנגנוני ניכוי, PCN874, 856/6111 — **כל אחת תכנית נפרדת**.
- **שלב 4 — חוסן**: טסטים ל-alert_engine/cfo_brain/bank_report; portable date_trunc; consent-journey ל-OF.

כל פריט בשלבים 1-4 הוא subsystem עצמאי → תכנית-יישום נפרדת משלו (לפי כלל "subsystem אחד לכל plan").
