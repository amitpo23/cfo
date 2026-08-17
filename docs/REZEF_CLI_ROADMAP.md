# CLI של רצף — מצב קיים וחוזה עתידי

**נבדק 13/08/2026 · חניון עד לאחר שער 0.** מסמך זה מתעד את ה־CLI; הוא אינו
אישור להפעיל קריאות ספק ואינו משנה את השער הפעיל ב־`MASTER_EXECUTION_PLAN.md`.

## החלטה

לא מטמיעים את חבילת `financy` בתוך מושקו ולא יוצרים ממנה data plane נוסף.
ה־API והשירותים הארגוניים של רצף נשארים מקור הגישה היחיד למוצר. Financy CLI
יכול לשמש כלי השוואה חיצוני ומוצמד־גרסה למפעיל מורשה בלבד.

CLI עתידי של רצף יהיה **לקוח דק של ה־HTTP API שלנו**. הוא לא יקרא ישירות ל־Neon,
SUMIT או Open Finance, ולא יבחר `organization_id=1` כברירת מחדל.

## המצב הקיים — `cfo`

ה־entrypoint מוגדר ב־`setup.py` כ־`cfo=cfo.cli:main`, אך `main` אינה קיימת.
הרצה מודולרית חושפת את הקבוצות `bank`, `cashflow`, `forecast`, `reports`, `sync`
ופקודות `init`, `run`, `config`, `test-sumit`.

הכלי **אינו בטוח לפעילות עסקית רב־ארגונית**:

- 19 קריאות מקובעות ל־`organization_id=1`;
- אין אימות משתמש, חברות פעילה, תפקיד או בחירת ארגון מפורשת;
- `config` מציג `database_url` ועלול לחשוף סוד שמוטמע ב־URL;
- `sync documents|payments|all` פונה לשירות legacy שהוצא משימוש;
- `test-sumit` מבצע קריאת ספק חיה בלי זרימת אישור מפורשת;
- אין `--json`, חוזה pagination או קודי יציאה יציבים;
- אין פקודות Open Finance.

עד להחלפתו: אין להשתמש ב־`cfo` לפעולות עסקיות, סנכרון או בדיקות ספק.

## שכבת Open Finance שעליה ה־CLI יישען

ה־backend כולל כעת, אופליין בלבד:

| יכולת | API של רצף | גבול |
| --- | --- | --- |
| סטטוס נפרד לכל חיבור | `GET /api/open-finance/status` | DB-only; מציג `unknown` כשאין ראיית שיוך/טריות |
| חיבורים | `GET /api/open-finance/connections[/{id}]` | org-scoped |
| חשבונות | `GET /api/open-finance/accounts[/{id}]` | סינון אמיתי לפי `connection_id`; דורש sync חדש למילוי רשומות legacy |
| תנועות | `GET /api/open-finance/transactions[/{id}]` | DB-only; תאריך/חשבון/חיבור/ספק/סוג/cursor |
| קטגוריות | `GET /api/open-finance/categories` | snapshot cache; רענון מפורש בלבד |
| ספקים וסניפים | `GET /api/open-finance/providers`, `bank-branches` | cache + cooldown |
| רענון כל החיבורים | `POST /api/open-finance/connections/refresh-all` | admin, אישור מדויק, AuditLog ותביעה עמידה ל־20 שעות; 20 קרדיטים לפי Financy CLI v0.1.3 |

אין לפרש זאת כהוכחת פרוד: `open-finance-ingestion` נשארת `gated` עד consent,
תצורה ו־sync חי ומאומת לכל ארגון.

## חוזה הפקודות העתידי

שם בינארי מוצע: `rezef`. כל פקודה ארגונית דורשת token ו־`--org`; השרת מכריע
מחדש את `OrganizationMembership`. `SUPER_ADMIN` אינו מקבל ברירת מחדל.

```text
rezef auth login
rezef org list
rezef open-finance status --org <id>
rezef open-finance connections list|get <id> --org <id>
rezef open-finance accounts list|get <id> --org <id> [--connection <id>]
rezef open-finance transactions list|get <id> --org <id>
    [--account <id>] [--connection <id>] [--provider <id>]
    [--type BANK|CARD] [--from YYYY-MM-DD] [--to YYYY-MM-DD]
    [--limit N] [--cursor <cursor>] [--all]
rezef open-finance categories --org <id>
rezef open-finance providers list|branches --org <id>
rezef open-finance refresh-all --org <id> --reason <text>
```

דרישות רוחב:

1. `--json` מחזיר envelope יציב; שגיאות נשלחות ל־stderr.
2. קודי יציאה נבדלים: usage, auth, org-access, not-found, stale, budget, provider.
3. סודות לעולם אינם מודפסים, נשמרים בפקודה או נשלחים למודל.
4. קריאה רגילה היא DB-first. אין sync מרענון מסך, פקודת read או שאלת מושקו.
5. `--all` מדפדף רק בנתונים המקומיים; הוא לא עוקף page cap או מכסת ספק.
6. פעולת עלות/כתיבה מציגה תקציר, עלות ושער הרשאה ודורשת אישור מדויק.
7. כל פקודה נבדקת במטריצת org A/org B/SUPER_ADMIN ללא ארגון.

## MCP ומושקו

לא מחברים `financy mcp` ישירות ל־runtime. בעתיד MCP של רצף יעטוף את אותו API,
עם org scope, policy, AuditLog ו־honest-null. השלב הראשון יהיה read-only. פעולות
עלות או פעולות בלתי־הפיכות ימשיכו דרך propose → approve → claim → execute → verify.

## תנאי יציאה מהחניון

- שער 0 נסגר על תיק פיילוט עם Open Finance ו־SUMIT חיים;
- `open_finance_connection_id` התמלא בסנכרון ונבדק שאין חשבונות לא־משויכים;
- PR נפרד מוחק/מחליף את `src/cfo/cli.py` הישן, עם TDD;
- CLI → API בלבד; אפס ייבוא של `SessionLocal` או clients של ספק;
- בדיקות end-to-end מוכיחות הפרדת ארגונים, פלט JSON וקודי יציאה.
