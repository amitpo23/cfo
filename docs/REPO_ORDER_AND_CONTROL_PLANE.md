# סדר הריפו ושכבות ההנחיה לסוכנים (control plane)

נכתב 2026-07-25 ועודכן במדידה 2026-08-09. מתאר את המצב בפועל — מה נמדד, מה
שונה בסבב הסדר הזה, ומה נשאר פתוח.

## 1. מצב מדוד

| מדד | ערך |
| --- | --- |
| מודולי Python ב-`src/cfo/` | 152 (40 routers, 102 services) |
| השורות הגדולות | `sumit_integration.py` 2,847 · `models.py` 1,734 · `routes/admin.py` 1,514 |
| קבצי טסט / טסטים | 184 קבצי `test_*.py` · **1,847 עוברים**, 0 נכשלים, ~369 שנ' |
| אזהרות בסוויטה | 27,171 — כמעט כולן `datetime.utcnow()` deprecation |
| `audit_routes.py` | **260 routes**: 177 תקין · 45 אזהרה(4xx) · 37 מוגדר-סביבה · **1 כשל** (honest-null) |
| `schema_drift_check.py` (מקומי) | **נכשל** — ארבע עמודות action-state ואינדקס חסרים ב-`ai_chat_messages`; ה-SQLite המקומי טרם הורץ למיגרציה החדשה. לא רגרסיה בקוד |
| `qa_gate.py` | אדום בבסיס על שער אחד: schema drift מקומי (DB מיושן) |
| מסמכי `.md` בשורש (לפני) | 17 · **(אחרי) 3** — README, CLAUDE, AGENTS |
| lint | frontend: `npm run lint` עובר באפס אזהרות. backend: **אין** ruff/mypy |
| CI | `.github/workflows/ci.yml` — pytest + frontend lint + frontend build |

## 2. שכבות ההנחיה — מה קיים ומה נוסף

חמש השכבות של control plane, מול המצב בפועל:

| שכבה | תפקיד | מצב לפני | מצב אחרי |
| --- | --- | --- | --- |
| **01 CLAUDE.md** | תמיד-דלוק: ארכיטקטורה, פקודות, דוקטרינות | ✅ קיים ו**נכון** — 1.8KB, דוקטרינות בלבד | ללא שינוי (במכוון) |
| **02 rules** (scoped) | הנחיות שנטענות לפי היקף/קובץ | ❌ אין | ראו §2.1 — המנגנון בפועל שונה מהאינפוגרפיקה |
| **03 skills** | פלייבוקים חוזרים | ✅ **עודף** — 3 עצי skills מקבילים | תועד; דדופ מוחזק לשאלה פתוחה |
| **04 agents** | מומחים בקונטקסט מבודד | ❌ אין | ✅ `.claude/agents/qa-runner.md`, `filing-verifier.md` |
| **05 hooks + settings.json** | אכיפה דטרמיניסטית | ❌ רק `settings.local.json` (הרשאות, בלי hooks) | ✅ `.claude/settings.json` משותף + hook נבדק |

### 2.1 שכבת "rules" — למה לא נבנתה כ-`.claude/rules/`

`grep` על הריפו ועל התיעוד לא מצא שום מנגנון שקורא `.claude/rules/*.md`. תיקייה כזאת
הייתה קישוט. המנגנונים שבאמת טוענים הנחיות ממוקדות-היקף:

- **`CLAUDE.md` מקונן** בתת-תיקייה — נטען כשעובדים בה. כרגע יש רק אחד, בשורש.
- **ייבוא `@path`** מתוך `CLAUDE.md` השורשי.
- **`AGENTS.md`** — מה שסוכנים שאינם Claude Code (Codex, למשל) קוראים.

לכן שכבה 02 מומשה כ-`AGENTS.md` בשורש + הפניות מפורשות מ-`CLAUDE.md` למרכזי הידע.
הצעה פתוחה (לא בוצעה): `src/cfo/api/routes/CLAUDE.md` עם חוזה ה-routes ותבניות
ה-org-scope, ו-`frontend/CLAUDE.md` עם מוסכמות ה-UI. לא נוצרו כדי לא לנפח קונטקסט לפני
שיש תוכן שמצדיק את זה.

### 2.2 שכבת skills — נתב רזה במקום ידע כפול

שלושה עצים מקבילים עדיין קיימים: `.claude/skills/`, `.agents/skills/`,
`.cursor/skills/`. אין להפוך אף אחד מהם למקור ידע חשבונאי נפרד. מקור האמת הוא
`docs/rezef_capabilities.json` ומרכזי הידע שאליהם הוא מפנה.

