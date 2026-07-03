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

## הגדרת סיום (חובה לוודא הכל)

- [ ] suite מלא ירוק (457+)
- [ ] Task 4.2 מאומת דטרמיניסטית ורשום ב-ledger
- [ ] prod_smoke קיים, נבדק מקומית, ירוק מול production
- [ ] SUMIT write-back אומת חי (נוצר→PDF→בוטל→אומת) ותועד
- [ ] drift מול Neon = OK אחרי migrate
- [ ] PRODUCTION_READINESS.md מעודכן, הכל committed + pushed
