# אינדקס התיעוד — רצף

נקודת הכניסה לפי סוג העבודה. מסמך שלא מופיע כאן הוא או ארכיון (`archive/`) או תיעוד
עזר נקודתי.

## חובה לפני עבודה

| מתי | מה לטעון |
| --- | --- |
| עבודה חשבונאית/מיסויית | [`bookkeeper_kb/README.md`](bookkeeper_kb/README.md) — הכרה בהוצאות, ניכוי תשומות, תקנה 14/18, שער-מסמך |
| כל פעולה בפורטל/API של SUMIT | [`SUMIT_KNOWLEDGE_BASE.md`](SUMIT_KNOWLEDGE_BASE.md) — 609 מאמרי עזרה, ספר החוקים |
| מודל התפעול היומי/חודשי | [`BOOKKEEPER_ARMY_OPERATING_MODEL.md`](BOOKKEEPER_ARMY_OPERATING_MODEL.md) — workflow + 12 SOP |
| כתיבת קוד / הרצת בדיקות | [`../CLAUDE.md`](../CLAUDE.md), [`../AGENTS.md`](../AGENTS.md) |

## מקורות אמת — אינטגרציות

- [`SUMIT_KNOWLEDGE_BASE.md`](SUMIT_KNOWLEDGE_BASE.md) · [`SUMIT_API_REFERENCE.md`](SUMIT_API_REFERENCE.md) · [`sumit_swagger_v1_2026-07-10.json`](sumit_swagger_v1_2026-07-10.json) · [`sumit_help_kb/`](sumit_help_kb/)
- [`SUMIT_INTEGRATION_GUIDE.md`](SUMIT_INTEGRATION_GUIDE.md) · [`SUMIT_BOOKS_BATCH_UNIFICATION_PLAYBOOK.md`](SUMIT_BOOKS_BATCH_UNIFICATION_PLAYBOOK.md) (סגירת מנה = רישום בלתי-הפיך)
- [`OPEN_FINANCE_KNOWLEDGE_BASE.md`](OPEN_FINANCE_KNOWLEDGE_BASE.md) · [`OPEN_FINANCE_API_REFERENCE.md`](OPEN_FINANCE_API_REFERENCE.md) · [`OPEN_FINANCE_PROVIDER_COVERAGE.md`](OPEN_FINANCE_PROVIDER_COVERAGE.md)

## ארכיטקטורה ותפעול

- [`DATABASE_MAP.md`](DATABASE_MAP.md) — מודל הנתונים
- [`PERMISSIONS.md`](PERMISSIONS.md) · [`AUTH_ROADMAP.md`](AUTH_ROADMAP.md) — הרשאות ורב-דיירות
- [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md) — מצב מוכנות לפרוד
- [`DOCKER_LOCAL.md`](DOCKER_LOCAL.md) — הרמה מקומית
- [`REPO_ORDER_AND_CONTROL_PLANE.md`](REPO_ORDER_AND_CONTROL_PLANE.md) — סדר הריפו ושכבות ההנחיה לסוכנים
- [`guides/`](guides/) — מדריכי אינטגרציה ורב-דיירות, כיסוי מודולי SUMIT

## תוכניות ומצב

- [`MASTER_EXECUTION_PLAN.md`](MASTER_EXECUTION_PLAN.md) — **לוח הביצוע הפעיל** (שערים 0-6)
- [`PROJECT_STATUS.md`](PROJECT_STATUS.md) — מצב נוכחי
- [`PRODUCT_AUDIT_AND_ROADMAP.md`](PRODUCT_AUDIT_AND_ROADMAP.md) · [`REZEF_CAPABILITY_COVERAGE_2026-07-12.md`](REZEF_CAPABILITY_COVERAGE_2026-07-12.md) — גריד יכולות
- [`superpowers/plans/`](superpowers/plans/) — תוכניות סשן והעברות מקל (chronological)
- [`audits/`](audits/) — דוחות ביקורת

## ארכיון — לא מקור אמת

[`archive/`](archive/) — תמונות מצב היסטוריות (PHASE_9/13/14, *_COMPLETION_SUMMARY,
FINAL_STATUS_REPORT ועוד). מתארות את מה שהיה נכון בזמן הכתיבה. **לא להסתמך עליהן** לגבי
המצב הנוכחי — לאמת מול הקוד והטסטים.
