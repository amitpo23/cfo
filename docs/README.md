# אינדקס התיעוד — רצף

נקודת הכניסה לפי סוג העבודה. מסמך שלא מופיע כאן הוא או ארכיון (`archive/`) או תיעוד
עזר נקודתי.

## חובה לפני עבודה

| מתי | מה לטעון |
| --- | --- |
| כל משימת מוצר/יכולת | [`REZEF_OPERATING_SYSTEM.md`](REZEF_OPERATING_SYSTEM.md) — חוזה יציב; [`rezef_capabilities.json`](rezef_capabilities.json) — סטטוס וראיות ברי-בדיקה |
| עבודה חשבונאית/מיסויית | [`bookkeeper_kb/README.md`](bookkeeper_kb/README.md) — הכרה בהוצאות, ניכוי תשומות, תקנה 14/18, שער-מסמך |
| כל פעולה בפורטל/API של SUMIT | [`SUMIT_KNOWLEDGE_BASE.md`](SUMIT_KNOWLEDGE_BASE.md) — 609 מאמרי עזרה, ספר החוקים |
| מודל התפעול היומי/חודשי | [`BOOKKEEPER_ARMY_OPERATING_MODEL.md`](BOOKKEEPER_ARMY_OPERATING_MODEL.md) — workflow + 12 SOP |
| כתיבת קוד / הרצת בדיקות | [`../CLAUDE.md`](../CLAUDE.md), [`../AGENTS.md`](../AGENTS.md) |

**נגיש למושקו בזמן ריצה** דרך `kb_lookup` (`src/cfo/services/kb_loader.py`), מרכז ידע
`procedures`: `BOOKKEEPER_ARMY_OPERATING_MODEL.md`, `REZEF_OPERATING_SYSTEM.md`,
`SUMIT_BOOKS_BATCH_UNIFICATION_PLAYBOOK.md` — לצד שני מרכזי הידע הקיימים
(`bookkeeper_kb`, `sumit_help_kb`). כך "מה סדר הפעולות ל-X" נענה מתוך הנוהל בפועל,
לא מזיכרון.

## מקורות אמת — אינטגרציות

- [`SUMIT_KNOWLEDGE_BASE.md`](SUMIT_KNOWLEDGE_BASE.md) · [`SUMIT_API_REFERENCE.md`](SUMIT_API_REFERENCE.md) · [`sumit_swagger_v1_2026-07-10.json`](sumit_swagger_v1_2026-07-10.json) · [`sumit_help_kb/`](sumit_help_kb/)
- [`SUMIT_INTEGRATION_GUIDE.md`](SUMIT_INTEGRATION_GUIDE.md) · [`SUMIT_BOOKS_BATCH_UNIFICATION_PLAYBOOK.md`](SUMIT_BOOKS_BATCH_UNIFICATION_PLAYBOOK.md) (סגירת מנה = רישום בלתי-הפיך)
- [`OPEN_FINANCE_KNOWLEDGE_BASE.md`](OPEN_FINANCE_KNOWLEDGE_BASE.md) · [`OPEN_FINANCE_API_REFERENCE.md`](OPEN_FINANCE_API_REFERENCE.md) · [`OPEN_FINANCE_PROVIDER_COVERAGE.md`](OPEN_FINANCE_PROVIDER_COVERAGE.md)

## ארכיטקטורה ותפעול

- [`REZEF_OPERATING_SYSTEM.md`](REZEF_OPERATING_SYSTEM.md) — בעלות נתונים, תפקידים, workflow יומי, שערים וארכיטקטורת היעד
- [`GATE0_DEPLOYMENT_RUNBOOK.md`](GATE0_DEPLOYMENT_RUNBOOK.md) — פריסה ושינוי סכימה גלובלי באישור בעלים, עם עצירה לפני `head` שקרי
- [`IRREVERSIBLE_ACTION_CONTROL.md`](IRREVERSIBLE_ACTION_CONTROL.md) — הצעה, אישור, ביצוע יחיד ו-readback לתשלום/שידור/סגירה
- [`TELEGRAM_CHANNEL_RUNBOOK.md`](TELEGRAM_CHANNEL_RUNBOOK.md) — הפעלת ערוץ השיחה (בוט, סודות, מיגרציה, קישור זהות) — פעולות בעלים בלבד
- [`MOSHKO_ACTIVATION_RUNBOOK.md`](MOSHKO_ACTIVATION_RUNBOOK.md) — **מדריך ההפעלה המלא של מושקו**: אימות SUMIT/Open Finance, גישה לידע וליכולות, הקמת WhatsApp, חיבור העוסק, ומה לבדוק
- [`rezef_capabilities.json`](rezef_capabilities.json) — חוזה היכולות המכונתי; נבדק מול קוד וטסטים
- [`DATABASE_MAP.md`](DATABASE_MAP.md) — מודל הנתונים
- [`PERMISSIONS.md`](PERMISSIONS.md) · [`AUTH_ROADMAP.md`](AUTH_ROADMAP.md) — הרשאות ורב-דיירות
- [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md) — מצב מוכנות לפרוד
- [`DOCKER_LOCAL.md`](DOCKER_LOCAL.md) — הרמה מקומית
- [`REPO_ORDER_AND_CONTROL_PLANE.md`](REPO_ORDER_AND_CONTROL_PLANE.md) — סדר הריפו ושכבות ההנחיה לסוכנים
- [`REZEF_CLI_ROADMAP.md`](REZEF_CLI_ROADMAP.md) — מצב ה־CLI הישן וחוזה CLI/MCP עתידי (בחניון עד סגירת שער 0)
- [`.agents/skills/rezef-operator/`](../.agents/skills/rezef-operator/) — נתב Codex למקורות האמת (אינו משכפל ידע)
- [`guides/`](guides/) — מדריכי אינטגרציה ורב-דיירות, כיסוי מודולי SUMIT

## תוכניות ומצב

- [`MASTER_EXECUTION_PLAN.md`](MASTER_EXECUTION_PLAN.md) — **לוח הביצוע הפעיל** (שערים 0-6)
- [`REZEF_DEEP_PLAN_2026-08-20.md`](REZEF_DEEP_PLAN_2026-08-20.md) — **תוכנית העומק הפעילה**: בקאופיס האימון של מושקו, אטימת מכסות, והרחבת קטלוג הכלים (W1–W5, מבוסס 3 חקירות קוד עם ראיות)
- [`../DEVELOPER.md`](../DEVELOPER.md) — מדריך המפתח: מפת תיקיות, הרצה, שערי איכות, "איפה כל דבר של מושקו"
- [`superpowers/plans/`](superpowers/plans/) — תוכניות סשן והעברות מקל (chronological)
- [`audits/`](audits/) — דוחות ביקורת

`PROJECT_STATUS.md`, `WORKFLOW_AUDIT.md`, `REZEF_OPERATING_MODEL.md`,
`REZEF_MASTER_ORCHESTRATION_PLAN.md`, תוכניות ה-completion/TODO ומפות הכיסוי
המתוארכות נשמרות כהיסטוריה. אין להשתמש בהן כסטטוס נוכחי.

## ארכיון — לא מקור אמת

[`archive/`](archive/) — תמונות מצב היסטוריות (PHASE_9/13/14, *_COMPLETION_SUMMARY,
FINAL_STATUS_REPORT ועוד). מתארות את מה שהיה נכון בזמן הכתיבה. **לא להסתמך עליהן** לגבי
המצב הנוכחי — לאמת מול הקוד והטסטים.
