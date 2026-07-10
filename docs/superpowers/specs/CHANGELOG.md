# CHANGELOG — הקשחת פלטפורמת CFO

יומן שינויים מגורסן לפי פאזה. נועד להמשכיות בין סוכנים: כל רשומה מתעדת מה השתנה,
למה, אילו קבצים, אילו בדיקות, ותוצאת שער האימות. ראה גם:
- `SYSTEM_STATE_v1.0.md` — snapshot as-is (baseline).
- `2026-06-24-platform-hardening-design.md` — תכנון מלא (12 פאזות) + מטריצת SUMIT.

---

## v1.7 — פאזות 6/7/8: פקודות יומן ידניות, scheduler ל-OCR, התאמה ידנית (2026-06-24)

**סטטוס:** ✅ ליבות הושלמו. שער: `pytest` 305 passed.

### פאזה 6 — API פקודת יומן ידנית (ledger)
- `ledger_service.add_manual_entry` — פקודת יומן ידנית מאוזנת (Σחובה==Σזכות, ≥2 שורות, חשבון לכל שורה); נשמרת ב-`JournalEntry(source='manual')` ונכללת אוטומטית ב-`build_journal`/`trial_balance` (פונקציה `_manual_entries`). route `POST /ledger/entries`.
- בדיקות: `tests/test_manual_journal_entry.py` (unit + route; דחיית לא-מאוזן).
- *הערה: commit זה נבלע ב-`b1b0d01` יחד עם פאזה 7/8 (סוכן ביצע `git add -A`).* 

### פאזה 7 — קליטת מסמכים (commit b1b0d01)
- `ExpenseOCRScheduler.run_scheduled_ocr` — הרצת OCR מתוזמנת על טיוטות SUMIT pending; כיבוד חלון 6 חודשים, סף ביטחון (auto-file רק בביטחון גבוה), backoff. route `/api/cron/process-ocr`.
- לולאת למידה לסיווג: עמודה `Expense.classifier_feedback` (JSON) לתיעוד תיקוני סיווג (audit ל-ML עתידי).

### פאזה 8 — התאמות בנק ידניות (commit b1b0d01)
- `ManualReconciliationService` + routes `/api/reconcile-manual/*` (match/unmatch/unmatched/suggestions/feedback); הצעות מבוססות-`bank_reconciliation._score` הקיים; התאמה ידנית מאפסת dispatch ל-re-dispatch אופציונלי.

### תיקון נכונות שנוסף בסקירה
- **migration חסר**: הסוכן הוסיף עמודה `classifier_feedback` ל-models אך ללא alembic migration → היה קורס מול cfo.db האמיתי. נוסף `alembic/versions/5f6a7b8c9d0e_add_expense_classifier_feedback.py` והעמודה הוחלה על cfo.db.

### נותר (פאזות 6-8)
- פאזה 6: רישום שכר→ledger, פחת, מצב חד-צידי (עוסק פטור).
- פאזה 7: קליטה במייל/טלפון (תשתית), חשבונית עצמית.
- פאזה 8: כרטיסי אשראי/שיקים ייעודי.

---

## v1.6 — פאזה 1 (הקשחה): סינון מסמכים לפי status (2026-06-24)

**סטטוס:** ✅ הושלם. שער: `pytest` 292 passed; אומת על cfo.db.

### באג סמוי שנתפס (בעקבות סקירת advisor + אימות נתונים)
מסמכים שאינם סופיים נספרו כהכנסה/הוצאה/מע"מ: חשבונית `cancelled/void/draft`, ספק `void/draft`, והוצאה `pending` (טיוטת קבלה לא מתויקת — ראה memory על 150 הטיוטות). מסמך מבוטל ניפח דוחות ודיווח מע"מ.