ב-2026-07-25 נוסף `.agents/skills/rezef-operator/` כנתב Codex רזה: הוא בוחר יכולת,
טוען את ה-KB וה-SOP הקנוניים ומחיל את השערים. שלד `data` הריק הוסר. skills כלליים
בעצי `.claude`/`.agents` נשארים חומר עזר בלבד ואינם רשאים לעקוף את החוזה.

24 מה-skills מכובים ב-`settings.local.json` (`skillOverrides: off`). **זה לא פגם** — זה
תקצוב קונטקסט מכוון, בדיוק מה שהאינפוגרפיקה מטיפה לו.

### 2.3 מה ה-hook אוכף

`.claude/hooks/guard-costly-and-generated.sh`, מחווט ב-`PreToolUse` על `Bash` ועל
`Write|Edit|NotebookEdit`. חוסם שני דברים ששום הנחיה טקסטואלית לא מבטיחה:

1. **סקריפטים עם קריאות חיות / כתיבה לפרוד.** נבדק פר-סקריפט, לא לפי ניחוש:
   `production_readiness_check.py` עושה ping ל-SUMIT ול-Open Finance; `prod_smoke.py`
   פותח `httpx` מול הפרוד; `run_ocr_pipeline.py`/`classify_expenses.py` מורידים מסמכים
   מ-SUMIT ומתייקים. לעומתם `audit_routes.py` כופה SQLite זמני, ו-`qa_gate.py` /
   `schema_drift_check.py` נופלים ל-SQLite מקומי כשאין `DATABASE_URL` — ולכן **מותרים**,
   וה-hook חוסם רק את הווריאנט עם `--env-file`.
2. **עריכת מסמך מיוצר** — `docs/bookkeeper_kb/03-classification-bridge.md` מיוצר מ-
   `src/cfo/services/israeli_tax_rules.py`. עריכה ידנית שם נדרסת בריצת הרנדרר הבאה.

**מה נבדק:** 13 בדיקות ב-`.claude/hooks/` (חסימה בנתיב ישיר, דרך `cd`, דרך `uv run`,
דרך `bash -c`, `--env-file`, עריכת מסמך מיוצר; ומנגד: pytest, `qa_gate` מקומי,
`audit_routes`, `grep` על שם דומה, קומיט שמזכיר שם, עריכת קוד — עוברים). בנוסף הוא
**הוכח חי בפועל**: ניסיון להריץ את מערך הבדיקות מהצ'אט נחסם על ידו.

**גבולות שכדאי לדעת:**

- ההתאמה דורשת טוקן מפעיל (`python`/`node`/`uv run`/`bash`/`./`) לפני שם הסקריפט באותו
  מקטע פקודה. גרסה קודמת התאימה על השם בלבד וחסמה גם `grep` וקומיטים — over-block.
- קלט לא-תקין או `jq` חסר → **fail-closed** (חוסם עם הסבר), לא מעבר שקט.
- `permissions.deny` ב-`settings.json` מכסה רק את צורת ההפעלה המפורשת
  (`python scripts/X.py`) ולא וריאנטים כמו `uv run` או `cd scripts &&`. **האכיפה
  האמיתית היא ה-hook**; ה-deny הוא נוחות, לא שכבה שנייה.
- זהו מעקה נגד פעולה בשוגג, לא גבול אבטחה מול יריב.

## 3. סדר הקבצים — מה זז

- **17 → 3 מסמכים בשורש.** נשארו `README.md`, `CLAUDE.md`, `AGENTS.md` (חדש).
  - `docs/archive/` — 10 תמונות מצב היסטוריות (`PHASE_9/13/14`, `*_COMPLETION_SUMMARY`,
    `FINAL_STATUS_REPORT`, `PRODUCTION_FIXES_SUMMARY`, `COMPLETE_TASK_CHECKLIST`,
    `IMPLEMENTATION_SUMMARY`, `FINANCIAL_CONTROL_BLUEPRINT`). **לא נמחק** — `git mv`, הפיך.
  - `docs/guides/` — 5 מסמכים חיים: `INTEGRATION_GUIDE`, `MULTI_TENANT_GUIDE`,
    `OPEN_FINANCE_SETUP`, `SUMIT_MODULE_COVERAGE`, `QUICK_REFERENCE`.
  - נבדק לפני ההעברה: ההפניות אליהם בקוד ובטסטים הן ב-docstrings בלבד, אף אחת לא
    קוראת את הקובץ. אין קישור שנשבר.
