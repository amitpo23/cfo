# מסמך המשך לביצוע — השלמת אפיק 1 (יציבות) עד דיפלוי

> **לסוכן המבצע:** זהו מסמך handoff עצמאי. כל טקסט המשימות המלא (קוד, טסטים,
> פקודות) נמצא בתכנית המחויבת: `docs/superpowers/plans/2026-07-03-epic1-stability.md`
> — קרא ממנה כל משימה לפני ביצועה. אם קיימים קבצי brief מקומיים
> (`.superpowers/sdd/task-N-brief.md`) הם זהים בתוכן — השתמש במה שנוח.
> אל תבצע מחדש עבודה שהושלמה (רשימה למטה). עבוד מ-`/Users/mymac/coding/cfo`
> על branch `feat/sumit-ar-ap-documents-ocr`. תקשורת ותיעוד בעברית.

## מצב נוכחי מאומת (2026-07-03, סוף סשן קודם)

- HEAD: `03043ac`, נדחף ל-origin. **456 טסטים עוברים, 0 נכשלים.**
- הושלמו עם review נקי: Task 1 (באג תקציב חוצה-חודש), Task 2 (schema_sync
  compute_missing + scripts/schema_drift_check.py), Task 3 (apply_additive +
  /api/admin/db/migrate מרפא-עצמי), Task 4 (אודיט 231 routes +
  httpx→503 handler; מסמך: docs/audits/2026-07-03-route-audit.md),
  Task 4.1 (SumitNotConfiguredError→400 + _post_binary→SumitAPIError).
- Task 4.2 הושלמה בקוד (commits `997ba6b`+`03043ac`: env-credential fallback
  מוגבל ל-org 1 בשני השירותים) אך ה-review שלה נקטע. ראה שלב 1.
- יומן התקדמות: `.superpowers/sdd/progress.md` — **עדכן אותו אחרי כל שלב**.

## כללים מחייבים

1. **TDD** לכל שינוי קוד: טסט אדום → מימוש → ירוק. suite מלא לפני כל commit:
   `python -m pytest tests/ -q --tb=short -p no:warnings 2>&1 | tail -3`
2. **פרוד:** שינויי סכמה additive בלבד. מחיקות — אסורות בלי אישור המשתמש.
3. **SUMIT חי:** backoff על 403 (המתן 30s, עד 3 נסיונות). לעולם לא להשאיר
   מסמך לא-מבוטל (אושר: הצעת מחיר סמלית + ביטול מיידי בלבד).
4. **סודות** רק ב-scratchpad של הסשן או ב-.env.local — לעולם לא בקומיט.
5. **נתקעת / חסר credential / שגיאה לא צפויה פעמיים ברצף → עצור ושאל את
   המשתמש.** אל תנחש.

## שלב 0 — אימות סביבה (5 דקות)

```bash
cd /Users/mymac/coding/cfo
git status --short          # נקי (למעט אולי .superpowers/sdd/progress.md)
git log --oneline -1        # 03043ac
python -m pytest tests/ -q --tb=short -p no:warnings 2>&1 | tail -3   # 456 passed
```
אם משהו לא תואם — עצור ושאל.

## שלב 1 — סגירת אימות Task 4.2 (בלי LLM-review, אימות דטרמיניסטי)

ה-review שנקטע מוחלף באימות הבא (מספיק כי הקוד כבר נבדק בטסטים):
```bash
python -m pytest tests/test_upstream_error_handling.py -v -p no:warnings   # הכל עובר
grep -n "organization_id == 1" src/cfo/services/data_sync_service.py src/cfo/services/sync_engine.py
# חייב להופיע שער org-1 בשני הקבצים סביב ה-env fallback
grep -rn "SumitNotConfiguredError" src/cfo/api/__init__.py   # handler 400 רשום
```
אם שלושת אלה תקינים — רשום ב-ledger: `Task 4.2: verified deterministically
(tests+grep), review waived by user cost decision` והמשך. אם לא — עצור ושאל.

## שלב 2 — Task 5: scripts/prod_smoke.py

בצע לפי `docs/superpowers/plans/2026-07-03-epic1-stability.md` → "Task 5"
(הקוד המלא שם): טסט מקומי (`tests/test_prod_smoke.py`, fixtures `client`+`owner`
מ-conftest — owner@example.com/secret123), ואז הסקריפט עצמו, ואז commit.

