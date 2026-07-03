# אודיט routes מלא — 2026-07-03

Epic: יציבות ותשתית (Task 4/8).

הרצה: `python scripts/audit_routes.py` — TestClient בזיכרון, SQLite זמני, ארגון
מדומה עם נתוני seed (חשבון בנק, חשבונית, חשבון ספק, פריט מלאי, הוצאה).
בודק **רק GET routes** (231 מתוך כלל ה-routes באפליקציה), עם משתמש מאומת
(Bearer token) אך **ללא** `SUMIT_API_KEY`/`OPEN_FINANCE_*` ב-env (בניגוד לסוויטת
הטסטים, ששם `conftest.py` מגדיר `SUMIT_API_KEY=test-env-sumit-key`).

פלט גולמי מלא: `/private/tmp/claude-501/-Users-mymac-coding-cfo/140cab34-9f53-46c8-a9e3-2c91f1032d4f/scratchpad/route_audit_raw.txt`

## תוצאה כוללת

```
סהכ: 231 | תקין(200): 167 | אזהרה(4xx): 25 | כשל(5xx/EXC): 39
```

הסקריפט עצמו מסמן "FAIL" לכל קוד שאינו 200/401/403/404/422 — כולל 400,
שבפועל הוא לרוב תגובת "credentials לא מוגדרות" תקנית (category 1 למטה).
הסיווג האמיתי (env-gated / באג / artifact) נעשה כאן, לפי קריאת קוד המקור
של כל route/dependency, לא לפי המארז של הסקריפט.

---

## קטגוריה 1 — env-gated (35 routes, לא באג)

כל אלה מסתמכים על `Depends(get_sumit_integration)` (או בדיקת קונפיגורציה
מקבילה ב-`open_finance.py:74`) שמחזירה **`HTTPException(400, ...)`** באופן
מכוון כשאין SUMIT API key / Open Finance client מוגדרים לארגון — לא קריסה.
מקומית האודיט לא מגדיר `SUMIT_API_KEY`, לכן הם נכשלים; בסוויטת הטסטים
(`SUMIT_API_KEY=test-env-sumit-key`) org 1 עובר את ה-dependency ומגיע
לקריאה עצמה (זה בדיוק המקרה שה-handler החדש בפרק הבא סוגר).

| Router | Routes (400, קונפיגורציה חסרה) |
|---|---|
| `/api/accounting` | balance, customers/{id}/debt, customers/{id}/url, documents, income-items, vat-rate (6) |
| `/api/admin` | quotas, stock, test-connection (3) |
| `/api/communications` | sms/senders, sms/mailing-lists, email/mailing-lists (3) |
| `/api/crm` | entities, folders (2) |
| `/api/open-finance` | accounts, accounts/{id}, credit-leads, credit-sessions, customers, customers/{id}, customers/{id}/balances, customers/{id}/contacts/{id}, customers/{id}/financial-relations, customers/{id}/invoices, customers/{id}/osh/accounts, customers/{id}/osh/accounts/{id}, merchants, monthly-report, payments, providers, securities, transactions (18) |
| `/api/payments` | `/`, methods/{id}, recurring/customer/{id} (3) |

**וידוא:** כולם מחזירים 400 (לא 500) — תקין. אין שינוי נדרש.

---

