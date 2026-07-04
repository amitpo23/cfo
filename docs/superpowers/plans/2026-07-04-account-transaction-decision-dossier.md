# החלטת Account/Transaction (P0) — דוסייה מרוכזת להחלטה

> נכתב 2026-07-04 עבור סוכן/משתמש שממשיך את העבודה. מטרת המסמך: לאפשר
> להחליט repair/retire/hybrid **בלי** לחקור מחדש — כל טענה כאן מאומתת מול
> הקוד הנוכחי (לא מסתמכת על ניסוח קודם ב-`PRODUCT_AUDIT_AND_ROADMAP.md`,
> שחלק ממנו התברר מיושן — ר' "מה כבר לא נכון" למטה).

## TL"ד

יש שתי מערכות דיווח מקבילות: `Account`/`Transaction` (קפואה, לא גדלה
מ-2026-07-03) מול `Invoice`/`Bill`/`Expense`/`Payment` ("ה-ledger", אמיתית,
גדלה בכל sync). **הכיוון הארכיטקטוני כבר ברור מההיסטוריה של הקוד עצמו** —
לא שאלה פתוחה של "מה כדאי": `financial_reports_service.py`'s
`generate_profit_loss`, כל `tax_service.py`, `ledger_service.py`,
`ar_service.py`, `ap_service.py` כבר עברו ל-ledger (חלקם מתועדים "פאזה 1",
חלקם תוקנו הפעם). מה שנשאר תלוי ב-`Transaction` הם **שאריות שלא הועברו**,
לא כוונה מוצרית מקבילה. יש גם תוכנית קיימת ומתועדת ("פאזה 6" — ר'
`docs/superpowers/specs/2026-06-24-platform-hardening-design.md`) שמייעדת
ריטייר מלא.

**המלצה**: retire, לא repair — להשלים את המעבר של 5-6 הצרכנים שנשארו
(רשימה מדויקת למטה), לא לתחזק שתי מערכות במקביל לנצח. זו לא "אולי" — זו
המשך ישיר של מגמה שכבר התחילה ותועדה.

**מה כבר טופל הפעם** (לפני כתיבת המסמך הזה): נמצא ונסגר **סיכון-חי אמיתי** —
`POST /api/sync/sumit/full` והשלושה ש"מלאים" אותו עדיין כתבו בפועל ל-
`Transaction` בכל קריאה, ללא שום חסם קוד (רק "אין UI שקורא לזה כרגע").
תוקן ב-commit `85fb09c`: 4 השיטות זורקות `LegacySyncRetiredError`→400 כן
במקום להריץ בשקט. **בלי התיקון הזה, כל קריאה ישירה (script/Postman/UI
עתידי) הייתה מחזירה את כל הבעיה הזו לחיים.**

---

## 1. מה קפוא בפועל עכשיו — טבלה מדויקת (מאומתת קוד, 2026-07-04)

| # | צרכן | Route חי | מוצג ב-UI? | מקור-נתון |
|---|------|----------|-----------|-----------|
| 1 | `BudgetService._get_actual_by_category` | `/api/financial/budget/vs-actual` | כן — `BudgetDashboard.tsx:51` | 🔴 קפוא (`Transaction`) |
| 2 | `CashFlowService` (monthly/daily/burn-rate/liquidity) | `/cashflow/monthly`, `/daily`, `/burn-rate`, `/liquidity-ratios` | כן — `CashFlowDashboard.tsx` (נוסף ל-nav ב-`/cashflow-detail`) | 🔴 קפוא |
| 3 | `ForecastingService._monthly_totals` | `/cashflow/forecast/revenue`, `/expenses`, `/cash-flow`, `/trends`, `/ml/ensemble`, `/accuracy` | כן — `ForecastingDashboard.tsx` | 🔴 קפוא |
| 4 | `AdvancedAIService.detect_anomalies` | `/api/financial/ai/anomalies` | כן — `AIAnalyticsDashboard.tsx` טאב "anomalies" | 🔴 קפוא |
| 5 | `alert_engine._check_large_transactions` | (פנימי, לא route ישיר) | כן — סוג-התראה כללי ב-`CFOAlertsTasks.tsx` | 🔴 קפוא — לא יכול לירות שוב על פעילות חדשה |
| 6 | `financial_reports_service.generate_balance_sheet` | `/api/reports/balance-sheet` | כן — `/reports` | 🟡 **מעורב**: assets/liabilities קפואים, אבל `retained_earnings` כבר אמיתי (קורא ל-`generate_profit_loss`) — **זה כנראה הגורם המכני הישיר לפער -503,734 מול -24,634 שתועד ב-2026-07-03** |
| 7 | `generate_cash_flow_projection`'s `opening_balance` fallback | `/api/reports/cash-flow-projection`, `/api/reports/summary` | כן | 🟡 רק ה-fallback קפוא; ה-caller החי אף פעם לא מעביר `opening_balance`, אז ה-fallback יורה בכל קריאה אמיתית |

### מה **כבר לא נכון** מהניסוח הישן ב-`PRODUCT_AUDIT_AND_ROADMAP.md`
- `generate_profit_loss()` (`/api/reports/profit-loss`) **כבר עבר ל-ledger
  לגמרי** — כולל פקודות-יומן ידניות ללא מסמך-מקור (`_manual_sums()`, לא
  `_manual_journal_items` כפי שההערה הישנה בקוד טענה — שם-פונקציה שגוי
  בהערה, לא פער תפקודי). שאילתת ה-`Transaction` שנשארה שם היא מתה
  (נשלפת, לא נעשה בה שימוש) — ניקוי-קוד לא מזיק, לא באג.
- `kpi_service.py` **לא** שואל `Transaction` יותר כלל (תוקן הפעם, honest-null
  ב-`b8581bd`).
- `tax_service.py`'s `calculate_tax_advance`/`get_tax_calendar` **כבר**
  עברו ל-ledger הפעם (`0c66f07`).

---

## 2. שורש-הבעיה — מדויק, לא רק "יש שתי מערכות"

1. `run_post_sync_tasks` הפסיק לקרוא ל-`DataSyncService.sync_all()`
   (commit `2a052d1`, מאומת — `Transaction`/`Account` לא גדלים יותר
   דרך הנתיב הזה).
2. **אבל** עד ל-commit `85fb09c` (היום), `POST /api/sync/sumit/full`
   ושלושת ה-routes הישירים (`documents`/`payments`/`billing`) עדיין
   קראו בפועל ל-`DataSyncService.sync_documents/sync_payments/
   sync_billing_transactions`, שכל אחת מהן כותבת שורת `Transaction`
   VAT-inclusive לכל מסמך/תשלום/עסקת-סליקה חדשים מ-SUMIT. שום דבר
   בקוד לא חסם את זה — ה"הקפאה" הייתה נסיבתית (ה-UI היחיד שקרא לזה,
   `DataSyncDashboard.tsx`, יתום לגמרי מ-`App.tsx`), לא אכיפה. **זה
   כבר תוקן** (ר' TL"ד).
3. Balance sheet (`generate_balance_sheet`) קורא ישירות ל-`Account.balance`
   + `Transaction` עבור assets/liabilities (`_calculate_account_balances`),
   אבל קורא בנפרד ל-`generate_profit_loss` (ledger-based) עבור
   `retained_earnings`. שני מקורות-נתון שונים לגמרי, מוזגים לדוח אחד —
   זה ההסבר המכני לפער התוצאות שתועד ב-2026-07-03, לא תעלומה.

---

## 3. שתי האופציות — היקף עבודה אמיתי

### אופציה A — Repair (להחיות מחדש את `Account`/`Transaction`)
- דורש להחזיר קריאה ל-`DataSyncService.sync_all()` (או שקול) לתוך
  `run_post_sync_tasks`, ולתקן את איכות-הנתון (הפייפליין הישן כותב
  `amount=doc.total` **כולל מע"מ**, בלי `is_provisional`/קישור-מסמך
  בסגנון ה-ledger).
- לא באמת יותר בטוח מ-retire — מנציח שתי מערכות שצריכות להישאר
  מסונכרנות לנצח, וההערכה שלנו (ושל תיעוד-הפרויקט הקיים, "פאזה 6")
  היא ש-repair לא היה הכיוון המתוכנן מלכתחילה.
- **לא מומלץ.**

### אופציה B — Retire (להשלים את המעבר ל-ledger)
כל אחד מהצרכנים בטבלת סעיף 1 (השורות ה-🔴/🟡) צריך גרסה מבוססת-ledger,
**באותה צורה בדיוק** כמו התיקון שנעשה הפעם ל-`tax_service.py`'s
`get_tax_calendar` (שאילתת Invoice/Bill/Expense/Payslip אמיתית במקום
Transaction):

| צרכן | מה נדרש |
|------|---------|
| `BudgetService._get_actual_by_category` | לבנות actuals-לפי-קטגוריה מ-Invoice/Bill/Expense (יש כבר תקדים ב-`financial_reports_service._ledger_expense_items`) |
| `CashFlowService` (4 endpoints) | לבסס מחדש על `Invoice`/`Bill`/`Payment`/`BankTransaction` |
| `ForecastingService._monthly_totals` | אותו דבר — היסטוריית הכנסות/הוצאות מה-ledger במקום Transaction |
| `AdvancedAIService.detect_anomalies` | להזין feed דמוי-transaction מ-`BankTransaction`+`Invoice`/`Bill`/`Expense` ממוזגים |
| `generate_balance_sheet` | **הכי משמעותי** — צריך לוגיקת מאזן אמיתית מבוססת-ledger (מזומן/לקוחות/ספקים/מלאי מ-Invoice/Bill/Payment/Expense/BankTransaction), לא רק תיקון-שדה |
| `generate_cash_flow_projection`'s `opening_balance` | לגזור "מצב-מזומן נוכחי" אמיתי מ-`BankTransaction`/`Payment` במקום `Account.balance` |

**כל זה עבודה תוספתית (additive)** — שאילתות חדשות מול טבלאות שכבר
מאוכלסות (Invoice/Bill/Expense/Payment/BankTransaction), **לא** נגיעה
או מחיקה של שורות `Transaction`/`Account` קיימות. **לא נכנס לקטגוריית
"הרסני"** תחת כלל-העצירה של הפרויקט. ה-חלק ההרסני היחיד יהיה **מחיקת**
שורות ה-`Transaction`/`Account` הישנות בפרוד אחרי שהמעבר שלם — זה כן
דורש אישור מפורש חד-פעמי, בנפרד מהמעבר עצמו.

קוד-מת שאפשר למחוק כבר עכשיו (ללא תלות בהחלטה, אפס סיכון):
`financial_service.py`/`report_service.py`/`ai_insights.py` (שרשרת יתומה
לגמרי — לא מיוצרת משום מקום), ו-`DataSyncDashboard.tsx` (יתום מ-`App.tsx`,
מפנה עכשיו לנתיבים חסומים ממילא).

---

## 4. המלצה מסכמת

1. **retire, לא repair** — ההיסטוריה של הקוד עצמו כבר בחרה בכיוון הזה;
   העבודה שנותרה היא להשלים 6 צרכנים, לא לפתוח דיון ארכיטקטוני חדש.
2. סדר עדיפויות מוצע (מהכי-משפיע להכי-פחות): `generate_balance_sheet`
   (מקור לפער-מספרים מבלבל שמשתמש אמיתי רואה) → `BudgetService` (יש
   route חי מרונדר) → `CashFlowService`/`ForecastingService` (יש nav
   items ייעודיים) → `detect_anomalies` (טאב אחד בדשבורד).
3. אחרי שכל 6 מועברים: מחיקת קוד-מת (הרשימה בסעיף 3) — אפס סיכון.
4. **מחיקת שורות `Transaction`/`Account` הישנות בפרוד** — צעד נפרד,
   הרסני, דורש אישור מפורש. לא לבצע כחלק מ-1-3.
5. עד להחלטה/ביצוע: כל 6 היכולות בטבלת סעיף 1 **אינן אמינות לדיווח
   אמיתי** — זה כבר היה נכון לפני המסמך הזה, לא משהו חדש.

---

## קבצים רלוונטיים
- `src/cfo/services/financial_reports_service.py` — `generate_profit_loss`
  (תקין, ledger), `generate_balance_sheet` (מעורב, שורה 308+),
  `generate_cash_flow_projection` (שורה 426+)
- `src/cfo/services/budget_service.py:581` (`_get_actual_by_category`)
- `src/cfo/services/cash_flow_service.py`
- `src/cfo/services/forecasting_service.py:695` (`_monthly_totals`)
- `src/cfo/services/ai_analytics_service.py:776` (`_get_transactions`)
- `src/cfo/services/alert_engine.py:156` (`_check_large_transactions`)
- `src/cfo/services/data_sync_service.py` — עכשיו חסום, ר' `LegacySyncRetiredError`
- תיעוד-מקור: `docs/PRODUCT_AUDIT_AND_ROADMAP.md`'s "ממצא חדש (2026-07-03)"
- תוכנית קיימת: `docs/superpowers/specs/2026-06-24-platform-hardening-design.md`'s "פאזה 6"
