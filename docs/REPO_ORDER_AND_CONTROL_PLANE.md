# סדר הריפו ושכבות ההנחיה לסוכנים (control plane)

נכתב 2026-07-25, על בסיס `origin/main` @ `1844af7`. מתאר את המצב בפועל — מה נמדד, מה
שונה בסבב הסדר הזה, ומה נשאר פתוח.

## 1. מצב מדוד

| מדד | ערך |
| --- | --- |
| מודולי Python ב-`src/cfo/` | 152 (40 routers, 102 services) |
| השורות הגדולות | `sumit_integration.py` 2,847 · `models.py` 1,734 · `routes/admin.py` 1,514 |
| קבצי טסט / טסטים | 147 קבצים · **1,318 עוברים**, 0 נכשלים, ~250 שנ' |
| אזהרות בסוויטה | 18,696 — כמעט כולן `datetime.utcnow()` deprecation |
| מסמכי `.md` בשורש (לפני) | 17 · **(אחרי) 3** — README, CLAUDE, AGENTS |
| lint | frontend: eslint `--max-warnings 0`. backend: **אין** ruff/mypy |
| CI | `.github/workflows/ci.yml` — pytest + frontend build. אין lint ל-frontend ב-CI |

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

### 2.2 שכבת skills — עודף, לא חוסר

שלושה עצים מקבילים עם תוכן חופף: `.claude/skills/` (~30 skills, ~179 קבצים),
`.agents/skills/`, `.cursor/skills/`. סביר ש-`.agents/` הוא של Codex ו-`.cursor/` של Cursor
— ולכן **לא נמחק כלום**: מחיקה עלולה לשבור בדיוק את הסוכן שעומדים להריץ.
ההמלצה: `.claude/skills/` הוא הקנוני; לגבי השניים האחרים ראו §5.

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

ה-hook נבדק ב-6 pipe-tests (2 חסימות Bash, 1 חסימת עריכה, 3 מסלולים מותרים) — כולם עברו.
`permissions.deny` ב-`settings.json` מכסה את אותם סקריפטים כחגורה שנייה.

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
| דדופ `.agents/skills` ו-`.cursor/skills` | **מוחזק** | סביר שאלה עצי ה-skills של Codex ושל Cursor. מחיקה עלולה לשבור סוכן פעיל. נדרשת הכרעת בעלים אילו מהם חיים. |
| 18,696 אזהרות `utcnow()` | **לא נוגע** | `datetime.now(UTC)` מחזיר tz-aware; השוואה מול עמודות DB נאיביות זורקת `TypeError`. סבב גורף = שבירה. מודול-מודול, טסטים ירוקים כשער. |
| אין lint ל-Python | פתוח | הוספת `ruff` היא שינוי מוסכמות לכל הריפו — החלטת בעלים, לא תוצר של סדר. |
| `npm run lint` לא ב-CI | פתוח | ה-CI בונה frontend אך לא מריץ eslint. תוספת של שורה אחת, אבל תיפול על אזהרות קיימות עד שינוקו. |
| `main` מקומי 373 קומיטים מאחור | ידוע | הענף הזה נחתך מ-`origin/main`. `git checkout main && git pull` בהזדמנות. |
| קבצים כבדים בעץ העבודה | ידוע | `cfo.db` (430KB), גיבוי `.bak` (520KB), `reports/` — כולם ב-`.gitignore`, לא במעקב. הריפו 760MB בעיקר מ-`.git` ו-`node_modules`. |
| `models.py` 1,734 שורות / `sumit_integration.py` 2,847 | פתוח | מועמדים לפיצול, אבל פיצול בלי צורך תפעולי הוא רפקטור לשם רפקטור. |

## 6. איך מריצים בדיקות

```bash
python -m pytest tests/ -q            # 1,318 עוברים, ~250 שנ' (בסיס 2026-07-25)
python scripts/qa_gate.py             # שער QA מקומי
python scripts/audit_routes.py        # ~231 routes
python scripts/schema_drift_check.py  # דריפט סכימה
cd frontend && npm run build && npm run lint
```

- דרך Claude Code: הסוכן `qa-runner` מריץ את כל הרצף ומחזיר דוח תמציתי.
- דרך Codex: `docs/prompts/codex-qa-run.md` — פרומפט מוכן להעתקה, עם הרשימה השחורה בפנים.
- לפני כל דיווח לרשויות: הסוכן `filing-verifier` (אימות משולש).