**מגבלת היקף האודיט:** הריצה משתמשת בסט seed יחיד עם מכנים לא-אפסיים
ושדות מאוכלסים (ר' `scripts/audit_routes.py:seed`) — מחלקות באגים
תלויות-נתונים (NaN/Infinity על מכנה אפס, נתיבי "אין תוצאות") לא היו
צפויות לצוץ כאן גם אם קיימות. בדיקת `grep -rn "current_user\.get("` על
`src/cfo/api/routes/*.py` לא העלתה ממצאים (מחלקה זו לא קיימת בקוד הנוכחי),
אך זו כיסוי משלים בלבד — לא סריקה סטטית ממצה.

---

## קטגוריה 2 — באג אמיתי (4 routes, שורש אחד; נדחה למשימה חדשה)

`/api/sync/sumit/{debts,income-items,vat-rate,exchange-rate}` (GET) —
וכן `/api/sync/sumit/{documents,payments,billing,full}` (POST, לא נבדקו
ע"י האודיט כי הוא בודק רק GET אך חולקים את אותו שורש) — מקבלים
`ValueError` גולמי במקום `HTTPException` מבוקרת:

```
File "src/cfo/api/routes/sync.py", line 143, in get_vat_rate
    rate = await service.get_vat_rate(for_date)
File "src/cfo/services/data_sync_service.py", line 357, in get_vat_rate
    sumit = await self._get_sumit()
File "src/cfo/services/data_sync_service.py", line 53, in _get_sumit
    raise ValueError("SUMIT API key not configured")
ValueError: SUMIT API key not configured
```

**שורש:** `DataSyncService._get_sumit()` (`src/cfo/services/data_sync_service.py:28-55`)
בונה `SumitIntegration` ישירות (קורא ל-`Organization.api_credentials` +
`settings.sumit_api_key`) ומעלה `ValueError` גולמי כשאין מפתח — בניגוד
לתבנית הסטנדרטית `get_sumit_integration` (`src/cfo/api/dependencies.py:273-308`)
שמשמשת את שאר ה-routers (accounting, crm, payments, communications,
admin) ומחזירה `HTTPException(400, ...)` מבוקרת. ה-routes ב-`sync.py`
(`src/cfo/api/routes/sync.py:28-171`) לא משתמשים ב-dependency הזה — הם
בונים `DataSyncService(db, org_id)` ישירות ומעולם לא תופסים את ה-`ValueError`.
תוצאה: `ValueError` לא-תפוס בורח דרך FastAPI ל-500 גולמי (`EXC:ValueError`
בפלט האודיט) — בדיוק המחלקה שהמשימה הזו נועדה לסגור, אך כאן זה לא
כשל httpx (ה-handler החדש לא תופס `ValueError`), אלא כשל קונפיגורציה
שלא עטוף כראוי.

**למה לא תוקן כאן:** התיקון האמיתי (עטיפת `_get_sumit()` ב-try/except
בכל אחד מ-8 ה-routes ב-`sync.py`, או מעבר ל-`Depends(get_sumit_integration)`
כמו שאר ה-routers) חורג מ"שורה-שתיים במחלקה ידועה" — נוגע ב-8 handlers
ובעיצוב שכבת השירות. נפתחה משימת המשך:

### Task 4.1: אחידות טיפול-שגיאות ב-`DataSyncService` (SUMIT לא מוגדר)

**Files:** `src/cfo/services/data_sync_service.py`, `src/cfo/api/routes/sync.py`,
`tests/test_data_sync_service.py` (או קובץ טסט sync רלוונטי קיים)

**Interfaces:**
- Consumes: `get_sumit_integration` pattern הקיים ב-`dependencies.py:273-308`
  כדוגמה ל-400 מבוקר.
- Produces: כל 8 ה-routes תחת `/api/sync/sumit/*` (GET+POST) מחזירים
  `HTTPException(400, "SUMIT API key not configured")` במקום `ValueError`
  לא-תפוס, כשאין credentials.

- [ ] כתיבת טסט אדום: `GET /api/sync/sumit/vat-rate` בלי SUMIT credentials
  מצפה ל-400 (כרגע: 500/exception לא-תפוס).
- [ ] תיקון: לעטוף את `DataSyncService._get_sumit()` בקריאה מכל route
  (`try/except ValueError as e: raise HTTPException(400, str(e))`), או
  להעביר את 8 ה-routes ל-`Depends(get_sumit_integration)` הסטנדרטי —
  להחליט לפי מה שדורש פחות שינוי בממשק `DataSyncService`.
- [ ] הרצת סוויטה מלאה + וידוא שאר 7 ה-routes (POST) גם מכוסים.

---

## קטגוריה 3 — artifact מקומי / מגבלת הסקריפט (25 routes WARN, לא באג)

כל ה-25 מסומנים `WARN` (401/403/404/422) ע"י הסקריפט — לא `FAIL`. נבדקו
מדגמית לפי סוג ואומתו כמגבלות של שיטת האודיט, לא כשלי אפליקציה:

- **422 — חסרים query params חובה שהאודיט לא ממלא** (הסקריפט ממלא רק
  path params מ-`PLACEHOLDERS`, לא query params): `annual-reports/1214`,
  `annual-reports/1301` (`year: int = Query(...)`), `cashflow/statement`,
  `cashflow/by-category` (`start_date`/`end_date`), `daily-reports/{cumulative-pl,vat,pcn874,suppliers}`
  (`year`,`month`), `financial/tax/{856,advance,withholding}`,
  `financial/ap/cash-optimization`, `payroll/{payslips,reports/102,reports/126}`,
  `notes` (`entity_type`,`entity_id`), `open-finance/bank-branches` (`bank_code`).
- **401 — `cron/*` דורש `CRON_SECRET` header ולא Bearer token**: האודיט
  שולח רק Bearer, לא נכשל אפליקטיבית.
- **403 — `admin/control/clients`, `admin/organizations`**: דורשים
  `SUPER_ADMIN`; משתמש ה-seed הוא ADMIN רגיל.
- **404 — `financial/reports/preview/1`, `sync/runs/1`**: אין רשומה
  ב-id=1 בנתוני ה-seed (הודג'-קוד placeholder `"1"`).

**הערה — `date_trunc` (PostgreSQL-only):** ההקשר של המשימה ציין 8 routes
תחת `/api/cashflow/forecast/*` שנכשלים על SQLite עקב `date_trunc`. באודיט
הנוכחי **כל ה-8 מחזירים 200** — הבאג כבר תוקן (ר' `src/cfo/services/forecasting_service.py:691`,
הערה: "אגרגציה ב-Python (ניטרלית-dialect; SQLite חסר date_trunc)"). אין
עוד `date_trunc` בקוד (`grep -rn date_trunc src/cfo/` — 0 שימושים בפועל,
רק בהערה). מתועד כאן לשלמות; לא נדרשת פעולה.

---

## Handler גלובלי — 503 על כשל upstream

`src/cfo/api/__init__.py` — נוסף `@app.exception_handler(httpx.HTTPError)`
מיד אחרי `app = FastAPI(...)`:

```python
@app.exception_handler(httpx.HTTPError)
async def upstream_error_handler(request: Request, exc: httpx.HTTPError):
    """כשל תקשורת מול שירות חיצוני (SUMIT/Open Finance) — 503 כן, לא 500."""
    return JSONResponse(
        status_code=503,
        content={"detail": f"upstream integration unavailable: {type(exc).__name__}"},
    )
```

**למה זה נחוץ בנוסף ל-`SumitAPIError` handler הקיים:** `SumitIntegration`
כבר עוטף `httpx.HTTPStatusError` (תגובת שגיאה מהשרת) ל-`SumitAPIError`
(→502, handler קיים ב-`__init__.py:36`), אבל **לא** תופס כשלי רשת ברמת
transport — `httpx.ConnectError`, `httpx.ConnectTimeout`, `httpx.ReadTimeout`
וכו' (כולם תת-מחלקות של `httpx.HTTPError` שאינן `HTTPStatusError`). אלה
היו בורחים כ-500 גולמי. ה-handler החדש תופס אותם ברמת ה-app כרשת-בטחון
לכל אינטגרציה מבוססת httpx (SUMIT, Open Finance), בלי תלות בעטיפה
הפנימית של כל קליינט.

**טסט (TDD):** `tests/test_upstream_error_handling.py` —
`test_httpx_error_returns_503_not_500`, מפיל את `SumitIntegration.list_documents`
עם `httpx.ConnectError` ישירות (עוקף את ה-wrapping הפנימי, בודק את
ה-handler הגלובלי עצמו) מול `GET /api/accounting/documents`.

- אדום (לפני ה-handler): `httpx.ConnectError` בורח לא-תפוס מ-TestClient
  (500 ב-production, exception גולמי בטסט).
- ירוק (אחרי ה-handler): `503`, `detail` מכיל `"upstream integration unavailable: ConnectError"`.

---

## סיכום מספרי

| קטגוריה | כמות | פעולה |
|---|---|---|
| תקין (200) | 167 | — |
| 1. env-gated (400, מבוקר) | 35 | וידוא בלבד — תקין |
| 2. באג אמיתי (ValueError לא-תפוס) | 4 GET (+4 POST לא-נבדק) | נדחה → Task 4.1 |
| 3. artifact/מגבלת-אודיט (401/403/404/422) | 25 | מתועד, לא מתוקן |
| Handler 503 גלובלי ל-httpx.HTTPError | — | מומש + TDD |

**סה"כ routes שנבדקו:** 231 GET routes.

---

## עדכון 2026-07-03 (המשך אחה"צ) — Task 5-7: prod_smoke + SUMIT write-back + drift

### Task 5: prod_smoke.py — נתיבים שגויים שתוקנו

ריצה חיה ראשונה מול `cfo-2.vercel.app` חשפה שני 404 על נתיבים שגויים
ב-`CRITICAL_PATHS`:
- `/api/financial/reports/profit-loss` (לא קיים) → תוקן ל-`/api/reports/profit-loss`.
- `/api/ap/aging` (לא קיים) → תוקן ל-`/api/daily-reports/ap-aging`.

תוקן ב-commit `61e0e65` + נוספה בדיקת רגרסיה ל-`tests/test_prod_smoke.py`.

**שאר 8 הכשלים (403 "User is not scoped to an organization") אינם באג:**
production לא נפרס 3 ימים, ולכן ה-fallback SUPER_ADMIN→org 1
(commit `23353ca`, היום) עדיין לא חי. צפוי להיפתר עם דיפלוי Task 8.

### Task 6: אימות SUMIT write-back חי — הצליח חלקית

`scripts/verify_sumit_writeback.py` נכתב מול החתימות האמיתיות
(`DocumentItem.price` לא `unit_price`; `customer_id` כטקסט חופשי ללקוח
walk-in; `get_document_details` לא `get_document`).

ריצה חיה:
```
1) יוצר הצעת מחיר סמלית...
   נוצר מסמך: 2095660684 (מספר 1001)
2) מוריד PDF...
   PDF: 83034 bytes
3) מבטל את המסמך...
   SumitAPIError: SUMIT API error: Cancelling this document isn't allowed
```

**מסמך 1001 (ID 2095660684) נשאר פתוח ב-SUMIT** — נדרש ביטול/מחיקה ידנית
ע"י המשתמש + בדיקה אם הצעות מחיר דורשות endpoint/פעולה שונה מחשבוניות
לביטול. עוקב: TaskCreate #1, memory `rezef-completion-epics`.

### Task 7: Neon schema drift — נקי

```
python scripts/schema_drift_check.py --env-file <scratchpad>/.env.prod
OK — אין drift: הסכמה החיה תואמת את המודלים
```
