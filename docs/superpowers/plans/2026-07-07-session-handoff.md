# Handoff — סשן 2026-07-06/07 (רצף CFO)

> מסמך המשך לסשן. קרא קודם: `.superpowers/sdd/progress.md` (יומן מלא) +
> זיכרון `rezef-completion-epics`. עבוד מ-`/Users/mymac/coding/cfo`,
> branch `feat/sumit-ar-ap-documents-ocr`. פרוד: `cfo-2.vercel.app` (Neon).
> env פרוד: `/private/tmp/claude-501/-Users-mymac-coding-cfo/140cab34-9f53-46c8-a9e3-2c91f1032d4f/scratchpad/.env.prod`.
> login פרוד (super_admin): `amitporat1981@gmail.com` / `Rezef-O1zHmGLj` (זמני).

## מי המשתמש
המשתמש הוא **רואה-החשבון/מנהל המשרד** של תיקי הלקוחות. רצף = המערכת שלו
לניהול רב-לקוחות. "אצלנו" = רצף (+ חשבון המשרד ב-SUMIT).

## מיפוי תיקים בפרוד (SUMIT)
| org | שם | CompanyID | מפתח | מצב |
|---|---|---|---|---|
| 1 | עמית פורת | 439924597 | env `...0IGO` | מחובר ✓ |
| 2 | שף אליהב כהן | 642076960 | `x9eyVPBPbYAdSkzRZVfgCQLXMIXwne0X7aYnc9juUG8mKeBFoU` | מחובר ✓ (30 חשבוניות) |
| 3 | מדיצ'י שיווק בתי מלון | 444973420 | — | לא מחובר, status=inactive (מפתח שגוי) |
| 5 | עומר ועודד פורת | 1999386278 | `n5uHwcsLShS96ePEVzR6m1kPoKSU0Tptbo9eZNpst6Bcv8R2aq` | מחובר ✓ (17 חשבוניות) |
- org 4 (כפילות עומר-ועודד ריקה) **נמחקה**.
- חשבון "ניהול משרד" ב-SUMIT: **CompanyID 844329067** (זה חשבון המשרד/רו"ח).
- **נעילת SUMIT "Repeated incorrect credentials"** = על ה-IP המקומי בלבד.
  סנכרון אמין דרך prod cron (Vercel IP):
  `curl -H "Authorization: Bearer $CRON_SECRET" https://cfo-2.vercel.app/api/cron/sync`.

## מה נעשה בסשן (הושלם ונפרס)
1. **תיקוני יציבות + פרוד** (מוקדם בסשן): פרורציית תקציב, schema_sync,
   migrate מרפא-עצמי, httpx→503, sync-routes→400, סגירת דליפת credentials
   חוצת-דיירים (env fallback רק org 1). 729+ טסטים ירוקים.
2. **תיקוני data-parity מול SUMIT חי:** VAT כפול (compute_vat_position dedup
   Bill/Expense לפי external_id), fetch_bills מושך סוגים 15+16,
   fetch_invoices מושך סוגים 0+1 (חשבונית מס קבלה — 9 מסמכי ₪124K שהוחמצו),
   expense-pull ב-cron. כולם נפרסו ואומתו חי.
3. **בוט AI:** knowledge base מלא (rezef_kb + rezef_help), כלי משרד
   (super-admin), 793 טסטים. **כבוי בפרוד** — צריך ANTHROPIC_API_KEY
   (המפתח הקיים מוצה מכסה חודשית עד 1.8). ה-API הוקצה לבוט בלבד
   (OCR-cron הוסר, OCR_LLM_ENABLED=false).
4. **UI פר-לקוח:** cashflow.py+reports.py (29 נקודות) מכבדים org-switcher.
   דשבורדים מציגים נתונים אמיתיים פר-תיק (אומת: org5 revenue ₪90K→₪319K
   אחרי תיקון type-1).
5. **הפעלת לקוחות:** חובר שף אליהב (מפתח חדש), נמחקה כפילות org4,
   הוגדרה סיסמת login למשתמש.

## ⚠️ הפריט הפתוח — קליטת הוצאות עומר-ועודד (המשך ישיר)
**מה קרה:** עומר-ועודד העלה **50 קבצי הוצאות** ל-SUMIT ("קבצי הוצאות",
כולם "ממתין לקליטה"). הורדתי את כולם (crm/downloadfile/{uuid} עובד ללא
auth → S3), קראתי כל אחד בעצמי (pdftotext לדיגיטליים + קריאת-תמונה
לסרוקים), ו**יצרתי 41 הוצאות ברצף** (org 5, source=sumit_fileexpense,
external_id=sumit_file_{uuid}): **מע"מ תשומות ₪32,171, סה"כ ₪211,108**.
- הוחרגו: קבצים 14,15,16,17,18 = קבלות שעומר/עודד **הנפיקו** (הכנסה!)
  שעלו בטעות; 39 = לוגו. כפילויות: 11=41, 38=40. flagged: 44 (קישור כביש6).
- קבצי המקור + הנתונים: scratchpad/receipts/*.pdf, uuids.txt.

**ניסיון תיוק ל-SUMIT נחסם:** `add_expense` החזיר "ההרשאה נדחתה: Expenses
addition isn't active". **הסיבה (מ-SUMIT support):** התיוק צריך לקרות
**מצד הנהלת החשבונות של המשרד** (משתמש מנהל המשרד, בתוך תיק הלקוח) — לא
מצד העסק של עומר. Rezef org5 מחובר עם המפתח של **עומר** (צד עסק) → חסום.

**הצעד הבא (ממתין למשתמש):** לקבל את **מפתח ה-API של חשבון המשרד**
(CompanyID 844329067, מדף developers/keys כשמחוברים לחשבון ניהול-המשרד).
עם מפתח המשרד + CompanyID של הלקוח → add_expense יעבוד מצד הנהלת-החשבונות.
כשהמפתח יגיע: להגדיר את רצף לתייק דרך מפתח המשרד (office_service תומך —
מפתח משרד אחד + CompanyID פר-לקוח), פיילוט אחד, ואז 41 + ארכוב המקור.
**חלופה:** הצוות קולט ידנית ב-SUMIT מצד הנהלת-חשבונות; רצף מציגה.

## חסמים שרק המשתמש פותח (דווחו)
- `ANTHROPIC_API_KEY` בפרוד (מפתח פעיל, לא מוצה) → מדליק את הבוט.
- מפתח API של חשבון המשרד (844329067) → מאפשר תיוק הוצאות מצד הנה"ח.
- `OPEN_FINANCE_USER_ID` + consent → מדליק התאמות בנק.
- מפתח SUMIT תקין למדיצ'י (org 3).
- מיזוג הענף ל-main (הפרוד רץ מהענף, ~260 commits לפני main — סיכון דריסה).
- ניקוי ב-SUMIT: הצעת מחיר 1001 + לקוח 2095660683 (משרידי אימות write-back).

## תזכורת עבודה
suite: `python -m pytest tests/ -q --tb=short -p no:warnings`. פרוד:
`vercel deploy --prod --yes` ואז migrate + `scripts/prod_smoke.py`.
עדכן `.superpowers/sdd/progress.md` אחרי כל משימה. גישה מלאה לפרוד מאושרת
(additive בלבד; מחיקות/רכישות — רק באישור מפורש + שקיפות עלות).
