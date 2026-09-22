# תוכנית + ספרינט — Handoff למתכנת חדש בפרויקט "רצף"

מקור: סוכן תכנון (Fable 5.1), הרצה מלאה עם אימות בפועל (pytest, git, audit_routes, schema_drift, frontend build/lint) — לא הועתק ממסמכים היסטוריים. איפה שלא ניתן היה לאמת (למשל drift מול Neon פרוד) מסומן honest-null במפורש. לא בוצעה קריאת רשת ל-SUMIT/Open Finance, לא commit, לא push, לא שינוי קובץ.

---

## ראש 1 — טבלת חוב טכני (נפרד לגמרי מ-C01–C36 ב-MASTER_EXECUTION_PLAN.md)

**הבהרה:** C01–C36 הם backlog מוצרי/תלוי-ספק/תלוי-בעלים — לא נכנסים לטבלה הזו.

### 1.1 — נמצא ואומת בסשן זה

| # | ממצא | חומרה | מאמץ | הוכחה |
|---|---|---|---|---|
| D0 | **הסוויטה המלאה אינה ירוקה כרגע.** `pytest tests/ -q` על עץ העבודה (ענף + 89 קבצים לא-committed): **6 failed, 2831 passed**, 1118.54s (18:38 דק'). סותר את "טסטים: חובה ירוק לפני commit" ב-CLAUDE.md. | קריטי לפני commit | קטן-בינוני | `/private/tmp/rezef-handoff-pytest-final.log` |
| D0a | `test_expense_classifier.py::test_file_all_without_sumit` נכשל (409 במקום 200) — טסט מיושן מול שער-אישור-לפני-ביצוע חדש (`irreversible_action_service`), לא רגרסיה. דורש הכרעת-בעלים: לעדכן טסט לזרימה החדשה. | בינוני | קטן | traceback שורה 42 |
| D0b | 4 כשלים ב-`test_expense_ocr_pipeline.py` — `auto_file=true` מצפה 200, מקבל 400 "X-Rezef-Approval-Id required". שער-אישור חדש נאכף גם על OCR אוטומטי. **דורש הכרעת-בעלים**: האם auto_file אמור לעקוף אישור אנושי (לא, לפי "אפס אוטונומיה")? אם לא — לעדכן 4 הטסטים. | בינוני-גבוה | בינוני | traceback שורות 56-197 |
| D0c | `test_per_key_gate_uses_real_credentials.py::test_the_gate_and_the_sync_share_the_same_source` נכשל — regression guard (בדיקת מקור-קוד) על שער ה-SUMIT cost-safety (מנע חזרה על חיוב org2, ₪62.23/יום). ריפקטור העביר לוגיקה מ-`get_connector_for_org` ל-`get_connection_configuration` (וידאתי: עדיין מכיל `IntegrationConnection`/`decrypt_credentials`) — כנראה false-positive, אבל **חובה לוודא בפועל** ולא רק לרכך את הטסט. | גבוה (שער הגנת-עלות אדום) | קטן | `sync_engine.py:1089-1106` מול `1114-1141` |
| D1 | `ai_analytics_service.py:456-480` — `from openai import OpenAI` (סינכרוני!) בתוך `async def get_ai_analysis` (route חי: `POST /api/ai/analysis`). חוסם event loop. מודל קשיח `"gpt-4"`. אין תיעוד usage/cost. | גבוה | קטן (`AsyncOpenAI`, ~10 שורות) | route מאומת חי |
| D2 | `ai_insights.py` — קוד מת (0 imports בייצור, מאומת ב-grep). אותו באג כמו D1, `gpt-4`, אין תיעוד. | נמוך (לא רץ) אך מבלבל | קטן (מחיקה) | grep מאומת |
| D3 | `moshko_reflector.py:20` — `MODEL="claude-sonnet-5"` קשיח, לא דרך settings. fail-quiet מכוון (יש docstring), אך אין תיעוד cost. | נמוך | קטן | קריאת קוד |
| D4 | אין שכבת abstraction אחידה ל-LLM — 5 נקודות קריאה נפרדות (2 תקינות עם cost-tracking, 1 תקינה בלי cost-tracking, 1 sync-bug חי, 1 קוד מת). | בינוני (תחזוקתיות) | גדול | grep ממצה |
| D5 | אין מקבילה ל-`sumit_request_budget.py` (atomic, fail-closed, AST-guarded) בשביל LLM — רק תיעוד-אחרי-מעשה best-effort. אותה סכנת-עלות עקרונית שהצדיקה את חוק ה-SUMIT הקשיח, טרם קרה אירוע. | בינוני-גבוה | גדול | קריאת קוד |
| D6 | `SUMIT_INTER_ORG_STAGGER_SECONDS=65` (`cron.py:110`) — sleep אמיתי בטסטים (לא מדומה), גורם לטסט להיראות "תקוע" 2+ דקות. תורם משמעותית ל-18:38 דק' הסוויטה. UX-פיתוח, לא בטיחות. | נמוך-בינוני | קטן (monkeypatch בטסטים) | מדידה חיה |
| D7 | 63 מופעי `datetime.utcnow()` (deprecated) → 42,774 אזהרות בריצה, מסתיר אזהרות אמיתיות. | נמוך | בינוני (sweep רוחבי) | grep |
| D8 | **`sites/moshko-builders/` — 1.4GB, `.git` נפרד (remote אחר לגמרי), לא ב-.gitignore.** סיכון: `git add -A` עלול לסחוף repo מקונן; מאט אינדוקס/grep. | **גבוה ל-handoff** | קטן (להעביר פיזית החוצה מהריפו) | `du -sh` + `git remote -v` |
| D9 | **`outputs/` — 34MB, 199 קבצים, לא ב-.gitignore, מכיל נתוני לקוח אמיתיים** (חשבוניות/VAT/readback אמיתיים של עמית פורת). סיכון דליפה להיסטוריית git. | **גבוה** | קטן מאוד (שורת gitignore) | `du -sh` + git status |
| D10 | `openai==1.6.1` מוצמד, ישן מאוד (סוף 2023). הזדמנות לתקן יחד עם D1. | נמוך | בינוני (בדיקת regression) | pyproject.toml |

### 1.2 — נבדק ונמצא נקי
- pytest: 2831 passed / 6 failed / 0 skip-הסתרה (2 skip לגיטימיים בלבד).
- `scripts/audit_routes.py`: 267 סה"כ, 176 תקין, 51 אזהרה(4xx), 40 מוגדר-סביבה, **0 כשל**.
- `scripts/schema_drift_check.py` (מול SQLite טרי): OK, 3 חריגות FK מוכרות/מכוונות.
- `frontend`: build עובר, lint עובר נקי (0 אזהרות).
- TODO/FIXME/HACK כמעט ואינם בקוד ייצור — החוב אמיתי הוא ארכיטקטוני (D1-D6), לא "עבודה לא-גמורה מפורשת".
- Alembic: head יחיד (`c81e6395fd71`), שרשרת לינארית נקייה, אין multiple-heads.
- אין conflict markers בשום קובץ.

### 1.3 — honest-null (לא ניתן לאימות בהיקף המשימה)
- Drift מול Neon פרוד בפועל — לא נבדק (אין/לא התבקשה גישה לסודות פרוד). מה שנבדק הוא drift מול SQLite-טרי-מהמודלים בלבד.
- האם 6 הכשלים היו קיימים לפני הסשן — אין snapshot "before" מדויק יותר.

---

## ראש 2 — מצב הענף `fix/rezef-stabilization-20260906` והמלצה

- `main` לא זז מאז ההסתעפות — 4 ה-commits הקיימים על הענף הם fast-forward נקי מול main, **אין סיכון קונפליקט בשכבה הזו**.
- מעל זה: **89 קבצים לא-committed** (73 שונו + 16 חדשים), +3266/-987 שורות. פילוח: 25 ב-`src/cfo/services`, 11 ב-`tests`, 9 ב-`docs`, 7 ב-`frontend/src/components`, 6 ב-`src/cfo/api/routes`, ועוד.
- אין conflict markers, אין עדות למיגרציה חצי-גמורה.
- 6 הכשלים (D0) מתאימים לדפוס אחד ברור: טסטים לא-מעודכנים אחרי החמרה מכוונת של שער-האישור + regression-guard אחד תעוור מריפקטור לגיטימי — **לא** "עבודה מסוכנת חצי-גמורה".
- `docs/audits/2026-09-07-agent-handoff.md`: "מעולם לא היה אישור סופי שהסוויטה ירוקה על השינויים האלה" — עקבי עם הממצא.
- **קריטי לדעת**: `docs/audits/2026-09-13-amit-porat-handoff.md` מתעד תיוק-הוצאות **חי** בפורטל SUMIT האמיתי של עמית פורת (1,031 קבצים בתור, מנה 1 כבר נוצרה בספרים האמיתיים). **זו לא בעיה בענף** — זה מצב עסקי נפרד, אסור לגעת (לא להריץ sumit-file-expenses, לא "לנקות" `outputs/porat-*`).

### המלצה — סדר יציוב (ללא reset/stash/checkout הרסני)
1. לתקן .gitignore (D8+D9) — `outputs/`, `sites/`; להעביר `sites/moshko-builders` פיזית החוצה מהריפו.
2. להכריע (עם הבעלים) ולתקן את 6 הכשלים (D0a/D0b/D0c) — כולל 2 החלטות-בעלים.
3. לפצל את 89 הקבצים לקומיטים נושאיים: (א) Open Finance connector/onboarding, (ב) report_builder_service+tests, (ג) expense filing/OCR+שער-אישור, (ד) CI workflow, (ה) docs/audits.
4. להריץ סוויטה מלאה **פעם אחת ברצף, לא concurrent** (לא יציבה תחת עומס מקביל — נצפה ישירות), ואז audit_routes + schema_drift (עצמאיים).
5. רק אז commit מסודר + PR לסקירה. אין deploy בלי אישור בעלים מפורש (GATE0_DEPLOYMENT_RUNBOOK.md).

---

## ראש 3 — סביבת עבודה למתכנת החדש, ≤$10/חודש

### המלצה 1 (חינם, מיידי) — Docker Compose מקומי, **כבר קיים בריפו**
`docker-compose.yml` + `docker/env.docker.example` כבר בנויים: Postgres 16 אמיתי מבודד, `AUTH_BYPASS_ENABLED=true`, כל הסודות דמה מפורשים, מפתחות ספק ריקים כברירת מחדל (honest-null UI, לא נפילה). `docs/DATABASE_MAP.md` מגדיר את גבולות שלוש הסביבות.

```bash
git clone <repo> && cd cfo
git checkout fix/rezef-stabilization-20260906   # אחרי יציוב לפי ראש 2
cp docker/env.docker.example docker/.env.docker
docker compose up --build
# frontend: http://localhost:8080 | api: http://localhost:8001/api/health
```
עלות: **$0/חודש**. זו הסביבה לעבודה שוטפת.

### המלצה 2 (קרוב-לפרוד, ל-cron/Functions/preview) — Vercel Hobby + Neon Free נפרדים
`vercel.json` הקיים ניתן לשימוש 1:1 בפרויקט Vercel חדש, ללא שינוי קובץ. הערכת גודל (proportional, honest-null — לא מדידה ישירה של הפרוד החי): 500MB חינמיים של Neon מספיקים בנוחות לסביבת פיתוח.

**שלבים:**
1. Neon: פרויקט חדש נפרד (לא branch) → free tier → להעתיק DATABASE_URL (pooler).
2. Vercel: פרויקט חדש נפרד (לא `cfo-2` הקיים) → Hobby.
3. `vercel env add DATABASE_URL` עם ה-Neon החדש. לא להעתיק מ-`.vercel/.env.production.local`.
4. סודות טריים ונפרדים: `JWT_SECRET_KEY`, `CREDENTIALS_ENCRYPTION_KEY`, `REGISTRATION_SECRET`, `CRON_SECRET`, `OPEN_FINANCE_WEBHOOK_SECRET` (`openssl rand -hex 32`).
5. מפתחות ספק (SUMIT/OpenAI/Anthropic/WhatsApp/Telegram) — **ריקים**, אלא אם יש מפתחות sandbox ייעודיים. לעולם לא מפתחות פרוד.
6. `alembic upgrade head` מול הNeon החדש (סכימה ריקה, ללא import נתוני-אמת).
7. honest-null: לא אומת אם Vercel Hobby מגביל מספר cron jobs (8 ב-vercel.json) — לבדוק בהקמה.

עלות: **$0/חודש**.

### חלופה חיצונית (בידוד מלא מ-Vercel)
Railway (~$5/חודש) או Fly.io (allowance חינמי + usage-based, ~$0-10). Render free-Postgres מתחדש/נמחק ל-30 יום — לא מתאים לקבוע בלי לשלם ($7/חודש). **ברירת המחדל המומלצת: Vercel Hobby + Neon Free** — אותו סטאק כמו פרוד, $0/חודש.

---

## ספרינט ראשון — משימות ממוספרות

**סדר: הבנה → סביבה בטוחה → יציוב הענף → תיקון חוב קריטי → מסירה.**

1. לקרוא בסדר: `CLAUDE.md` → `docs/DATABASE_MAP.md` → `docs/MASTER_EXECUTION_PLAN.md` → `docs/audits/2026-09-07-agent-handoff.md` **וגם** `docs/audits/2026-09-13-amit-porat-handoff.md` (מצב עסקי חי — לא לגעת). לא לכתוב קוד לפני זה.
2. להקים Docker מקומי (ראש 3, המלצה 1) — לוודא health-check + frontend עולים.
3. להבין את שתי שכבות ה-git (4 commits נקיים + 89 קבצים מעליהם) — **לא** `git reset`/`stash`/`checkout .`.
4. לתקן D8+D9 (.gitignore + הזזת sites/) — קומיט ראשון, נפרד וקטן.
5. להכריע עם הבעלים על D0a/D0b (שער-אישור ב-OCR auto_file), לתעד ההחלטה, לתקן 5 הטסטים (TDD).
6. לתקן D0c — לאמת ידנית שהמסלולים מתואמים, ואז לעדכן את הטסט לבדוק גם `get_connection_configuration`.
7. להריץ סוויטה מלאה פעם אחת לבד (לא concurrent, ~18-19 דק', D6 stagger ידוע ותקין).
8. להריץ audit_routes + schema_drift — לוודא 0 כשל/0 drift.
9. לפצל 89 הקבצים לקומיטים נושאיים (ראש 2).
10. לתקן D1 (`AsyncOpenAI` + חיווט cost-tracking) — TDD, קומיט נפרד.
11. למחוק D2 (`ai_insights.py`) אחרי grep נוסף גם על frontend.
12. PR לסקירה מול main. אין deploy בלי אישור בעלים מפורש.

D3/D4/D5/D7/D10 — עבודה אמיתית, לא חוסמת את הספרינט הראשון. מומלץ ספרינט שני ייעודי (D4+D5 יחד: שכבת abstraction אחת שגם עוטפת budget-gate).

---

## הערה עתידית — Vercel AI Gateway + Jev (עדיפות נמוכה)

`typesafe-ai/jev` דרך Vercel AI Gateway — עלות כמעט אפסית, `zdr:"all"`, `no_training:"all"`. עשוי להתאים לנקודות-החלטה זולות: הגשר לסיווג הוצאות (`israeli_tax_rules.py`), שער כפילויות OCR, תעדוף פערי-בנק, דירוג דחיפות בתזכורות גבייה. אם ייבחר בעתיד — לשלב יחד עם בניית D4 (abstraction) + D5 (budget-gate), לא כחיבור נפרד נוסף.

---

### קבצים קריטיים
- `CLAUDE.md`, `docs/MASTER_EXECUTION_PLAN.md`, `docs/DATABASE_MAP.md`
- `docs/audits/2026-09-07-agent-handoff.md`, `docs/audits/2026-09-13-amit-porat-handoff.md`
- `src/cfo/services/ai_analytics_service.py`, `ai_insights.py`, `moshko_reflector.py`
- `src/cfo/services/sumit_request_budget.py`, `moshko_observability.py`, `sync_engine.py`
- `src/cfo/api/routes/cron.py`
- `tests/conftest.py` (חומת-רשת נגד קריאות SUMIT אמיתיות), `tests/test_auth_and_tenancy.py`
- `docker-compose.yml`, `docker/env.docker.example`
- `vercel.json`, `.vercel/project.json`, `.gitignore`