**להרצה החיה מול הפרוד** צריך פרטי אדמין אמיתיים:
- נסה `grep -i "smoke\|admin" /Users/mymac/coding/cfo/.env.local` — אולי מוגדרים.
- אם אין — **שאל את המשתמש** ל-SMOKE_EMAIL/SMOKE_PASSWORD (אל תיצור משתמש
  אדמין חדש בפרוד בלי אישור).
- הרץ: `SMOKE_EMAIL=... SMOKE_PASSWORD=... python scripts/prod_smoke.py`
- כל FAIL שאינו env-gated: רשום ב-docs/audits/2026-07-03-route-audit.md
  (קטגוריה 2). תיקון קטן — תקן ב-TDD; גדול — תעד כמשימת המשך ודווח.

צפי suite אחרי השלב: 457+ passed.

## שלב 3 — Task 6: אימות SUMIT write-back חי

בצע לפי התכנית → "Task 6". לפני ההרצה **קרא את החתימות האמיתיות** ב-
`src/cfo/integrations/sumit_integration.py` (create_document /
get_document_pdf / cancel_document / get_document) וב-`sumit_models.py`
(DocumentRequest — כולל מיפוי `quote`→PriceQuotation), והתאם את הסקריפט.

Credentials: `SUMIT_API_KEY`/`SUMIT_COMPANY_ID` מ-.env.local; אם ריקים:
```bash
vercel env pull /private/tmp/claude-501/-Users-mymac-coding-cfo/140cab34-9f53-46c8-a9e3-2c91f1032d4f/scratchpad/.env.prod --environment production --yes
```
(הפרויקט מקושר: cfo-2. אם הנתיב לא קיים צור אותו או משוך לקובץ scratchpad אחר —
לא לתוך הרפו.)

הצלחה = 4 שלבים: נוצר מסמך → PDF ירד (גודל>0) → בוטל → סטטוס מאומת.
**אם create הצליח ו-cancel נכשל: עצור מיד, דווח למשתמש עם מזהה המסמך
כדי שיבטל ידנית ב-UI של SUMIT.** תעד תוצאה ב-PRODUCTION_READINESS.md
ובמסמך האודיט, ו-commit לפי התכנית.

## שלב 4 — Task 7: בדיקת drift מול Neon (קריאה בלבד בשלב זה)

```bash
python scripts/schema_drift_check.py --env-file <קובץ-ה-env-שנמשך-בשלב-3>
```
- `OK` → רשום ב-ledger והמשך.
- יש drift → **אל תתקן עדיין ישירות ב-DB.** התיקון יקרה בשלב 5 דרך
  ה-endpoint המשודרג אחרי הדיפלוי (זו בדיוק היכולת שנבנתה ב-Task 3).
  רשום את רשימת ה-drift במסמך האודיט.

## שלב 5 — Task 8: דיפלוי ואימות סופי

```bash
python -m pytest tests/ -q --tb=short -p no:warnings 2>&1 | tail -3   # ירוק מלא
vercel deploy 2>&1 | tail -3                                          # preview
SMOKE_BASE_URL=<preview-url> SMOKE_EMAIL=... SMOKE_PASSWORD=... python scripts/prod_smoke.py
# exit 0 נדרש. כשל → תקן לפני production.
vercel deploy --prod 2>&1 | tail -3
```
אחרי פריסת production:
1. הפעל מיגרציה+ריפוי סכמה: קבל token דרך
   `POST https://cfo-2.vercel.app/api/admin/auth/login` (אותם פרטי SMOKE),
   ואז `POST https://cfo-2.vercel.app/api/admin/db/migrate` עם
   `Authorization: Bearer <token>`. שמור את התשובה (שדה `schema_sync`).
2. אימות drift חוזר: `python scripts/schema_drift_check.py --env-file ...` → חייב `OK`.
3. smoke סופי מול prod: `python scripts/prod_smoke.py` (base ברירת מחדל) → exit 0.
4. עדכן `docs/PRODUCTION_READINESS.md`: תאריך אימות, תוצאות smoke, אימות
   SUMIT write-back, מנגנון migrate המשודרג, ומה שנותר פתוח
   (OPEN_FINANCE_USER_ID — אפיק 3; Google OAuth — לא חוסם).
5. Commit + push:
```bash
git add docs/PRODUCTION_READINESS.md docs/audits/2026-07-03-route-audit.md .superpowers/sdd/progress.md
git commit -m "docs(readiness): epic 1 stability verified live"
git push origin feat/sumit-ar-ap-documents-ocr
```

## שלב 6 — סגירה ודיווח

