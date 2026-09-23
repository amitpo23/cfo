# כניסה למפתח חדש — רצף

עודכן: 23.09.2026. המסמך הזה עוסק בגישת פיתוח ובבדיקות כניסה. סטטוס המוצר נשאר ב־[`MASTER_EXECUTION_PLAN.md`](MASTER_EXECUTION_PLAN.md).

## מה לקרוא, בסדר הזה

1. [`../CLAUDE.md`](../CLAUDE.md) ו־[`../AGENTS.md`](../AGENTS.md) — כללי עבודה, בדיקות וגבולות הפעולה.
2. [`REZEF_OPERATING_SYSTEM.md`](REZEF_OPERATING_SYSTEM.md) — החוזה הארכיטקטוני.
3. [`MASTER_EXECUTION_PLAN.md`](MASTER_EXECUTION_PLAN.md) — לוח הסטטוס הפעיל.
4. [`rezef_capabilities.json`](rezef_capabilities.json) — יכולות, ראיות וגבולות.
5. [`BOOKKEEPER_ARMY_OPERATING_MODEL.md`](BOOKKEEPER_ARMY_OPERATING_MODEL.md) — תהליך העבודה ו־SOP.
6. [`superpowers/plans/2026-09-22-new-developer-handoff.md`](superpowers/plans/2026-09-22-new-developer-handoff.md) — ביקורת היסטורית וספרינט מוצע. סעיף מצב עדכני בראשו גובר על המספרים מ־22.09.

## קוד וסביבת עבודה

