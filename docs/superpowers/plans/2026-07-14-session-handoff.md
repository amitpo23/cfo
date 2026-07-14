# Handoff — סשן 12-14/07/2026 (רצף CFO)

> מסמך המשך. קרא קודם: `.superpowers/sdd/progress.md` (יומן מלא) + הזיכרונות
> `verify-first-doctrine`, `filing-triple-verification-rule`, `api-call-cost-discipline`,
> `sumit-knowledge-base`, `vat-may-june-2026-org1-filing`.
> עבודה מ-`/Users/mymac/coding/cfo`, branch `feat/sumit-ar-ap-documents-ocr` (הפרוד רץ ממנו!).
> פרוד: `cfo-2.vercel.app` (Neon). login super_admin: `amitporat1981@gmail.com` / `Rezef-O1zHmGLj` (זמני — להחליף!).
> env פרוד: `vercel env pull <file> --environment=production` (ה-CLI מחובר).

## דוקטרינות מחייבות (הנחיות בעלים, בזיכרון הקבוע)
1. **בדיקה מול מרכז ידע SUMIT לפני כל פעולה/פיתוח** — `docs/SUMIT_KNOWLEDGE_BASE.md` (34 חוקים) + `docs/sumit_help_kb/01..06` (609 מאמרים מעוכלים).
2. **אימות משולש לכל פלט דיווח** — דיווח שגוי = עבירה על החוק. ממומש ב-`filing_verification.py` + פאנל ב-/vat-report.
3. **"אם יש ספק אין ספק"** — אימות אקטיבי בדפדפן (סשן Chrome של המשתמש, לא API) והצלבת DB. בחודש הראשון לאמת הכול.
4. **משמעת עלויות API** — כל קריאת SUMIT עולה כסף (obligo!); Open Finance במכסה. רק מה שחייבים.
5. **חלוקת מודלים:** חשיבה/חקירה/אימות = Fable; ביצוע = Sonnet (model param ב-Agent tool).

## מה נבנה ופרוס בסשן (הכול חי, 1,035 טסטים, smoke 16/16)
| תחום | תוצר | commits עיקריים |
|---|---|---|
| מסמכי-על | REZEF_OPERATING_MODEL (מהות+מקצב יומי+scorecard), תכנית עמית פורת, תכנית שלמות נתונים | d8f2090, 94a229e |
| גבייה | מודל T-1 + יומי לפי ימי איחור + עצירה בזיהוי תשלום בנק; תוקן PAID-עם-יתרה (11 שורות ₪590K בשני תיקים) | a16d9e5 |
| בנק | connection scoping פר-org (זיהום חוצה-לקוחות!), org2 (אליהב/מזרחי) חובר — 2,000 תנועות; חסימת monthly-report/securities על userId משותף | 72b0baf, aa5382d |
| מנוע פער בנק-חשבוניות | סיווג+דוח חודשי+cron התרעות 06:15+בוט; מסך "ספקים חסרי חשבונית" עם מטרת-העברה | 0331369, 96ae615 |
| שלמות נתונים | יתרות בנק אמיתיות (parsing+טיפוסי חשבון), bills סימן+סטטוס (947K-→2.2K AP), data_quality, daily-close+snapshots, Command Center כן | 2df0f84 |
| דיווח מע"מ | מסך /vat-report: תקופה דו-חודשית, בסיס קליטה, PCN874 להורדה, מבנה אחיד (חשבשבת), Excel/PDF בכל 13 המסכים | 0dce100 |
| זיכויים | סוג 5+6 נמשכים (הוכחת ₪215,400!), קבלות=סוג 2, סכומים חתומים בכל המנועים, tax_service אוחד על הבורר הקנוני | ebf0f48 |
| אימות משולש | reconciliation + חישוב עצמאי + שלמות (טיוטות/טריות-checkpoints/הצלבת ספרים מוקלטת) | ebf0f48, ca134b4, 67075ad |
| אודיט אליהב | הצלבה תלת-כיוונית: 3 דליפות (עסק→תיק ידני; ×4 במנה; sync) + תיקוני PCN | f5737c9, docs/audits/2026-07-13-eliav-* |
| P1 | תזכורת שע"מ רבעונית, FilingCrosscheck (הרגל 3), ולידציות מס"ב | 67075ad |
| ידע | מרכז ידע SUMIT מלא (609 מאמרים), מיפוי כיסוי API (84 SUMIT+83 OF), ניקוי creditguy/billing/load | 5ca201b, aa5382d, 92dd522 |