1. עדכן ledger: `EPIC 1 COMPLETE` + מספרי commits + תוצאות smoke.
2. דווח למשתמש סיכום קצר בעברית: מה נפרס, תוצאות ה-smoke, מזהה מסמך
   ה-SUMIT שאומת ובוטל, מצב ה-drift, ומה האפיק הבא (אפיק 2: סופר-אדמין
   ופר-לקוח UI; אפיק 3: Open Finance — דורש consent של המשתמש).

## הגדרת סיום — גל 1 (אפיק יציבות)

- [ ] suite מלא ירוק (457+)
- [ ] Task 4.2 מאומת דטרמיניסטית ורשום ב-ledger
- [ ] prod_smoke קיים, נבדק מקומית, ירוק מול production
- [ ] SUMIT write-back אומת חי (נוצר→PDF→בוטל→אומת) ותועד
- [ ] drift מול Neon = OK אחרי migrate
- [ ] PRODUCTION_READINESS.md מעודכן, הכל committed + pushed

---

# גל 2 — שדרוגים, השלמות SUMIT, צ'אטבוט AI, QA ודיפלוי סופי

> **סדר מחייב:** גל 1 (שלבים 0–6) נפרס קודם. רק אחרי production ירוק
> מתחילים גל 2. כל פריט בגל 2 = מחזור TDD מלא + commit נפרד. אחרי כל
> 2–3 פריטים: suite מלא. בסוף הגל: שלב 11 (QA מקיף + דיפלוי).

## שלב 7 — עשרה שדרוגים (בסדר הזה; כל אחד commit נפרד)

**7.1 COGS אמיתי בדשבורד.** `src/cfo/services/dashboard_service.py` (~שורה
380): מוחלף המקדם המזויף `expenses * 0.3` בחישוב אמיתי מקטגוריות עלות־ישירה
(אותה סיווג DIRECT_CATEGORIES שכבר קיים ב-cost_analysis_service — עשה בו
שימוש חוזר, אל תשכפל). אם אין נתון — החזר null+דגל `"cogs_derived": false`,
לא מספר מומצא. טסט: ארגון עם Transactions מסווגות → COGS מדויק; ארגון ריק → null.

**7.2 הסרת fallback מזויף ב-AI intelligence.** `src/cfo/services/ai_intelligence_agent.py`
(~שורה 262): fallback שממציא נתונים → החזרת `{"available": false, "reason": ...}`
כנה. טסט: כשאין נתונים אין מספרים מומצאים בתשובה.

**7.3 Workflow גבייה מתמשך.** מודל `CollectionCase` חדש (org_id, contact_id,
invoice_ids JSON, status: open/promised/paid/escalated, attempts JSON —
תאריך/ערוץ/תוצאה, promise_date) + migration additive. שירות
`collection_service.py`: פתיחת case אוטומטית לחשבונית שעברה סף ימים,
רישום נסיון, קידום סטטוס. routes `/api/collections/*` (GET list, POST attempt,
POST status) + חיבור ל-alert_engine. UI: לשונית בדשבורד AR. טסטים: מחזור חיים
מלא + בידוד org.

**7.4 שכר→יומן.** `payroll_service`: אחרי חישוב תלוש — יצירת פקודת יומן
(ברוטו הוצאה, ניכויים התחייבויות, נטו לתשלום) דרך ledger_service, מסומנת
derived. טסט: תלוש → פקודה מאוזנת Σחובה=Σזכות.

**7.5 זיהוי כפילויות מסמכים.** ב-`document_anomalies` (engine): זיהוי
duplicate — אותו ספק+סכום+תאריך±3 ימים או אותו מספר-מסמך. חיבור לדשבורד
Engine הקיים. טסט: שתי הוצאות זהות → anomaly.

**7.6 Alert engine — שגיאות לא נבלעות + טסטים.** `alert_engine`: החלפת
try/except האילם ברישום שגיאה ל-log + מונה כשלים בתשובה. טסטים ראשונים
ל-alert_engine (אין כיום): התרעה נוצרת על תנאי אמת, כשל handler לא מפיל
את השאר.

**7.7 מנגנוני ניכוי בהוצאות.** בהתבסס על שלושת מחשבוני הניכוי הקיימים
(רכב/בית/טלפון ב-calculators): שדה `deduction_percent` ב-Expense (migration
additive) + החלה אוטומטית לפי קטגוריה ב-expense_filing_service, ושיקוף
בדוח מע"מ/1301 (רק החלק המוכר). טסט: הוצאת רכב → החלק המוכר בלבד נספר.

