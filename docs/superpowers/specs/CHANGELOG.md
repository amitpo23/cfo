# CHANGELOG — הקשחת פלטפורמת CFO

יומן שינויים מגורסן לפי פאזה. נועד להמשכיות בין סוכנים: כל רשומה מתעדת מה השתנה,
למה, אילו קבצים, אילו בדיקות, ותוצאת שער האימות. ראה גם:
- `SYSTEM_STATE_v1.0.md` — snapshot as-is (baseline).
- `2026-06-24-platform-hardening-design.md` — תכנון מלא (12 פאזות) + מטריצת SUMIT.

---

## v1.2 — פאזה 2 (חלקי): הסרת נתוני random מסוכנים (2026-06-24)

**סטטוס:** 🟡 בתהליך. שער: `pytest` 284 passed / 0 failed (+4 בדיקות).

### מה תוקן עד כה
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