## מצב נתונים חי (14/07 בוקר)
- **org1 עמית:** מאי-יוני = החזר ₪2,058 (בסיס מסמך) ברצף מול **₪3,265 בספרי SUMIT** (crosscheck הוקלט → verify=FAIL, פער ~₪1,207 — מסמכים שקיימים בצד אחד בלבד). **262 קבצים בתור התיוק** (לא 200+; 200 נקצרו→docs/audits/2026-07-12-org1-books-pending-files-harvest.txt, 62 טרם). בנק: לא-מתועד מאי ₪51.9K/יוני ₪16.8K. AR אמיתי: 21 חשבוניות ₪440K. סנכרון SUMIT שלו קפוא (obligo, circuit open).
- **org2 אליהב:** בנק חי (2,000 תנועות). בתיק ההנה"ח: **הזנה ×4 במנה (ניפוח ₪9,623) + קבלת ₪30K כפולה — אסור לשמור דוח לפני ניקוי!** 70310/70311+4 הכנסות חסרים בתיק ("הורדת חומרים" לא בוצעה). 16 טיוטות בעסק. sync שלו עובד (12:01 ✓).
- **טבלת payments מזוהמת:** 14 "תקבולים" שהם זיכויים (org1 ₪215K, org2 ₪493K) — **מחיקה ממתינה לאישור בעלים**.
- ה-obligo של SUMIT פוגע כרגע רק ב-org1 (אינטרמיטנטי לפי צריכה).

## פעולות בעלים פתוחות (לפי דחיפות)
1. הסדרת ה-ActionsBilling obligo ב-SUMIT (חוב פעולות — תשלום/שדרוג; "פריקת חוב" שנכשלה = חסימה).
2. ניקוי כפילויות ×4 + אימות קבלת ₪30K בתיק אליהב לפני כל שמירת דוח.
3. החלטת תיוק: 262 קבצי עמית + 16 של אליהב — צוות ידני / browser-automation (פיילוט קודם). + הרצת "הורדת חומרים"/יבוא הכנסות בתיקים.
4. חידוש חיבור שע"מ (לא פעיל; פג כל 3 חודשים — תזכורת אוטומטית קיימת עכשיו).
5. אישור מחיקת 14 התקבולים המזויפים.
6. בירור: האם דוח מע"מ 05-06/26 של עמית כבר הוגש מחוץ ל-SUMIT (הלוח מציג "הבא: 07-08/26").
7. ANTHROPIC_API_KEY (בוט; המכסה חוזרת 01/08) · SMTP · opt-in גבייה+נוסח · zהות Financy נפרדת פר-לקוח · מיזוג ל-main (~330 commits — לפתוח PR באישור) · החלפת סיסמת super_admin.

## תור הנדסי הבא
- backfill זיכויים/קבלות היסטורי לכל התיקים אחרי שחרור obligo (איפוס checkpoints של sumit/invoices פר-org + סנכרון אחד).
- קציר 62 הקבצים הנותרים (גריד "כל הקבצים לתיוק" /f2114194212/v839662703/ עוקף את מגבלת ה-200).
- מילוי טיוטות רצף מהקציר — רק אחרי החלטת מסלול תיוק (סיכון כפל).
- שכפול ה-scorecard/מקצב לכל התיקים (גל C במודל ההפעלה); מדיצ'י ממתין למפתח.
- P2 מהתכניות: לוח מיסים ותשלומים, ריטיינרים מחזוריים, M5 פקודות יומן (createbatch — אין מתודה עדיין).

## סביבת עבודה
- suite: `source .venv/bin/activate && python -m pytest tests/ -q -p no:warnings` (1,035). QA: `python scripts/qa_gate.py`. smoke: `SMOKE_EMAIL=... SMOKE_PASSWORD=... python scripts/prod_smoke.py`.
- deploy: `vercel deploy --prod --yes` → מיגרציות: `POST /api/admin/db/migrate` (עם JWT admin) → smoke.
- crons חיים: sync-sumit שעתי, sync-open-finance 05:30, enrich, gap-scan 06:15, daily-close 06:30, collections 07:00.
- **Vercel bot-checkpoint** חסם curl ל-API אתמול תחת עומס (משתחרר לבד; דפדפן לא מושפע). אימות חלופי: הרצת שירותים לוקלית מול DB פרוד (read-only) עם `hostaddr` בעת תקלת DNS.
- **סביבת ה-CLI שודרגה (14/07, /doctor):** Claude Code 2.1.63→2.1.209, defaultMode=auto, 23 פלאגינים לא-בשימוש כובו (גיבוי: `~/.claude/settings.json.doctor-backup-20260714`), עותק nvm כפול הוסר.
- גישה מלאה לפרוד מאושרת additive בלבד; מחיקות — רק באישור מפורש.