- הריפו: `https://github.com/amitpo23/cfo`. ענף הפיתוח הנוכחי: `fix/rezef-stabilization-20260906`, שפורסם ב־GitHub ב־23.09 במסגרת [PR #39](https://github.com/amitpo23/cfo/pull/39). אין לעבוד מ־`main` כאילו הוא כולל את הענף: ה־PR עדיין טיוטה ולא מוזג. עדכון `main` שעוצר את cron SUMIT שולב בענף. יש לבדוק את מצב ה־CI וה־PR לפני מסירה או מיזוג.
- Python 3.12, Node 20 ו־Docker Desktop. הוראות ההרצה: [`DOCKER_LOCAL.md`](DOCKER_LOCAL.md). `docker compose up -d --build` משתמש ב־Postgres מקומי, `AUTH_BYPASS_ENABLED=true` ומפתחות ספק ריקים; הפורטים מוגבלים ל־`127.0.0.1`. ב־23.09 שלושת הקונטיינרים עלו במצב `healthy`, ‏`http://localhost:8080/healthz` החזיר 200 ו־`http://localhost:8001/api/health` דיווח `database=ok`.
- סנדבוקס ענן נפרד לפי הגדרת הבעלים: `https://cfo-dev-sandbox.vercel.app`. מזהה פרויקט Vercel שלו שונה מזה של `cfo-2` ואומת מקומית. קוד ההרשמה/גישה אישית נמסרים בערוץ פרטי על ידי הבעלים; אין לשמור אותם ב־Git. ב־23.09 נפרס אליו ה־commit `3e32668` כ־deployment `dpl_wGj4cbEKf4o6xsyjQKNCNEeZTgox`, קודם לכתובת הקבועה, וזו החזירה `database=ok` ו־Alembic `c81e6395fd71`. כניסה לחשבון הבדיקה הקיים החזירה 200 לפני הקידום. ניסיון לרשום את כל הארגונים עם אותו חשבון החזיר 403, לכן אין לו גישת `SUPER_ADMIN` לפלטפורמה. בידוד המסד עצמו, הרשמה ויצירת חשבון אישי טרם אומתו עצמאית.
- בפריסה הישנה מ־22.09 הופיע `sync-sumit` כ־cron יומי. הפריסה החדשה אושרה ב־Vercel כ־`Ready` עם שבעה cron jobs וללא `sync-sumit`. ברשימת **שמות** משתני הסביבה של פרויקט הסנדבוקס לא הופיע מפתח SUMIT (הערכים לא נקראו). לפני חיבור ספק יש לאמת שוב את תצורת הפריסה.
- פריסה מה־checkout המקומי דורשת `vercel deploy --dry` וביקורת רשימת הקבצים: ב־23.09 נמצאו בו גיבויי SQL, חשבוניות תחת `tmp/` וקובצי לקוחות תחת `reports/`. הם נחסמו ב־`.vercelignore`, ובבדיקה יבשה חוזרת לא הופיעו ברשימת ההעלאה. להעדיף ארכיון Git נקי כדי שלא להעלות קבצים מקומיים שנוצרו אחרי הבדיקה.
- תיקיית `.vercel/` המקומית בעמדת הבעלים מקושרת ל־`cfo-2`, פרויקט הפרוד האמיתי. אין להריץ ממנה `vercel deploy` ללא יעד מפורש. לפריסת סנדבוקס משתמשים בתיקייה נקייה שמקושרת ל־`cfo-dev-sandbox`, מאמתים את שם הפרויקט ב־dry run, ורק אז פועלים לפי הרשאת הבעלים.
- בדיקות מקומיות: `.venv/bin/python -m pytest tests/ -q` לאחר התקנת התלויות; `cd frontend && npm ci && npm run lint && npm run build`. את כל סוויטת pytest מריצים פעם אחת בלבד, ללא ריצה מקבילה. ב־23.09 הענף העדכני עבר **2,839 טסטים** אחרי שילוב `main` ותיקוני הסביבה; מצב ה־CI של שינוי עתידי נבדק מחדש ב־PR.
- `rezef_capabilities.json` מכיל 12 יכולות ו־262 הפניות לקובצי ידע/קוד/בדיקות; כל 262 הנתיבים קיימים בעץ הנוכחי. קיום קובץ אינו הוכחה שהיכולת חיה בפרוד.

## מושקו, Meta, ידע ומסדים

- **מושקו:** מפת הקוד ב־[`../DEVELOPER.md`](../DEVELOPER.md), תוכנית ומצב ב־[`REZEF_MOSHKO_OPERATING_PLAN.md`](REZEF_MOSHKO_OPERATING_PLAN.md), והפעלת ערוצים ב־[`MOSHKO_ACTIVATION_RUNBOOK.md`](MOSHKO_ACTIVATION_RUNBOOK.md). לולאת השיחה היא `src/cfo/services/ai_chat_service.py`, קטלוג הכלים ב־`ai_chat_tools.py`, הממשק ב־`/ai-chat` וב־`/agent/{session_id}`, והניטור ב־`/admin-moshko`. קיום קוד או runbook אינו הוכחה שהערוץ החי הוגדר.
- **Meta/WhatsApp:** הקוד נמצא ב־`src/cfo/api/routes/whatsapp_webhook.py` וב־`src/cfo/services/whatsapp_gateway.py`. הנתיב הוא `/api/whatsapp/webhook`. `MOSHKO_ACTIVATION_RUNBOOK.md` מתאר את רצף SMTP, הסודות, ה־webhook, שיוך האפליקציה ל־WABA ואימות זהות המשתמש. אלה פעולות בעלים; אין להריץ את סקריפט הבדיקה החי או לחבר מספר/טוקן בלי תיאום. הוראות הפריסה הממוספרות בתחילת ה־runbook הן היסטוריות; סטטוס נוכחי נמצא ב־`MASTER_EXECUTION_PLAN.md` וב־PR.
- **ידע:** [`README.md`](README.md) הוא אינדקס התיעוד. מושקו טוען בזמן ריצה את `docs/bookkeeper_kb/`, את `docs/sumit_help_kb/` ואת נוהלי `procedures` דרך `src/cfo/services/kb_loader.py`; ידע המוצר נמצא ב־`src/cfo/services/rezef_kb.py`. מסך קריאה וניהול ידע נמצא ב־`/admin-moshko-knowledge`. בסיס ידע SUMIT ובסיס ידע Open Finance מתועדים בנפרד באינדקס. יש לאמת אריזת `docs/` בפריסה לפני שמניחים שהידע זמין למושקו.
- **DB:** [`DATABASE_MAP.md`](DATABASE_MAP.md) מפריד בין SQLite מקומי, Postgres מקומי ב־Docker והמסד האמיתי ב־Neon; מצב הסנדבוקס מתועד לעיל, אך בידוד המסד שלו טרם אומת עצמאית. המודלים נמצאים ב־`src/cfo/models.py`, המיגרציות ב־`alembic/`, וחיבורי ספק נשמרים ב־`integration_connections` המוצפנת. נתוני ארגונים חיים במסד משותף עם שיוך ארגוני. גישה ל־Neon האמיתי נמסרת אישית, לקריאה בלבד אם אושרה; אין לשים מחרוזת חיבור או סודות ב־Git, במסמך מסירה או במייל.

```bash
git clone https://github.com/amitpo23/cfo.git
cd cfo
git switch fix/rezef-stabilization-20260906
docker compose up -d --build
curl -fsS http://localhost:8001/api/health
curl -fsS http://localhost:8080/healthz
```

## גישה שאינה עוברת עם clone

| משאב | מסלול גישה | מצב האימות כאן |
| --- | --- | --- |
| GitHub | הריפו הציבורי ניתן לשכפול; הרשאת כתיבה ניתנת להזמנת GitHub לחשבון האישי של המפתח | קריאה לענף אומתה; הרשאת כתיבה לא הוקצתה |
| סנדבוקס Vercel + DB נפרד | חשבון אישי בסנדבוקס; גישת פרויקט/מסד תינתן רק לפי תפקיד וצורך | deployment, health וכניסת חשבון הבדיקה אומתו; בידוד DB, הזמנה והרשאות אישיות לא אומתו |
| נתוני לקוחות אמיתיים | חיבור SQL אישי עם `SELECT` בלבד, דרך ערוץ סודות מאושר, אם הבעלים מאשר צורך עסקי | פרטי חיבור והרשאות לא אומתו; אין להכניסם ל־Git או למייל |
| פרוד `cfo-2.vercel.app` | הרשאות נפרדות ומוגבלות, רק לפי אישור הבעלים | שום גישה לא הוקצתה או נבדקה במסגרת מסירה זו |

אין להעביר למפתח סיסמת אדמין משותפת, URL למסד אמיתי או מפתחות ספק במייל. עדיף חשבון אישי והרשאה מדורגת עם אפשרות ביטול. גישת קריאה לנתונים אמיתיים אינה הרשאת כתיבה, ואין להשתמש בסודות פרוד בסנדבוקס או במחשב מקומי.

## גבולות עבודה ומסירה

- אין להריץ סקריפטים חיים או לקרוא ל־SUMIT/Open Finance בלי verify-first ואישור מתאים; רשימת הפקודות החסומות נמצאת ב־[`../AGENTS.md`](../AGENTS.md).
- אין פריסה לפרוד, שינוי סכימה בפרוד, תשלום, שידור או סגירת מנה בלי אישור בעלים ותהליך [`GATE0_DEPLOYMENT_RUNBOOK.md`](GATE0_DEPLOYMENT_RUNBOOK.md).
- שינויי קוד ותיעוד עוברים בדיקות, commit על ענף, PR וסקירה; אין commit ל־`main`.
- פרטי גישה אישיים, מצב הזמנות Vercel/Neon ויכולת כניסה מלאה לסנדבוקס דורשים אימות עם זהות המפתח. עד אז אין להציג את ההעברה כגישה מלאה.
