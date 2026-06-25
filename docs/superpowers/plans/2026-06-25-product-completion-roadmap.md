# תוכנית-אב להשלמה ותיקון — CFO Platform (2026-06-25)

מסמך זה מרכז את **כל** העבודה הנותרת, מתועדף, ומבוסס על ממצאים מאומתים בלבד
(לא על ה-audit הרב-סוכני שהוכח כלא-אמין — ראו `docs/PHASE13_VERIFIED_BUG_SCAN.md`).
לכל פריט מסומן מקור-האמת ומצב האימות.

## עקרון מנחה
"אין נתון מזויף": כל מספר שמוצג למשתמש חייב להיגזר מנתון אמיתי או להיות מסומן
במפורש כ-derived/unsupported/draft. כל תיקון ב-TDD. commits תכופים. עבודה על
ענף `feat/sumit-ar-ap-documents-ocr`.

---

## מצב נוכחי (הושלם בסבב 2026-06-25, commit `e8ccf0f`)
- ✅ `forecasting_advanced` — delegation לשירותים אמיתיים (היה hardcoded).
- ✅ `analytics_reporting` — 16 עמודות שגויות + 4 stubs תוקנו.
- ✅ `revenue_analytics` + `expense_analytics` — באג עמודות תוקן; category/region→"unsupported".
- ✅ `expense_intake_email` — import חסר.
- 373 טסטים עוברים; סורק עמודות דטרמיניסטי נקי.

---

## P0 — חוסמי production (דורשים פעולת משתמש/env; לא ניתן לסגור בקוד בלבד)
מקור: [[open-finance-integration-state]], [[accounting-engine-buildout]], roadmap.
1. **Open Finance לא חי** — `OPEN_FINANCE_USER_ID` חסר + מסע consent. חוסם זרימת בנק חיה ופריט סימן-הסכום.
2. **אימות write-back ל-SUMIT** — יצירת חשבונית/קבלה חזרה ל-SUMIT לא מאומתת.
3. **חוסמי deploy** — `DATABASE_URL` (Supabase), Google OAuth, סודות.
> פעולה: לתאם עם המשתמש; אין כאן משימת-קוד טהורה.

## P1 — פיצ'ר חדש: תזכורות גבייה אוטומטיות (SMS/מייל)
**מצב: מתוכנן במלואו** → `docs/superpowers/plans/2026-06-25-collection-reminders.md`.
רוב התשתית קיימת (ar_service templates, sumit.send_sms, Invoice.due_date, cron).
פערים שהתוכנית סוגרת: טבלת state להסלמה/anti-spam, חיווט שליחה אמיתית, cron יומי,
הגדרות SMTP למייל, דגל הפעלה פר-org. **זו העבודה המומלצת להתחיל בה.**

## P1 — תיקוני נתון מומצא (קבוצה B — אומת בסבב הזה, נדחה לסבב נפרד)
מקור: `docs/PHASE13_VERIFIED_BUG_SCAN.md` §B. כל אחד = משימת TDD קצרה.
1. **`dashboard_service.py:380`** — `cogs = expenses * 0.3` (אומדן שרירותי שמזין רווח גולמי בדשבורד).
   תיקון: לגזור COGS מקטגוריות הוצאה אמיתיות (עלות-מכר) או לסמן `cogs_estimated:true` + disclaimer, או להציג רווח תפעולי בלבד.
2. **`ai_intelligence_agent.py:262`** — fallback מחזיר `"[Analysis would be provided here]"`.
   תיקון: להחזיר סיכום נגזר-נתון אמיתי, או הודעת "אין מספיק נתון" כנה.
3. **`cash_flow_service.py:408,427`** — TODO: תזרים חשבוניות/הוצאות מ-SUMIT לא ממומש.
   תיקון: לחבר לנתון האמיתי (Invoice/Expense) או לסמן את הענף כלא-זמין.
4. **קלים** (`dashboard_service:46` net=gross, `revenue_analytics:219` profitability ללא עלויות,
   `ml_models:468` placeholder, `analytics_reporting:449` net=operating) — לסמן/לתעד או לגזור.

## P2 — פערי-סכמה שנחשפו (דורשים migration או החלטת מוצר)
מקור: `docs/PHASE13_VERIFIED_BUG_SCAN.md` §A-עמוק.
1. **revenue-by-category** — כרגע "unsupported". לתמיכה אמיתית: לגזור קטגוריה מ-`Invoice.line_items` (JSON) או להוסיף עמודה. החלטת מוצר.
2. **revenue-by-region** — "unsupported". דורש הוספת שדות גאוגרפיים ל-`Contact` (migration) + מילוי נתון. החלטת מוצר.

## P2 — פערי יכולת פתוחים (מ-roadmap; טעון אימות-ריצה לפני עבודה)
> ⚠️ ה-roadmap מ-19/6 חלקית מיושן; חלק כבר נסגרו (856, יתרות פתיחה, AgreementCashFlow,
> VAT split, AR hardcoded). לאמת מצב-ריצה לכל פריט לפני שמתחילים.
1. **טופס 6111** — declared ב-ReportType ללא generator (אומת לא-ממומש באודיט פאזה 13).
2. **ריבית חוק מוסר תשלומים** — Prime+2% על חשבוניות באיחור (משלים את פיצ'ר הגבייה).
3. **מכתבי התראה עבריים + תביעות קטנות** — הסלמה משפטית (המשך טבעי לפיצ'ר הגבייה).
4. **`date_trunc` על SQLite** (`forecasting_service`) — באג נאמנות-טסט בלבד; עובד ב-prod Postgres.

---

## רצף עבודה מומלץ
1. **פיצ'ר תזכורות הגבייה** (P1, ערך גבוה, תשתית מוכנה) — לפי התוכנית המפורטת.
2. **קבוצה B** (P1, תיקוני נתון מומצא, קצר) — להסרת מצגים מזויפים שנותרו.
3. **החלטת מוצר** על revenue category/region (P2) ועל P0 (Open Finance/SUMIT) — מול המשתמש.
4. שאר P2 לפי אימות-ריצה.

## אימות לפני "הושלם" (לכל פריט)
- טסט derivation שזורע נתון ומאמת גזירה (לא assert על היעדר magic-number).
- להריץ את `scratchpad/colscan.py` אם נגעת בשאילתות ORM.
- `python -m pytest tests/ -q` ירוק מלא לפני commit.