### תיקון
- `vat_utils.py`: predicates משותפים — `invoice_counts`, `bill_counts`, `expense_counts` (חשבונית: לא draft/void/cancelled; ספק: לא draft/void; הוצאה: רק filed).
- יושמו ב-**5 המקומות** (מקור אמת אחד): `financial_reports_service` (revenue/expense/cashflow), `tax_service._get_vat_transactions`, `financial_synthesis.compute_vat_position`.
- בדיקות: `tests/test_status_filtering.py` (P&L + שני מנועי מע"מ מחריגים מבוטל/pending).

### אימות נתונים אמיתיים
- org2 revenue 185k נכון: 1.64M מהמסמכים הם **2025** (מחוץ לתקופת 2026); אין חשבוניות מבוטלות.
- P&L ללא שינוי אחרי הסינון (ה-pending היו בסכום 0). שני מנועי המע"מ עדיין מסכימים.
- **balance sheet `is_balanced=False`** על נתונים אמיתיים — ישר ומכוון: הדוח נושא `derived:true`+disclaimer. איזון מלא (יתרות פתיחה/דו-צדדי) → פאזה 6.

---

## v1.5 — פאזה 5: היגיינת repo וסודות (2026-06-24)

**סטטוס:** ✅ הושלם (אימות; הסיכון הקריטי היה אזעקת שווא).

### ממצא (אומת מול git, מתקן את האודיט)
- **`cfo.db`, `.env.local`, `*.bak` אינם בהיסטוריית git ואינם במעקב** — בניגוד לטענת האודיט. `git log --all --name-only` לא מצא אותם; `git ls-files` לא מציג אותם. **אין צורך בשכתוב היסטוריה.**
- `.gitignore` כבר מכסה: `.env`, `.env.local`, `.env*.local`, `*.db`, `*.bak`, `cfo.db.*.bak`, `.vercel`.
- קבצי env במעקב הם templates/ציבוריים בלבד: `.env.example`, `.env.template`, `frontend/.env.example`, `frontend/.env.production` (רק `VITE_*` ציבורי — אין סודות).
- `.vercel/` אינו במעקב.

### נדחה (דורש אימות פריסה, לא בוצע חד-צדדית)
- איחוד מקורות תלויות (`requirements.txt` + `requirements-full.txt` + `pyproject.toml` + `uv.lock`) — שינוי משפיע על build/deploy של Vercel; דורש אימות פריסה לפני ביצוע. המלצה בלבד.
- ארכוב docs מיושנים (קוסמטי).

---

## v1.4 — פאזה 3 (חלקי): השלמת מודול המס (2026-06-24)

**סטטוס:** 🟡 ליבה. שער: `pytest` 290 passed.

### מה תוקן
- **`tax_service.__init__`** — ח.פ (`company_vat_number`) נטען דינמית מ-`Organization.tax_id` במקום הקשיח `'123456789'`. נדרש לזהות נכון בייצוא SHAAM (filename/header/XML). fallback `'000000000'` רק אם חסר.
- **`tax_service._get_annual_profit_estimate`** — חושב מ-P&L מבוסס-ledger (`FinancialReportsService`) במקום מטבלת `Transaction` (שהייתה אפס לארגוני ledger). עקבי עם פאזה 1.
- בדיקות: `tests/test_tax_vat_number_dynamic.py`.

### נותר בפאזה 3
- מעקב תשלומי מקדמות (`_get_previous_payments` עדיין מחזיר 0) — דורש טבלת רישום תשלומים.
- לוח שנת מס מחושב (סכומים קשיחים 15000/8000/25000).
- ייצוא SHAAM מלא end-to-end (כעת עם ח.פ נכון; נדרש אימות מבנה מול שע"מ).

---

## v1.3 — פאזה 4: ייצוב routes (date_trunc על SQLite) (2026-06-24)

**סטטוס:** ✅ ליבה הושלמה. שער: `pytest` 289 passed; `audit_routes.py` 47→40 כשלים (121 OK, היה 116).

### מה תוקן
- **`forecasting_service`** — `_get_monthly_revenue`/`_get_monthly_expenses` השתמשו ב-`func.date_trunc('month', ...)` שאינו קיים ב-SQLite → `OperationalError` שהפיל את כל `/api/cashflow/forecast/*`. הוחלף ב-`_monthly_totals` (אגרגציה ב-Python, ניטרלית-dialect), המחזיר `date` כ-datetime (ראשון לחודש) לשמירת חוזה ה-route (`r.date.strftime`).
- אומת: 5 routes של `/api/cashflow/forecast/*` עברו מקריסה ל-200.
- NaN/חלוקה-באפס שהאודיט סימן (`mape`, `r2`, `revenue_growth`) — נמצאו **כבר מוגנים** בקוד (`np.all(actual != 0)`, `ss_tot != 0`, `revenue_values[0] > 0`).

### מצב audit שנותר (לא קריסות)
- 4 EXC נותרו, כולם `/api/sync/sumit/*` — `ValueError: SUMIT API key not configured` (צפוי בסביבת audit ללא מפתח; בפרודקשן מוגדר).
- ~36 × 400 — Open Finance/CRM/communications/payments דורשים credentials/params (התנהגות תקינה, לא 5xx).
- QA 2026-06-30: אומת מול production. `DATABASE_URL` קיים ומצביע ל-Postgres מנוהל; `sumit:ping` עובר; Open Finance חסום נקי עם 400 עד להגדרת `OPEN_FINANCE_USER_ID`.

### נותר בפאזה 4 (ongoing)
- המרת ValueError של SUMIT ל-400 נקי (polish).
- הרחבת כיסוי בדיקות ל-19 ה-route modules ללא בדיקות (נוספו בדיקות ממוקדות; כיסוי מלא = מאמץ נמשך).
- בדיקות: `tests/test_forecasting_sqlite.py`.

---

## v1.2 — פאזה 2: החלפת נתוני Mock שדולפים למשתמש (2026-06-24)

**סטטוס:** ✅ הושלם. שער: `pytest` 288 passed / 0 failed (+16 בדיקות מ-baseline 272).

### ReportBuilder + AI (השלמת הפאזה)
- **`report_builder_service`** — `_execute_report_query` וארבעת ה-`_generate_*` נותבו לשירותים האמיתיים (org-scoped): P&L→`FinancialReportsService`, גיול→`AccountsReceivableService`, KPI→`KPIService`, תקציב→`BudgetService`. כשל → `[]` + לוג (לא random). הוסר כל `import random`.
- **`ai_analytics_service._get_transactions`** — הוסר ה-stream המזויף (50 תנועות random); זיהוי חריגות רץ על `Transaction` אמיתי (תאריך-בלבד למניעת קריסת parsing ב-route).
- **`ai_analytics_service.AIRecommendation`** — שדה `is_illustrative=True`: ההמלצות הקשיחות מסומנות ביושר כתבניות לדוגמה (לא data-derived). מימוש אמיתי → פאזה 11.
- בדיקות: `test_report_builder_real.py`, `test_anomalies_real_source.py` (2), `test_ai_recommendations_flagged.py`. אומת גם דרך `test_all_financial_get_routes_no_crash`.

### מה תוקן (silent random)
- **`budget_service._get_actual_by_category`** — באג חי: השתמש ב-`Transaction.date` (שדה לא קיים) → זרק תמיד → נפל ל-`_get_sample_actuals` (random). כלומר *תקציב מול ביצוע היה 100% מזויף לכל ארגון*. תוקן ל-`transaction_date`, הוסר ה-fallback האקראי השקט (כשל → `{}` + לוג), ונמחקה `_get_sample_actuals` המתה.
- **`financial_reports_service.generate_cash_flow_projection`** — הוסר רעש אקראי ±5%/±3%; המקור הוסט מ-`Transaction` (ריק לארגוני ledger) ל-מסמכי ledger בברוטו (תנועת מזומן בפועל). עונתיות מחושבת מהכנסות חודשיות. מתודות עזר: `_ledger_cash_aggregates`, `_seasonality_from_monthly`.

### בדיקות חדשות
- `tests/test_budget_actuals_real.py` (2), `tests/test_cashflow_ledger_sourced.py` (2).

### נותר בפאזה 2
- `report_builder_service._generate_*` (P&L/גיול/תקציב/KPI אקראיים) → ניתוב לשירותים האמיתיים.
- `ai_analytics_service`: anomalies (stream מזויף) + recommendations (5 קשיחות) → חישוב אמיתי או סימון מפורש כ-demo.

---

## v1.1 — פאזה 1: תיקון שורש נכונות המע"מ והחשבונאות (2026-06-24)

**סטטוס:** ✅ הושלם. שער: `pytest` 280 passed / 0 failed (baseline 272 → +8 בדיקות).
אומת על **נתונים אמיתיים** (cfo.db): org 2 כבר לא ריק (revenue ₪185k), org 1 ללא ספירה כפולה, ושני מנועי המע"מ מסכימים (org1 net −45,668.95; org2 net 7,157.04).

### מה השתנה ולמה
מקור האמת לדוחות הוסט מטבלת `Transaction` (כוללת מע"מ, מנופחת, מקור לספירה כפולה)
לשכבת ה-ledger (`Invoice/Bill/Expense`) עם סכומי נטו מפוצלי-מע"מ — מקור אמת אחד
המתכנס עם `financial_synthesis.compute_vat_position`.

תובנת נתונים שהנחתה את התיקון (cfo.db, 2026-06-24): org 2 הוא ledger-only
(0 transactions → דוחות היו ריקים), ו-org 1 סבל מספירה כפולה (100/101 transactions
היו הד-מסמך). התיקון פותר את שניהם בלי backfill.

### שינויי קוד
- `src/cfo/services/financial_reports_service.py`:
  - `generate_profit_loss` — הכנסה=`Invoice.subtotal` (נטו), הוצאה=`Bill.subtotal`+`Expense.amount` (נטו, מגניטודה חיובית). מתודות עזר חדשות: `_ledger_revenue_items`, `_ledger_expense_items`, `_items_from_sums`, `_net_of`, `_doc_date`.
  - שילוב פקודות יומן ידניות בלי לאבד ובלי לכפול: `_manual_sums` + `_ledger_external_ids` מדלגים על Transaction שהוא הד-מסמך (external_id תואם ledger).
  - `generate_balance_sheet` — עודפים נגזרים מרווח נקי מצטבר (`generate_profit_loss` מאז ומתמיד), לא plug שמכריח `is_balanced=True`.
- `src/cfo/services/tax_service.py`:
  - `_get_vat_transactions` — קורא `Invoice.tax`/`Bill.tax`/`Expense.vat_amount` אמיתיים; סיווג חייב/פטור לפי נוכחות מע"מ (במקום אומדן 18% שטוח מ-Transaction).
  - `generate_vat_report` — `output_vat` מסתכם ממע"מ אמיתי, לא `net×18%`.
- `src/cfo/services/data_sync_service.py`:
  - `sync_documents` — סומן DEPRECATED + אזהרת לוג (כותב Transaction מנופח). ריטייר מלא (מעבר route ה-sync ל-SyncEngine) → פאזה 6. אין ספירה כפולה בפלט כי הדוחות מדלגים על הד-מסמך.

### בדיקות חדשות
- `tests/test_reports_ledger_sourced.py` (6): הכנסה נטו, הוצאה נטו, שילוב פקודה ידנית, אי-ספירה-כפולה של הד-מסמך, דוח מע"מ משדות אמיתיים, עודפים=רווח נקי.
- `tests/test_cost_tax_ai_real.py::test_vat_report_real` — עודכן לזרוע מסמכי ledger עם מע"מ מפורש (במקום אומדן 18% מ-Transaction).

### נדחה במכוון (לא בפאזה 1)
- `generate_cash_flow_projection` עדיין קורא מ-`Transaction` + מזריק רעש אקראי → **פאזה 2** (אותה מתודה, יחד עם הסרת הרעש).
- מאזן מלא דו-צדדי (חשבונות/יתרות פתיחה אמיתיים) → **פאזה 6** (מנוע הנה"ח כפולה).
- סייג פטור/אפס: ללא דגל מפורש מ-SUMIT, מסמך ללא מע"מ מסווג 'פטור' (לא 'אפס') — תיעוד ב-`vat_utils.py`.

### למשך (פאזה הבאה)
פאזה 2 — החלפת נתוני Mock שדולפים למשתמש (ReportBuilder/AI/budget-fallback) + תיקון `generate_cash_flow_projection` (ledger + הסרת רעש).
