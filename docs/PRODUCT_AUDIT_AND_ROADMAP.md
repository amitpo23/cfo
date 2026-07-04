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
| 1 | **מי חייב לנו (AR)** | 🟢 real | backend אמיתי: גיול 0-30/31-60/61-90/91-120/120+, credit-score, תזכורות, תחזית גבייה. **אומת live: `/ar/aging` שטוח, total 155,320, 11 חשבוניות — הדשבורד תקין**. ~~ערכים hardcoded (DSO, credit_limit, last_payment)~~ **בוטל אחרי אימות 2026-07-04**: כל השלושה מחושבים בפועל מ-Payment/Invoice אמיתיים (`_last_payment_date` שואל תשלום אחרון בפועל; `_behavioral_credit_limit`'s docstring: "אין מסגרת מוגדרת במערכת, לכן זו המלצה מבוססת-נתונים, לא מספר קבוע מזויף"; DSO ממוצע ימים אמיתי בין הנפקה לתשלום) | קיימים **שני** endpoints ל-AR aging (שטוח ב-cfo_dashboard, nested ב-financial_management) — עדיין רלוונטי, שקול לאחד | P2 |
| 2 | **מה אנחנו חייבים (AP)** | 🟢 real | ~~route `/ap` מרנדר קומפוננטה שגויה~~ **תוקן**: `/ap` → `CFOAPDashboard` ייעודי (אומת ב-App.tsx, 2026-07-03) | שדות discount/early-payment עדיין hardcoded ב-`ap_service` — לא נבדק מחדש הפעם | P2 |
| 3 | **רווח/הפסד מצטבר חודשי+יומי** | 🟢 derived | `daily_reports_service`: P&L מצטבר יומי, גיול, פירוק ספקים — מבוסס מסמכי SUMIT אמיתיים; דשבורד מחווט | הוצאות מתבססות על `Expense` (manual/SUMIT-filed), אין `fetch_expenses` ייעודי מ-SUMIT | P2 |
| 4 | **תזרים מזומנים + תחזית** | 🟢 real | ~~AgreementCashFlow ב-memory בלבד~~ **תוקן**: `CashflowAgreement`/`CashflowEntry` טבלאות persist אחרי כל מוטציה (`agreement_cashflow_service.py`); ~~CashFlowDashboard לא ב-nav~~ **תוקן**: מנותב תחת `/cashflow-detail` + פריט nav | aging-stubs מאפסים — לא נבדק מחדש הפעם | P1 |
| 5 | **הנהלת חשבונות כפולה (יומן/כרטסת/מאזן בוחן)** | 🟢 real | `ledger_service`: יומן מאוזן, מאזן-בוחן, כרטסת, source_ref לכל פקודה; אינווריאנט Σdebit==Σcredit נבדק; דשבורד מחווט. ~~אין יתרות פתיחה~~ **תוקן**: `set_opening_balances`/`get_opening_balances` + `/api/ledger/opening-balances` | `fetch_journal_entries` ריק (נגזר, by design — לא באג) | — |
| 6 | **מאזן + דוחות פיננסיים** | 🔴 **ממצא חדש — ראה "מערכת חשבונאות כפולה" למטה** | `/api/ledger/balance-sheet` (נגזר מ-Invoice/Bill אמיתיים, מאומת חי) תקין | `/api/reports/balance-sheet` + `/api/reports/profit-loss` (`financial_reports_service`, דשבורד `/reports`) בנויים על טבלאות `Account`/`Transaction` **נפרדות לגמרי** שמאוכלסות ע"י קוד שבור/נטוש (`data_sync_service.py`) — ראה ממצא מפורט | **P0** |
| 7 | **שליחה לבנקים (מס"ב/דוחות)** | 🟢 real | `masav_service`: קובץ מס"ב 128-תווים; `bank_report_service`; דשבורד מחווט | דורש הגדרת מוסד-שולח (Masav settings); אין ולידציית פרטי-בנק ספק; אין טסטים ל-bank_report | P1/P2 |
| 8 | **קליטת בנק + התאמות (Open Finance)** | 🟡 partial | client ~84 מתודות; `bank_reconciliation` (התאמת תנועות→מסמכים, חלון ±7 ימים, token-overlap); insights; דשבורד מחווט | **`OPEN_FINANCE_USER_ID` חסר** (חוסם חי); אין UI הגדרת credentials פר-org; תווית "provisional" לא מוצגת; אין שכבת trust/idempotency | **P0** + P1 |
| 9 | **הוצאות/רכש/OCR** | 🟢 real | `expense_ocr_pipeline` (getpdf→ראייה LLM→אימות ח.פ→סיווג→תיוק); `expense_filing`; `inventory`; `DocumentManager` | סיווג בלבד — **אין מנגנוני ניכוי** (רכב/בית/טלפון %) לפי פקודת מס הכנסה; אין זיהוי כפילויות מסמכים | P1 |
| 10 | **שכר (Payroll)** | 🟢 real | `payroll_service` + `calculators`: מס הכנסה, ב"ל, מס בריאות, פנסיה, נקודות זיכוי, שווי-רכב; דשבורד מחווט. **עודכן 2026-07-04**: `form_102`/`form_126` **קיימות בפועל** ומחשבות סיכומים אמיתיים מ-`Payslip` (ניכוי-מס/ב"ל/בריאות, סה"כ לחודש/לשנה פר-עובד) — לא תועדו כקיימות | עובדים מוזנים ידנית (לא מסונכרנים); אין העברה בנקאית לשכר; שכר לא מוזרם ליומן; קבועי-מס 2026 hardcoded; `form_102`/`form_126` מחזירות dict מובנה, **לא** קובץ XML בפורמט ההגשה הרשמי לרשות המסים — עדיין נדרש | P1/P2 |
| 11 | **מיסוי (מע"מ/1301/1214/ניכוי/מקדמות)** | 🟡 partial | `tax_service`, `vat_utils`, `annual_report_service` (1301/1214 טיוטה); calculators. ~~ח.פ hardcoded 123456789~~ **בוטל אחרי אימות**: כבר טוען מ-`Organization.tax_id` עם fallback כנה של אפסים. ~~ניכוי ספקים (856) מחזיר ריק~~ **בוטל אחרי אימות**: honest-null מכוון (רק ספקים עם `withholding_rate` מפורש נכללים) | היסטוריית-מס לא נשמרת; ייצוא מע"מ לא בפורמט PCN874; אין דשבורד-מס | P2 |
| 12 | **דשבורדים / חוויית CFO / KPI / alerts** | 🟢 real | ~40 דשבורדים מחווטים; CFOOverview/Executive/KPI/Office/AdminClients; `alert_engine`+`cfo_brain` | ~~alert_engine/cfo_brain ללא טסטים~~ **תוקן**: כיסוי מלא נוסף לשניהם (17+32 טסטים), כולל תיקון באג אזור-זמן שקט + בידוד-כשלים ב-cfo_brain. ~~קריאות /analytics/* ללא router תואם~~ **בוטל אחרי אימות**: הראוטר כן רשום; אך תוך כדי בדיקה נמצא משהו חמור יותר — **תוקן**: `/analytics` (AnalyticsDashboard.tsx) היה דף עם נתונים מומצאים ב-100% (ללא שום קריאת API!) — הוסר לגמרי, מנותב ל-/kpis האמיתי. alerts נבלעים ב-try/except אילם **תוקן**: `/ai-analytics`'s `predict_metric`/`get_ai_analysis` היו מייצרים נתונים מומצאים (random noise / הקשר פיננסי קשיח זהה לכל ארגון) — כעת מחזירים 400 כנה במקום זה; `is_illustrative` על ה-recommendations הקשיחות (עיצוב מכוון, פאזה 2) סוף-סוף מוצג ב-UI | — |

🟢 real/derived = backend מחשב מנתונים אמיתיים · 🟡 partial = backend אמיתי אך פער חיווט/נתון · 🔴 mock/missing = (אין כאלה ברשימה — כל היכולות שמנית **קיימות** עם backend אמיתי).

---

## באג data-integrity שאומת ידנית — VAT split בנתיב החי — **תוקן ✅ (2026-07-03, commit 23353ca)**
> נשאר כאן כתיעוד-היסטורי; אומת מחדש 2026-07-03 שהתיקון חי בקוד. אל תשכפל את החקירה.

הבאג המקורי: `sumit_connector.py` (כיום ב-`src/cfo/services/sumit_connector.py` — הקובץ עבר מיקום) לא נפל-back ל-`split_inclusive` כש-SUMIT לא שולח `vat_amount`, מה שיצר `tax=0` בשקט. **מאומת תוקן**: פונקציה ייעודית `_derive_subtotal_tax(doc, total)` (שורה 25) כיום מפעילה `split_inclusive(total, doc_day)` בדיוק כשחסר `vat_amount`, ומשמשת גם ב-`fetch_invoices` וגם ב-`fetch_bills`. אין פעולה נוספת נדרשת.

---

## ממצא חדש (2026-07-03) — שתי מערכות חשבונאות מקבילות, אחת נגזרת מקוד שבור/נטוש (P0)

**התגלה תוך כדי חקירת ה-P1 הישן "`generate_balance_sheet` חסר `derived:true`+disclaimer"** — התברר להיות חמור בהרבה ממה שהניסוח ההוא רמז.

### הראיה
לאותו ארגון (org 1, חברת SUMIT 439924597, 21 חשבוניות אמיתיות ₪512,327 + 875 חשבונות ₪-942,428 מסונכרנים), שני endpoints שאמורים שניהם להציג "מאזן" מחזירים מספרים שאין ביניהם שום קשר:

| | `/api/ledger/balance-sheet` (נגזר מ-Invoice/Bill, `/ledger` ב-nav) | `/api/reports/balance-sheet` (`financial_reports_service`, `/reports` ב-nav) |
|---|---|---|
| total_assets | **-503,734.34** | **-24,634.68** |
| ספקים (AP) | **-942,428.02** — תואם בדיוק את סכום ה-875 חשבונות בפרוד | (לא מופיע — total_liabilities=0) |
| `/api/reports/profit-loss` (טווח רחב) | — | revenue=372,658.74, expenses=1,510,916.05 — **לא תואם שום סכום אמיתי** |

### שורש הבעיה — לא "חסר disclaimer", אלא נתיב-קוד נטוש ושבור
1. `/api/reports/*` (balance-sheet, profit-loss) נקראים מ-`FinancialReportsService`, שקורא מטבלאות `Account`/`Transaction` — **טבלאות נפרדות לגמרי** מ-`Invoice`/`Bill` שמזינות את `/ledger` ואת `/dashboard/pnl` האמיתי.
2. טבלאות אלה מאוכלסות (בכל sync אמיתי!) ע"י `DataSyncService.sync_all()` (`data_sync_service.py:129`), שמופעל אוטומטית מתוך `run_post_sync_tasks` — שמופעל מ-4 נתיבים חיים אמיתיים: `cfo_sync.py` (ה-sync הראשי), `office.py`, `cron.py`, `admin.py`.
3. **הבאג בפועל**: `is_income = doc.document_type in ['invoice', 'receipt', 'tax_invoice']` — משווה קוד-מסמך **מספרי** של SUMIT (לדוגמה `15`) מול רשימת **strings** → תמיד `False`. תוצאה נבדקה ישירות בפרוד: **כל** שורה ב-`transactions` עבור org 1 (127 שורות) יצאה `transaction_type='EXPENSE'`, `amount=0.00`, `description='15: Unknown'` — לא נתוני-בנק אמיתיים, לא seed/demo, אלא תוצר-לוואי ישיר של קוד שהתנתק מהמוסכמה המספרית של SUMIT (אותה מוסכמה שתוקנה השבוע במקומות אחרים: "SUMIT doc-type 15→16").
4. אישוש: כל ה-5 ה"ארגונים" בפרוד מציגים בדיוק אותם 5 חשבונות-שלד `source='sumit'` ביתרה 0.00 (Bank Account/AR/AP/Revenue/Expenses) — לא נתון עסקי אמיתי, אלא תוצר של אתחול/onboarding.
5. `DataSyncDashboard.tsx` — הממשק המקורי שהיה אמור לשמש להפעלה ידנית של `DataSyncService` — **אינו מנותב** ב-`App.tsx` (dead component). אף משתמש אמיתי לא בוחר להריץ את הנתיב הזה במודע; הוא רץ **רק** כתוצר-לוואי אוטומטי, בלי ידיעת המשתמש.
6. **טווח השפעה — נבדק במלואו (2026-07-03), רחב יותר ממה שנחשד תחילה**. גריפ מדויק לפי שימוש-בפועל (לא רק import) על כל 10 השירותים:
   - **תלות אמיתית, בנתיב חי**: `ai_analytics_service.py` (Transaction לפי קטגוריה — תובנת "ריכוז הוצאות" ל-90 יום, מזין AI insights); `ai_intelligence_agent.py` (סכום `Account.balance` ל-cash_balance); `balance_snapshot.py` (סכום `Account.balance` — נקרא גם מ-`bank_report_service.py` וגם מ-`kpi_service.py`, כך ש-KPI dashboard תלוי בעקיפין!); `budget_service.py` (Transaction לפי טווח-תאריכים, תקציב-מול-בפועל); `cost_analysis_service.py` (Transaction לפי קטגוריה, הוצאות); `fees_service.py` (סכום Transaction); `forecasting_service.py` (Transaction לפי קטגוריה — קלט לתחזית תזרים); `tax_service.py._get_annual_profit_estimate` — תוקן כבר פעם אחת (הערה מפורשת בקוד!) לא לקרוא ישירות מ-Transaction, אבל **עדיין** קורא מ-`FinancialReportsService.generate_profit_loss` שבעצמו עדיין קורא מאותן טבלאות שבורות — מזין `calculate_tax_advance` (מקדמות מס), route חי (`financial_management.py`) אך **ללא UI שקורא לו כרגע** (חשיפה אפסית היום, אבל התוצאה תהיה שגויה אם ייקרא).
   - **עדכון 2026-07-04**: `kpi_service.py` תלוי גם **ישירות**, לא רק דרך `balance_snapshot`: `get_executive_summary`/`get_kpi_dashboard` קוראים ל-`_get_financial_data` שקורא ל-`FinancialReportsService.generate_profit_loss` (אותה מערכת שבורה). בנוסף, `get_executive_summary`'s `comparison_to_budget` (יעדים קשיחים 500000/400000) ו-`comparison_to_previous` (אחוזים קשיחים 8.5%/5.2%/12.3%) הם עוד נתון מומצא באותו קובץ — **לא תוקן**: תיקון "אמיתי" (חישוב מול Budget האמיתי / snapshot של חודש קודם) עדיין יריץ מעל אותה שכבת נתונים שבורה/קפואה, ויהפוך "שגוי-בבירור" ל"שגוי-סביר" — בדיוק הטעות שכבר נמנעה פעם אחת ב-data_sync_service. ממתין לאותה החלטת repair/retire.
   - **import מת בפועל** (לא שואלים את הטבלאות בפועל): `ap_service.py`, `ar_service.py`.
   - **מסקנה**: 8-9 יכולות (לא רק שני endpoints) בנויות בשקט על אותו dataset קפוא/שגוי. זה מחזק את הצורך בהחלטת repair/retire — לא מצדיק תיקון פרטני של כל שירות בנפרד.

### למה זה לא תוקן במקום — צריך החלטת מוצר, לא רק תיקון-קוד
- תיקון ה-type-comparison לבד **לא מספיק** — יהפוך "נתונים ברור-שגויים" (אפסים, "Unknown") ל"נתונים סבירים-אבל-שגויים" משתי מערכות שעדיין לא יתאמו זו לזו. זה מסוכן יותר, לא פחות.
- הפתרון הנקי (retire את `/reports`'s balance-sheet/P&L + `DataSyncService`, או מחיקת השורות הקיימות) הוא פעולה הרסנית על נתוני-פרוד קיימים → כלל-העצירה (א) של ה-goal-directive. **לא בוצע ולא יבוצע ללא אישור.**
- האם המערכת המקבילה (`Account`/`Transaction`) הייתה כוונה מוצרית נפרדת (view על בסיס-מזומן, למשל) או קוד-שרד נטוש — שאלת-כוונה שלא ניתן להכריע מהקוד לבד.

### המלצה — עודכן אחרי החלטת המשתמש (2026-07-03)
1. **קצר-טווח, לא-הרסני — בוצע ✅**: `run_post_sync_tasks` כבר לא קורא ל-`DataSyncService.sync_all()` (commit 2a052d1, פרוס בפרוד, מאומת חי: sync אמיתי לא הוסיף שורות חדשות ל-`transactions`). מונע החמרה נוספת; לא נוגע בנתונים קיימים.
2. **ארוך-טווח — עדיין פתוח (Task #7)**: להחליט retire מול repair מול "זו כוונה מוצרית" — עכשיו כשידוע שההשפעה משתרעת על 8-9 יכולות (כולל KPI dashboard, AI insights, תקציב, תחזית תזרים, ניתוח עלויות, מקדמות מס), לא רק `/reports`. אם retire — מחיקת השורות הקיימות טעונה אישור מפורש (הרסני).
3. עד להחלטה: `/reports`'s balance-sheet/P&L, וכל 8-9 היכולות שברשימה בסעיף 6, **אינם אמינים** ואסור להשתמש בהם לדיווח אמיתי — `/ledger` ו-`/dashboard/pnl` הם מקור-האמת הנכון כרגע.

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
7. ~~**AP discount fields hardcoded 0** + פרטי-בנק dummy ב-bank-reconciliation~~ — **AP discount**: בוטל אחרי אימות — אין מקור-נתון אמיתי לתנאי-הנחת-ספק בשום מקום במערכת (honest-null מכוון, לא באג). **bank-reconciliation dummy**: **תוקן 2026-07-04** — `ap_service.run_bank_reconciliation()` היה מחזיר `bank_name='בנק לאומי'`+`account_number='12-345-67890'` קבועים בכל דוח; הוסר ל-`Optional[str]=None` (אין מקור אמיתי בקלט הפונקציה). ה-route היחיד שקורא לזה כבר החריג את שני השדות מהתשובה — אפס חשיפה חיה, אבל מוקש לכל קורא עתידי. (יכולת 2)
8. **ניכוי ספקים (856) מחזיר ריק** + ח.פ hardcoded ב-`TaxComplianceService`. (יכולת 11)
9. **יתרות פתיחה ביומן/מאזן** — carry-forward מתקופות קודמות. (יכולת 5)
10. **`date_trunc` על SQLite** (`forecasting_service.py:678-710`) — נכשל מקומית/בטסטים, **עובד ב-prod Postgres**. באג נאמנות-טסט, לא חוסם-פרודקשן. תיקון: ביטוי portable (strftime/extract לפי dialect).
11. **`ComplianceAuditService` (`compliance_audit.py`) — שירות-שלד מזויף לגמרי** (נמצא 2026-07-04). חשוף חי ב-6 routes אמיתיים (`/api/audit/log-change`, `/api/audit/trail`, `/api/tax/report-1301`, `/api/tax/report-1214`, `/api/audit/export`, `/api/audit/compliance-checklist`) — כל מתודה מחזירה נתון קבוע/ריק; `compliance_checklist()` תמיד מחזיר "100% תואם, מוכן-לייצוא-ביקורת" ללא קשר למצב בפועל. **אפס חשיפה חיה כרגע** (נבדק ב-grep — אין קורא frontend לאף אחד מ-6 ה-routes). תיקון אמיתי דורש 6 יכולות נפרדות, חלקן כפולות ל-`annual_report_service.py`'s (1301/1214 טיוטה אמיתית כבר קיימת שם) — היקף גדול מדי לתיקון בודד; דורש החלטה: לבנות-מחדש בכנות מול לפרק/למחוק את ה-routes המתים. (יכולת 3 — הנהלת חשבונות כפולה, בהרחבה לביקורת/ייצוא)

## P1/P2 — העשרות שעברו שער-ביקורת (8 מתוך 28 מועמדות)
> מבוססות על מחקר ה-skills הישראליים + מערכות OSS, **כל אחת אומתה כלא-קיימת ותואמת-אופי**.

| המלצה | יכולת | חומרה | מאמץ |
|-------|-------|-------|------|
| **workflow גבייה מתמשך** — לשמר `collection_status` כ-state, לעקוב אחר ניסיונות (תאריך/אמצעי/promise-to-pay), לחבר ל-alert_engine ו-DSO | AR | P1 | M |
| **Open Finance provisional staging** — `is_provisional` ב-`BankTransaction`; OF→provisional; סינון ב-reconciliation; תווית UI | בנק | P1 | M |
| **מנגנוני ניכוי הוצאה** — רכב (ק"מ), בית (% שכ"ד), טלפון/אינטרנט (%) לפי פקודת מס הכנסה | הוצאות | P1 | M |
| **ייצוא מע"מ PCN874 (מבנה אחיד)** — fixed-width רשמי במקום pipe-delimited; דגל zero-rated/Eilat. **המשך מחקר 2026-07-04**: התקנתי poppler (חסם קודם) וחזרתי לחפש את המפרט הרשמי. **תיקון חשוב לניסוח הפריט עצמו**: "PCN874" ו"מבנה אחיד" **אינם אותו דבר** — PCN874 הוא קובץ-הסיכום התקופתי (חודשי/דו-חודשי) להגשת דיווח מע"מ מקוון; "מבנה אחיד" הוא פורמט-ביקורת נפרד ורחב יותר (INI.TXT+BKMVDATA.TXT, סוגי-רשומה A100/Z900/C100/D110/D120/B100/B110/M100) שרשות המסים דורשת ליכולת-הפקה בעת ביקורת מחשוב חשבונות — לא קשור להגשת מע"מ עצמה. **מצאתי ואימתתי** את המפרט הרשמי המדויק של "מבנה אחיד" — רשות המסים בישראל, מחלקת ביקורת ממוחשבת, גרסה 1.31, 01/05/2009: https://www.gov.il/BlobFolder/service/registration-software-designed-managing-computerized-accounting-system/he/Service_Pages_Income_tax_horaot-131.pdf — כולל טבלאות שדה-מדויקות (מספר-שדה/סוג/אורך/עמודות-התחלה-סוף) לכל רשומה, קריא ומדויק אחרי התקנת poppler (`brew install poppler`, נדרש כדי ש-PDF ירונדר לתמונה קריאה). לא נשמר בריפו — `*.pdf` ב-`.gitignore` גורף, בכוונה לא נעקף; יש להוריד מחדש מה-URL למי שממשיך. זה **לא** הפורמט של PCN874 עצמו. מפרט PCN874 האמיתי (הפורמט הספציפי לדוח המע"מ התקופתי) עדיין לא אותר במקור קריא-מכונה (רק מדריכי-משתמש של ספקי תוכנה, לא spec רשמי). **מסקנה**: אם יתבצע מימוש עתידי, "מבנה אחיד" מוכן-למימוש (spec אמיתי בידיים, feature נפרד וגדול — ביקורת-חשבונות, לא דיווח-מע"מ); PCN874 עדיין דורש איתור spec נוסף לפני מימוש. שני הפריטים **לא מומשו** בסבב הזה — מומלץ תכנון TDD ייעודי נפרד לכל אחד, לא ניחוש. | מע"מ | P1 | M |
| **ריבית חוק מוסר תשלומים** — **נחקר 2026-07-04, לא מומש, שיעור-הריבית המקורי מוטל בספק**: חיפוש בסיסי מצביע על כך שהריבית הרלוונטית לפי "חוק מוסר תשלומים לספקים, תשע"ז-2017" (מפנה ל"חוק פסיקת ריבית והצמדה") היא **ריבית פריים + 6.5%**, לא "Prime+2%" כפי שנוסח כאן במקור — פער משמעותי, לא רק ניסוח. **לא מומש בכוונה**: זהו חישוב שמשפיע בפועל על סכום שעסק אמיתי גובה מלקוח אמיתי — טעות בשיעור הריבית היא טעות משפטית/כספית ממשית, לא קוסמטית. לפני מימוש: לוודא את השיעור המדויק ישירות מול נוסח החוק (https://www.nevo.co.il/law_html/law00/144599.htm) ו/או עורך דין/רואה חשבון, לא מול חיפוש-רשת בלבד. | AR | P2 | M |
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
