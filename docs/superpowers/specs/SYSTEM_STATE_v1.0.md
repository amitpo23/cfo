# תיעוד מצב המערכת — CFO Platform

**גרסה:** 1.0
**תאריך:** 2026-06-24
**ענף:** feat/sumit-ar-ap-documents-ocr
**שיטה:** תשחקור משולש מאומת מול הקוד (לא הצהרות — file:line).
**מטרה:** snapshot "as-is" של היכולות הקיימות, כבסיס להשוואה מול יכולות SUMIT ולתכנון השלמות.

---

## 1. ארכיטקטורה כללית

- **Backend:** FastAPI, Python. `src/cfo` — 58 services, 29 route modules, 5 integrations.
- **Frontend:** React 18 + Vite + TanStack Query + Recharts + Tailwind + TS.
- **DB:** SQLAlchemy ORM; dev על SQLite (`cfo.db`), alembic migrations.
- **אינטגרציות:** SUMIT (חשבוניות/מסמכים), Open Finance (בנקאות פתוחה), OCR pipeline (LLM vision).
- **Multi-tenant:** org-scoped (`organization_id`).

## 2. שכבת נתונים — שני נתיבי סנכרון פעילים (ממצא מרכזי)

| נתיב | קובץ | כותב ל־ | פיצול מע"מ | מי מפעיל |
|------|------|---------|-----------|----------|
| ישן | `data_sync_service.py` | `Transaction.amount = doc.total` (כולל מע"מ) | ❌ | route `sync.py`, `cli.py` |
| חדש | `sync_engine.py` | `Invoice/Bill/Expense` (`subtotal`+`tax`) | ✅ | office/cfo_sync/onboarding/cron |
| בנק | `sync_engine.py` | `BankTransaction` (amount בלבד) | — (אין מע"מ) | Open Finance |

- מודלי `Invoice/Bill/Expense` כוללים `subtotal/tax/vat_amount` (אין צורך ב-migration).
- פקודות יומן ידניות: `financial_service.create_transaction` → `Transaction` בלי מסמך מקור.

## 3. מצב יכולות קיימות (real / hybrid / mock)

### חשבונאות ודוחות
- **P&L / מאזן / תזרים** (`financial_reports_service`): קוראים מ-`Transaction` המנופח (כולל מע"מ) → **שגוי ~15-18%**. מאזן "מאוזן באלגברה" (`is_balanced` תמיד True).
- **מע"מ — שני מנועים סותרים:** `tax_service.generate_vat_report` (אומדן 18% שטוח מ-`Transaction`) מול `financial_synthesis.compute_vat_position` (קורא `tax` אמיתי — **הנתיב הנכון**).
- **דוחות יומיים** (`daily_reports_service`): קיים, עם disclaimer על נגזרת 18%.
- **מנוע הנה"ח כפולה / ledger** (`ledger_service`): קיים חלקית.

### מס
- 1301/1214 (`annual_report_service`): קיים, שיעורי מס קשיחים 2025/2026.
- ח.פ קשיח `'123456789'` (`tax_service:175`); לוח שנת מס קשיח (15000/8000/25000).
- מקדמות: `_get_previous_payments` מחזיר 0 (stub — אין מעקב תשלומים).
- ניכוי מס במקור ספקים: קיים ועובד (`_get_supplier_withholding`).

### קליטת מסמכים / OCR
- `expense_ocr_pipeline` + `vision_extractor`: pipeline אוטומטי (getpdf→ראייה LLM→אימות ח.פ→סיווג→תיוק). אומת חלקית.
- `expense_filing_service`: כותב `Expense` עם vat_amount.

### בנקאות / Open Finance
- אינטגרציה מלאה (`open_finance_client` ~84 מתודות, `open_finance_connector`): תובנות, התאמות, persist payments מ-webhooks. אומת חי.
- `BankTransaction` נשמר; **אין מע"מ** (תקין — מקור בנקאי).
- **התאמות בנק↔מסמכים:** `reconciliation_dispatch` קיים; עומק לא מלא.

### אנליטיקה / AI (רובו mock)
- `report_builder_service`: כל התבניות `random` (P&L/גיול/תקציב/KPI).
- `ai_analytics_service`: anomalies (stream מזויף), recommendations (5 קשיחות), risks (DB אמיתי + ערכים קשיחים).
- `kpi_service`, `cost_analysis_service`: רובם real מ-DB; חוסרים (פחת/ריבית/units).
- `forecasting_service`: `date_trunc` מפיל SQLite; NaN ב-MAPE.

### פלטפורמה
- Onboarding, billing (Stripe + mock dev), CRM, payroll, masav (קובץ מס"ב), payments, inventory, communications.
- 183 GET routes; **47 נכשלים (26%)**; 19 route modules ללא בדיקות; 40% כיסוי קבצים.

## 4. חולשות מערכתיות מתועדות (מתשחקור)

1. מוח-מפוצל בנתוני סנכרון → דוחות שגויים + סיכון ספירה כפולה.
2. נתוני mock דולפים למשתמש (reports/AI).
3. מודול מס לא פונקציונלי לשידור אמיתי (ח.פ קשיח, אין מעקב מקדמות, אין PCN/שידור).
4. 26% routes נכשלים; כיסוי בדיקות נמוך.
5. סודות + DB בהיסטוריית git.

## 5. מה שאין עדיין (לעומת SUMIT — ראה מטריצה במסמך התכנון)

- אין PCN874 / מבנה אחיד; אין שידור ישיר API לרשות המסים.
- אין מנוע התאמות בנק מלא (מהיר+ידני) ברמת SUMIT.
- אין פורטל לקוח/מייצג מלא (גישה חיה + הרשאות בעלים).
- אין ניהול ריבוי-תיקים למשרד הנה"ש.
- אין תכנון מס (אישי/רוחבי/חברות).
- קליטת מסמכים: יש OCR, אין קליטה דרך מייל/טלפון ייעודי וסיווג-לומד מלא.
- הצהרת הון / 6111: חלקי.

---

## 6. מצב הנתונים בפועל (cfo.db, נמדד 2026-06-24)

| טבלה | org 1 | org 2 |
|------|-------|-------|
| invoices | 13 (₪155,320) | 27 (₪1,861,680) |
| bills | 0 | 320 (−₪785,007) |
| expenses | 834 (₪940,808) | 0 |
| transactions | 101 (₪24,635) | **0** |
| bank_transactions | 0 | 0 |

**ממצאים מכריעים:**
- **org 2 הוא ledger-only (0 transactions).** הדוחות שקוראים מ-`Transaction` מציגים **ריק** לארגון הזה כרגע. מעבר ל-ledger מתקן זאת.
- **org 1: 100 מתוך 101 transactions הם כפילויות מסמך** (94 תואמים `expenses.external_id`, 6 תואמים `invoices.external_id`). **ספירה כפולה קיימת ב-DB.** רק תנועה אחת (`בדיקת API`, ₪1) ידנית-אמיתית.
- **אין צורך ב-backfill** — ה-ledger מאוכלס בשני הארגונים. נדרש: מעבר קריאה ל-ledger + שימור התנועה הידנית + השבתת הכותב הישן.

## 7. Baseline בדיקות (2026-06-24)

- **pytest:** 272 passed, 0 failed (חבילת היחידות ירוקה — שער אימות אמין).
- **audit_routes.py:** 47/183 GET routes נכשלים (בדיקת runtime נפרדת; יעד פאזה 4).

---

*מסמך זה הוא baseline v1.0. כל פאזה בתכנון ההקשחה תעדכן את הסטטוסים כאן בגרסה הבאה.*