**7.8 Idempotency לסנכרון בנק.** `BankTransaction`: עמודת `is_provisional`
(migration additive) + מפתח ייחודי לוגי (org, provider_tx_id) עם upsert —
סנכרון כפול לא יוצר כפילויות. טסט: אותו feed פעמיים → אותה ספירה.

**7.9 מסכי הנפקה לכל סוגי המסמכים.** frontend: `DocumentIssueWizard.tsx` —
בחירת סוג (10 הסוגים מ-`/api/financial/documents/types`), לקוח, שורות, ותצוגת
תוצאה עם PDF. חיבור ל-DocumentManager ולדשבורד לקוח. `npm run build` + `tsc`
נקיים. בדיקה ידנית מול preview לפני production.

**7.10 ניקוי אזהרות (pristine output).** החלפת כל `datetime.utcnow()` ב-
`datetime.now(timezone.utc)` בקוד שלנו (src/ + tests/ — כ-2,285 אזהרות כיום),
ותיקון ה-LegacyAPIWarning של Query.get→Session.get ב-tests/test_office.py.
יעד: `python -m pytest tests/ -q 2>&1 | grep -c Warning` יורד דרמטית; אפס
שינוי התנהגות (utcnow נאיבי → aware; ודא שאין השוואות naive/aware שנשברות —
הרץ suite מלא).

## שלב 8 — השלמות יכולות SUMIT API

מקור אמת: `docs/SUMIT_API_REFERENCE.md` + `SUMIT_MODULE_COVERAGE.md`
(רשימת ה-Partial). לכל יכולת: מתודה ב-`sumit_integration.py` → route →
טסט (mock של SUMIT) → רישום ב-SUMIT_MODULE_COVERAGE.md כ-Ready.

**8.1 מסמכים עתידיים** (future documents) — יצירה/רשימה/ביטול של מסמכים
מתוזמנים. **8.2 צ'קים ומזומן** — רישום תקבול צ'ק/מזומן כאמצעי תשלום במסמך.
**8.3 הרשאות מס"ב (mandates) והחזרות** — יצירת mandate, סטטוס, טיפול
בהחזרות. **8.4 זיכויים/החזרים (refunds)** — יצירת זיכוי כספי מול עסקת סליקה
קיימת. **8.5 התרעות chargebacks** — משיכת התרעות והצגתן ב-alerts.

**8.6 פער שאינו API (לתעד, לא לממש כאן):** קליטת מנות יומן, תיוק טיוטות
סרוקות, שידור PCN874 — אין API ב-SUMIT; נדרש סקריפט דפדפן (תקדים:
`scripts/sumit_daily_file_expenses.js`). פתח סעיף "אוטומציית דפדפן — אפיק 5"
במסמך הכיסוי עם שלושת אלה, ודווח למשתמש שזה ממתין לאפיק 5.

לכל route חדש: org-scoped, שגיאות כנות (400/503 — התשתית מגל 1), ובדיקת
בידוד בין ארגונים.

## שלב 9 — צ'אטבוט AI של רצף (אפיק 4 — מוקדם לפי בקשת המשתמש)

**ארכיטקטורה:** backend tool-use loop מול Anthropic API. הקונפיג כבר קיים:
`settings.anthropic_api_key` (config.py:91). מודל ברירת מחדל: הוסף
`ai_chat_model: str = "claude-sonnet-5"` לקונפיג (override ב-env). לפני
המימוש אמת את זמינות המודל מול התיעוד הרשמי של Anthropic.

**9.1 שכבת כלים** — `src/cfo/services/ai_chat_tools.py`: רישום כלים שכל
אחד עוטף שירות קיים (לעולם לא SQL גולמי), org-scoped מה-JWT:
- קריאה: `get_profit_loss`, `get_cashflow`, `get_ar_aging`, `get_ap_aging`,
  `get_ledger_card` (כרטסת לפי contact), `get_vat_position`,
  `list_invoices` (עם פילטרים), `get_engine_status`, `search_contacts`.
- פעולה (דורשות אישור — ראה 9.3): `run_sync`, `issue_document`,
  `send_report` (מייל דוח קיים).
- סופר-אדמין בלבד (בדיקת role קשיחה): `register_client`, `list_clients`,
  `get_office_rollup`, `sync_all_clients`.

