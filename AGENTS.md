# AGENTS.md — הוראות לסוכני קוד בריפו הזה

מסמך הכניסה לכל סוכן שאינו Claude Code (Codex, Cursor, Copilot). Claude Code טוען
`CLAUDE.md` — התוכן שם מחייב גם אותך. המסמך הזה מוסיף את מה שסוכן אוטומטי צריך: אילו
פקודות באמת קיימות, ומה אסור להריץ.

## מה זה הפרויקט

רצף (Rezef) — מערכת CFO/הנהלת-חשבונות לעסקים בישראל.
`src/cfo/` = FastAPI (152 מודולים, 40 routers, 102 services), `frontend/` = React+Vite+TS,
פרוד ב-cfo-2.vercel.app (Vercel + Neon Postgres).
אינטגרציות חיות: **SUMIT** (הנה"ח ישראלית) ו-**Open Finance** (בנקאות פתוחה).

## דוקטרינות מחייבות (מ-CLAUDE.md)

- **verify-first** — אימות מול `docs/SUMIT_KNOWLEDGE_BASE.md` לפני כל פעולה בפורטל/API.
- **אימות משולש** — כל פלט דיווח לרשויות: ≥3 בדיקות בלתי-תלויות (`filing_verification`).
- **honest-null** — אין מספרים מומצאים. עמימות = תור הכרעה, לא ניחוש.
- **אפס אוטונומיה בבלתי-הפיך** — סגירת מנה / שידור / תשלום: רק באישור בעלים.
- **משמעת עלויות API** — קריאות SUMIT/OF רק כשחייבים; שערי sync יומיים (20h) לא נעקפים.
- **TDD** — טסט אדום לפני מימוש. `python -m pytest tests/ -q` חייב להיות ירוק לפני commit.

עבודה חשבונאית/מיסויית — לטעון קודם `docs/bookkeeper_kb/README.md`.
בכל שאלת יכולת/ארכיטקטורה — `docs/REZEF_OPERATING_SYSTEM.md` הוא החוזה היציב,
`docs/rezef_capabilities.json` הוא מפת המימוש והראיות, ו-
`docs/MASTER_EXECUTION_PLAN.md` הוא לוח הסטטוס היחיד.

## ⛔ אסור להריץ — קריאות חיות / כתיבה לפרוד

הסקריפטים הבאים אומתו כמבצעי קריאות רשת חיות או כתיבה לפרוד. הם **מחוץ לתחום** לכל
סוכן אוטומטי, גם כשהמשימה נשמעת כמו "תריץ את כל הבדיקות". הרצה עולה כסף אמיתי
(היסטוריה בריפו: ‏₪62.23/יום חריגת API) ועלולה להיות בלתי-הפיכה:

| סקריפט | למה חסום |
| --- | --- |
| `scripts/production_readiness_check.py` | ping חי ל-SUMIT ול-Open Finance |
| `scripts/prod_smoke.py` | httpx חי מול cfo-2.vercel.app |
| `scripts/verify_sumit_writeback.py`, `pull_sumit_item_names.py` | קריאות SUMIT API |
| `scripts/run_ocr_pipeline.py`, `classify_expenses.py`, `sumit_daily_file_expenses.js` | מוריד מסמכים מ-SUMIT + מתייק (כתיבה) |
| `scripts/fix_prod_schema_drift.py`, `migrate_sqlite_to_postgres.py`, `apply_*_schema.py`, `backfill_vat_split.py`, `fix_bills_sign_status.py` | DDL/DML על פרוד |
| `scripts/bootstrap_superadmin.py`, `grant_superadmin_token.py`, `reset_password.py` | הרשאות/סודות |
| `qa_gate.py --env-file` / `schema_drift_check.py --env-file` | הדגל מפנה ל-Neon פרוד |

בלי `--env-file`, `qa_gate.py` ו-`schema_drift_check.py` עובדים על SQLite מקומי ומותרים.

גם: אין `git push`, אין `vercel deploy`, אין commit ל-`main` — הכל דרך PR.

## ✅ פקודות שאומתו כקיימות ובטוחות (offline)

כל בסיס כאן **נמדד** ב-2026-07-25 על ענף העבודה. סטייה מהמספר = שינוי אמיתי, לא רעש.

| פקודה | בסיס מדוד |
| --- | --- |
| `python -m pytest tests/ -q` | **1,401 עוברים**, 0 נכשלים, ~247 שנ', 19,948 אזהרות |
| `python scripts/audit_routes.py` | **250 routes**: 174 תקין · 39 אזהרה(4xx) · **36 מוגדר-סביבה(400)** · **1 כשל**. הכשל היחיד: `/api/financial/ai/predict/revenue` מחזיר 400 "דורש היסטוריית נתונים" — honest-null נכון. כל כשל נוסף = רגרסיה |
| `python scripts/schema_drift_check.py` | **נכשל** על ה-DB המקומי: 4 טבלאות חסרות (`filing_crosschecks`, `morning_briefs`, `of_snapshot_cache`, `vehicle_profiles`) + עמודות ב-`organizations`/`accounts`/`daily_snapshots`/`expenses`. ה-SQLite המקומי מיושן — **לא רגרסיה** |
| `python scripts/qa_gate.py` | נכשל בבסיס על שער אחד בלבד: `3a. Schema drift (local)` (DB מקומי מיושן). 7 השערים האחרים עוברים |
| `cd frontend && npm ci && npm run build` | עובר (tsc + vite) |
| `cd frontend && npm run lint` | ⚠️ **שבור** — אין קובץ קונפיג של eslint ב-`frontend/`. ה-script קיים ב-`package.json` אבל נופל מיד. ה-CI לא מריץ lint ולכן זה לא נתפס. אל תדווח על זה כרגרסיה — זה פער ידוע |
| `python scripts/render_bookkeeper_kb.py` | מייצר את `docs/bookkeeper_kb/03-classification-bridge.md` |

**אין בריפו `ruff` ואין `mypy`** — לא מותקנים ולא ב-`pyproject.toml`. אל תמציא פקודת lint
ל-Python ואל תתקין אחת בלי בקשה מפורשת. `pyproject.toml` דורש Python ~=3.12.

## מפת הריפו

```
src/cfo/api/routes/    40 routers של FastAPI
src/cfo/services/      102 services — לוגיקה עסקית, מנועי מע"מ/פער/דוחות
src/cfo/integrations/  לקוחות API חיצוניים (sumit_integration.py, 2,847 שורות)
src/cfo/models.py      כל מודלי SQLAlchemy (1,734 שורות)
tests/                 154 קבצי טסט
docs/                  ראו docs/README.md — אינדקס
docs/bookkeeper_kb/    מרכז הידע החשבונאי (חובה לפני עבודה מיסויית)
docs/archive/          תמונות מצב היסטוריות — לא מקור אמת
scripts/               כלי תפעול; ראו טבלת החסימות למעלה
```

## מלכודות מוכרות

- **אל תריץ שתי ריצות pytest במקביל.** הסוויטה עובדת מול ה-SQLite המקומי; שתי ריצות
  בו-זמנית מייצרות כשלים מדומים. נצפה בפועל: `qa_gate.py` דיווח `FAIL — Full test suite`
  בזמן שריצה נוספת פעלה ברקע, ועבר נקי בריצה בודדת.
- **שער התקציב היומי מסתיר תוצאות cron**: אם ל-org/source יש `SyncCheckpoint` עם
  `last_success_at` צעיר מ-20h, `/api/cron/sync` מחזיר `{"skipped": "daily_budget"}`
  בלי מפתחות התוצאה. טסט שבודק תוצאת sync חייב לנקות את הרשומה קודם
  (fixture `clear_sumit_sync_budget` ב-`tests/test_auth_and_tenancy.py`) — אחרת הוא
  נכשל מסיבה שאינה קשורה למה שהוא בודק. **תוקן 2026-07-25.**

- **סכימת פרוד**: `create_all` לא מוסיף עמודות. שינוי סכימה נעשה רק לפי
  `docs/GATE0_DEPLOYMENT_RUNBOOK.md`: אישור בעלים, `SUPER_ADMIN`, repair
  additive, בדיקת drift ורק אז `stamp head`. סקריפט תיקון חלקי אינו רשאי
  לסמן Alembic `head`.
- **`datetime.utcnow()`**: ~18.7K אזהרות deprecation בסוויטה. אין להחליף בסוויטה גורפת ל-
  `datetime.now(UTC)` — עמודות DB נאיביות, והשוואה tz-aware מול נאיבי זורקת `TypeError`.
  מודול אחד בכל פעם, עם טסטים ירוקים כשער.
- **`current_user.get(...)`**: באג חוזר — `current_user` הוא אובייקט, לא dict.
- **מסמך מיוצר**: `docs/bookkeeper_kb/03-classification-bridge.md` — לערוך רק את
  `src/cfo/services/israeli_tax_rules.py` ואז להריץ את הרנדרר.
