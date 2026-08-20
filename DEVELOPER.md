# DEVELOPER.md — מדריך המפתח של רצף (Rezef)

מסמך הכניסה למפתח/סוכן חדש. מה יש בכל תיקייה, איך מריצים, איפה מקורות האמת,
ואילו חוקים אסור להפר. **לפני כל עבודה — קרא גם את [`CLAUDE.md`](CLAUDE.md)
ואת [`AGENTS.md`](AGENTS.md); הם מחייבים וגוברים על כל ברירת מחדל.**

## מה המערכת

רצף = מערכת הפעלה פיננסית לעוסקים ישראליים: הנהלת חשבונות (מול SUMIT),
בנקאות פתוחה (Open Finance), מנועי דוחות (מע"מ/רו"ה/מאזן/תזרים), ועוזר AI
בשם **מושקו** שמפעיל את היכולות דרך צ'אט עם שערי אישור.

- Backend: FastAPI + SQLAlchemy + Alembic (Python 3.13) — `src/cfo/`
- Frontend: React + Vite + TypeScript — `frontend/`
- פרוד: Vercel (cfo-2.vercel.app) + Neon Postgres (מסד-לכל-דייר)
- מקומי: Postgres (docker-compose) או SQLite (`cfo.db`) לפיתוח מהיר

## מפת התיקיות

| נתיב | מה יש בו |
| --- | --- |
| `src/cfo/api/` | FastAPI app; `api/routes/` — ‏44 קובצי routes (כל דומיין קובץ) |
| `src/cfo/services/` | ‏137 שירותים — לב הלוגיקה. מרכזיים: `ai_chat_service.py` (לולאת מושקו), `ai_chat_tools.py` (קטלוג הכלים), `sumit_request_budget.py` + `sumit_quota.py` (שערי עלות), `israeli_tax_rules.py` (דיני מס — לערוך רק כאן), `kb_loader.py` (מרכזי ידע בזמן ריצה) |
| `src/cfo/integrations/` | `sumit_integration.py` — העטיפה היחידה ל-SUMIT API (אכיפת מגביל fail-closed בשכבת הרשת) |
| `src/cfo/models.py` | כל מודלי ה-DB (קובץ יחיד) |
| `src/cfo/config.py` | `Settings` (pydantic) — נטען מ-`.env` / `.env.local` |
| `src/cfo/auth.py` | JWT + תפקידים (`super_admin` וכו') |
| `alembic/` | מיגרציות סכימה — **הדרך היחידה** לשינוי סכימה בפרוד (ראה `docs/GATE0_DEPLOYMENT_RUNBOOK.md`) |
| `frontend/src/components/` | מסכי React; `MoshkoSystemChat.tsx` — הצ'אט הגלובלי; `/admin-moshko` — דשבורד observability |
| `tests/` | ‏237 קובצי pytest; חובה ירוק לפני commit |
| `scripts/` | כלי תפעול (audit_routes, fix_prod_schema_drift, grant_superadmin_token…) |
| `docs/` | כל התיעוד — האינדקס: [`docs/README.md`](docs/README.md) |
| `docs/sumit_help_kb/`, `docs/bookkeeper_kb/` | מרכזי ידע שחולצו (SUMIT + דיני הנה"ח) — נגישים למושקו דרך `kb_lookup` |
| `reports/` | פלטי דוחות — **מכילים נתוני לקוח; לא לפרסם** |

## הרצה מקומית

```bash
# Backend (מקומי, SQLite/Postgres לפי .env.local)
python -m uvicorn cfo.api:app --reload --app-dir src

# Frontend
cd frontend && npm run dev

# Docker (Postgres מלא)
make docker-up          # build + up
make docker-migrate     # alembic upgrade head
make docker-test        # pytest בתוך הקונטיינר
```

קונפיגורציה: העתק `.env.example` → `.env.local`. **אין לגעת ב-`.env.prod`**
(סודות פרוד; גישה באישור בעלים בלבד).

## בדיקות ושערי איכות

```bash
python -m pytest tests/ -q        # חובה ירוק לפני commit (TDD)
python scripts/audit_routes.py    # ביקורת routes
cd frontend && npm run build && npm run lint
```

או דרך סוכן ה-QA: `qa-runner` (מריץ הכול offline — לא נוגע ב-SUMIT/פרוד).

## החוקים שאסור להפר (תקציר — המלא ב-CLAUDE.md)

1. **משמעת עלויות SUMIT**: כל `SumitIntegration` חייב `SumitRequestLimiter`
   אמיתי. אכיפה כפולה: שכבת הרשת (fail-closed) + מכסה מהספק. שער אנטי-רגרסיה:
   `tests/test_sumit_rate_limit_hard_rule.py` — אין לרכך בלי אישור בעלים.
2. **אפס אוטונומיה בבלתי-הפיך**: סגירת מנה / שידור / תשלום — רק באישור בעלים
   (`docs/IRREVERSIBLE_ACTION_CONTROL.md`).
3. **אימות משולש**: כל פלט דיווח לרשויות ≥3 בדיקות בלתי-תלויות.
4. **honest-null**: אין מספרים מומצאים; עמימות = תור הכרעה.
5. **verify-first**: פעולה בפורטל/API של SUMIT — רק אחרי בדיקה מול
   `docs/SUMIT_KNOWLEDGE_BASE.md`.
6. **סכימת פרוד**: רק דרך Alembic + `docs/GATE0_DEPLOYMENT_RUNBOOK.md`
   (`create_all` לא מוסיף עמודות!).

## מושקו — איפה כל דבר

| רכיב | קובץ |
| --- | --- |
| לולאת הצ'אט (LLM + כלים + שערי אישור) | `src/cfo/services/ai_chat_service.py` |
| קטלוג הכלים (64 כלים, read/write, office) | `src/cfo/services/ai_chat_tools.py` |
| רישום ביצועים (audit) | טבלת `moshko_tool_calls` + `moshko_observability.py` |
| פידבק משתמש | טבלת `moshko_feedback` |
| זיכרון מושקו | `src/cfo/services/moshko_memory.py` |
| דשבורד תפעול | `frontend/.../MoshkoObservabilityDashboard.tsx` (‏`/admin-moshko`) |
| ידע בזמן ריצה | `kb_loader.py` + `kb_lookup` |
| ערוצים | Telegram (`telegram_webhook.py`), Web (`MoshkoSystemChat.tsx`) |

## תיעוד — לאן ללכת

- **אינדקס מלא**: [`docs/README.md`](docs/README.md)
- **לוח הסטטוס היחיד**: `docs/MASTER_EXECUTION_PLAN.md`
- **תוכנית מושקו הפעילה**: `docs/REZEF_MOSHKO_OPERATING_PLAN.md`
- **מפת יכולות SUMIT ותוכנית הבנייה**: `docs/SUMIT_CAPABILITY_MAP_AND_REBUILD_PLAN.md`
- **חוזה היכולות המכונתי**: `docs/rezef_capabilities.json`
- תוכניות סשן והעברות מקל: `docs/superpowers/plans/` (כרונולוגי)