**9.2 שירות + route** — `src/cfo/services/ai_chat_service.py`: לולאת
tool-use (קריאה ל-API, ביצוע כלי, החזרת תוצאה, עד תשובה סופית; תקרת 10
סיבובים). route `POST /api/ai/chat` (הודעה+היסטוריה) — org מה-JWT, הכלים
מסוננים לפי role. שמירת שיחות בטבלת `ai_chat_messages` (org_id, user_id,
role, content, tool_calls JSON, created_at) + migration additive.

**9.3 בטיחות פעולות:** כלי-פעולה מחזירים תחילה
`{"confirmation_required": true, "summary": "..."}`; הביצוע רק כשההודעה
הבאה מאשרת (ה-frontend מציג כפתור אישור). לעולם אין ביצוע פעולה כותבת
בסיבוב הראשון.

**9.4 Frontend** — `ChatAssistant.tsx`: פאנל צף (כפתור בפינה בכל המסכים)
+ route `/assistant`. עברית, RTL, סטרימינג לא נדרש בגרסה ראשונה. הצגת
"הבוט מציע לבצע: X — אשר/בטל" לפעולות.

**9.5 טסטים (חובה):** unit לכל כלי (org isolation: משתמש org A לא מקבל
נתוני org B); route עם LLM ממוקפח (monkeypatch של קריאת ה-API — אין קריאות
אמיתיות ב-CI); non-admin שמנסה כלי office → נחסם; פעולה כותבת בלי אישור →
לא מבוצעת. בדיקה חיה אחת ידנית אחרי deploy עם ANTHROPIC_API_KEY אמיתי
(אם חסר ב-env — שאל את המשתמש).

## שלב 10 — חבילת QA מקיפה (שער לפני הדיפלוי הסופי)

צור `scripts/qa_gate.py` שמריץ ומדווח PASS/FAIL מרוכז:
1. `python -m pytest tests/ -q` — אפס כשלים.
2. `python scripts/audit_routes.py` — אפס כשלים לא-מתועדים חדשים (השווה
   מול docs/audits/2026-07-03-route-audit.md; כל route חדש חייב סטטוס תקין).
3. `python scripts/schema_drift_check.py` מול SQLite מקומי ומול Neon.
4. Frontend: `cd frontend && npx tsc --noEmit && npm run build` — אפס שגיאות.
5. `python scripts/colscan.py` אם קיים (סורק עמודות-רפאים) — אפס ממצאים חדשים.
6. בידוד דיירים: הרץ ממוקד `python -m pytest tests/ -q -k "isolation or org_scope or tenancy"`.
7. E2E ידני מול preview (רשימת סימון, לתעד במסמך האודיט): login → org switch
   → sync → P&L → מאזן → כרטסת → הנפקת מסמך (טיוטה/ביטול) → צ'אטבוט שאלה
   אחת + פעולה אחת עם אישור.
כשל בכל סעיף → תיקון לפני המשך. אין דיפלוי עם QA אדום.

## שלב 11 — דיפלוי סופי ודיווח

1. suite + qa_gate ירוקים → `vercel deploy` → smoke מול preview →
   `vercel deploy --prod` → `POST /api/admin/db/migrate` (המיגרציות החדשות:
   CollectionCase, deduction_percent, is_provisional, ai_chat_messages) →
   `python scripts/prod_smoke.py` (הוסף ל-CRITICAL_PATHS את `/api/ai/chat`
   בבדיקת אימות-בלבד ואת `/api/collections`) → `schema_drift_check` מול Neon = OK.
2. עדכן PRODUCTION_READINESS.md + SUMIT_MODULE_COVERAGE.md + ledger
   (`WAVE 2 COMPLETE`), commit + push.
3. דיווח סיכום למשתמש בעברית: מה נוסף, תוצאות QA, קישור לפרוד, מה נותר
   לאפיקים 2/3/5 (סופר-אדמין UI מלא; Open Finance consent — פעולת משתמש;
   אוטומציית דפדפן SUMIT).

## הגדרת סיום — גל 2

- [ ] 10 השדרוגים בוצעו ב-TDD, כל אחד commit נפרד
- [ ] יכולות SUMIT 8.1–8.5 ממומשות + מתועדות; 8.6 מתועד כאפיק 5
- [ ] צ'אטבוט AI חי בפרוד: שאילתות + פעולות-עם-אישור + בידוד org נבדק
- [ ] qa_gate.py קיים וירוק על כל 7 הסעיפים
- [ ] production נפרס, migrate הורץ, smoke+drift ירוקים
- [ ] כל התיעוד מעודכן, הכל pushed