- **`docs/README.md`** — אינדקס: מה לטעון לפי סוג העבודה, מקורות אמת, ומה ארכיון.
- **נמחק מהמעקב**: 6 קבצי `.playwright-mcp/*.yml` (פסולת ריצה) ו-`.gitignore.new`.
  `.playwright-mcp/` נוסף ל-`.gitignore`.

## 4. עץ היעד

```
cfo/
├── CLAUDE.md              # 01 — תמיד דלוק, דוקטרינות בלבד. לא לנפח.
├── AGENTS.md              # 02 — Codex/Cursor/Copilot: פקודות מאומתות + רשימה שחורה
├── README.md
├── .claude/
│   ├── settings.json      # 05 — משותף, בגיט: hooks + deny
│   ├── settings.local.json# אישי, לא בגיט: הרשאות + skillOverrides
│   ├── hooks/             # 05 — guard-costly-and-generated.sh
│   ├── agents/            # 04 — qa-runner, filing-verifier
│   └── skills/            # 03 — קנוני
├── src/cfo/ · frontend/ · tests/ · scripts/ · alembic/
└── docs/
    ├── README.md          # אינדקס
    ├── bookkeeper_kb/     # חובה לפני עבודה מיסויית
    ├── prompts/           # פרומפטים לסוכנים חיצוניים (codex-qa-run.md)
    ├── guides/ · audits/ · superpowers/
    └── archive/           # היסטוריה — לא מקור אמת
```

## 5. פתוח / לא בוצע — ולמה

| נושא | מצב | למה |
| --- | --- | --- |
| דדופ `.agents/skills` ו-`.cursor/skills` | **נפתר ברמת מקור האמת** | לא נמחקים עצי harness; הידע הקנוני עבר למניפסט/KB, ו-Codex משתמש בנתב `rezef-operator`. דדופ פיזי נשאר אופציונלי ואינו נדרש לעקביות. |
| 19,948 אזהרות `utcnow()` | **לא נוגע** | `datetime.now(UTC)` מחזיר tz-aware; השוואה מול עמודות DB נאיביות זורקת `TypeError`. סבב גורף = שבירה. מודול-מודול, טסטים ירוקים כשער. |
| אין lint ל-Python | פתוח | הוספת `ruff` היא שינוי מוסכמות לכל הריפו — החלטת בעלים, לא תוצר של סדר. |
| שער התקציב היומי הפיל טסט | **תוקן** | `/api/cron/sync` מחזיר `{"skipped": "daily_budget"}` בלי מפתחות התוצאה כשל-org יש `SyncCheckpoint` צעיר מ-20h. שני טסטי ה-cron ב-`test_auth_and_tenancy.py` לא שלטו בתנאי הזה ונשענו על מזל. נצפה כשל בודד ב-`qa_gate` שלא שוחזר ב-5 ריצות. תוקן ב-fixture `clear_sumit_sync_budget` — הטסט שולט בתנאי במקום לרדוף אחרי המזהם. |
| `npm run lint` שבור | **נפתר 09/08/2026** | נוסף `.eslintrc.cjs`, נוקו שגיאות hooks, וה־lint רץ גם ב־`qa_gate.py` וב־CI. |
| `main` מקומי 373 קומיטים מאחור | ידוע | הענף הזה נחתך מ-`origin/main`. `git checkout main && git pull` בהזדמנות. |
| קבצים כבדים בעץ העבודה | ידוע | `cfo.db` (430KB), גיבוי `.bak` (520KB), `reports/` — כולם ב-`.gitignore`, לא במעקב. הריפו 760MB בעיקר מ-`.git` ו-`node_modules`. |
| `models.py` 1,734 שורות / `sumit_integration.py` 2,847 | פתוח | מועמדים לפיצול, אבל פיצול בלי צורך תפעולי הוא רפקטור לשם רפקטור. |

## 6. איך מריצים בדיקות

```bash
python -m pytest tests/ -q            # 1,847 עוברים, ~369 שנ'
python scripts/audit_routes.py        # 260 routes, 1 כשל (honest-null)
python scripts/schema_drift_check.py  # נכשל מקומית — DB מיושן, לא רגרסיה
python scripts/qa_gate.py             # עוטף את כל הנ"ל + frontend
cd frontend && npm run lint           # אפס אזהרות
cd frontend && npm run build
```

הבסיסים המספריים לעיל נמדדו 2026-08-09 על ענף העבודה.

- דרך Claude Code: הסוכן `qa-runner` מריץ את כל הרצף ומחזיר דוח תמציתי.
- דרך Codex: `docs/prompts/codex-qa-run.md` — פרומפט מוכן להעתקה, עם הרשימה השחורה בפנים.
- לפני כל דיווח לרשויות: הסוכן `filing-verifier` (אימות משולש).
