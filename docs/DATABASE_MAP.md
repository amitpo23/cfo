# Rezef Database Map

This document defines the database boundaries so local development, Docker, and
production do not get mixed up.

## Source Of Truth

Production data lives in the Vercel `DATABASE_URL`, currently a managed
Postgres database:

```text
postgresql+psycopg://neondb_owner:***@ep-round-cloud-aihrzsjw-pooler.c-4.us-east-1.aws.neon.tech/neondb
```

This is the database that currently contains the live Rezef client roster and
financial data.

Current production snapshot, verified on 2026-06-30:

> ⚠️ **מיושן, לא מעודכן.** הטבלה הזו נכתבה פעם אחת ב-2026-06-30 ומעולם לא רועננה. היא
> כבר סותרת מסמכים מאוחרים יותר — למשל `MASTER_EXECUTION_PLAN.md` (2026-07-24) מתעד
> ש-org1 מחובר ל-Open Finance עם 6 חשבונות בנק חיים, כך ש-`bank_transactions=0` אינו
> נכון עוד. סוכן אוטומטי **אסור לו** לרענן את הטבלה הזו ישירות — היא production על
> Neon. רענון אמיתי דורש את הבעלים דרך הנוהל ב"Safe Audit Commands" למטה
> (`production_readiness_check.py --env-file`, קריאה-בלבד, ואז מחיקת קובץ ה-env).

| Table | Count |
| --- | ---: |
| organizations | 5 |
| users | 1 |
| integration_connections | 5 |
| invoices | 48 |
| bills | 1174 |
| expenses | 834 |
| transactions | 154 |
| bank_transactions | 0 |
| sync_runs | 48 |

Active organizations (כפי שתועדו ב-2026-06-30 — **ראה תיקון והערת אימות-בעלים מתחת**):

| Org ID | Name | Integration |
| ---: | --- | --- |
| 1 | עמית פורת | SUMIT |
| 2 | שף אליהב כהן | SUMIT |
| 3 | מדיצ׳י שיווק בתי מלון בע״מ | SUMIT |
| 4 | ~~עומר ועודד פורת~~ — **נמחק 2026-07-06** | — |
| 5 | ~~may way~~ → **עומר ועודד פורת** | SUMIT |

> **תיקון (2026-08-05):** הטבלה שלמעלה שגויה החל מ-2026-07-06. `.superpowers/sdd/progress.md`
> ו-commit `64596d2` מתעדים ש-org4 היה כפילות ריקה של "עומר ועודד פורת" (0 חשבוניות/הוצאות/
> אנשי-קשר, נוצר עם פרטי-התחברות שגויים) ו**נמחק** יחד עם 196 שורות sync-cruft. מאותו רגע
> ואילך, בעקביות מלאה בעשרות commits/מסמכים (`MASTER_EXECUTION_PLAN.md`,
> `docs/superpowers/plans/2026-07-28-omer-oded-hashavshevet-intake.md`,
> `docs/audits/2026-07-17-eliav-batch4-analysis.md`, `src/cfo/services/kb_loader.py`,
> `tests/test_sumit_connector_bills_types.py`): **org5 = עומר ועודד פורת** (ח.פ 558402376,
> SUMIT CompanyID 1999386278). `MASTER_EXECUTION_PLAN.md` (2026-07-24, לוח הסטטוס היחיד של
> הפרויקט) כבר קורא לזה "org5 עומר ועודד" — הוא היה נכון; מסמך זה היה המיושן.
>
> **דורש אימות בעלים**: השם "may way" עבור org5 בטבלת ה-2026-06-30 המקורית אינו מופיע באף
> מקור אחר בריפו (לא בקוד, לא ב-`progress.md`, לא במסמך נוסף). לא ניתן לקבוע בוודאות אם זו
> הייתה טעות-תיעוד מלכתחילה (השם "עומר ועודד פורת" תמיד היה הנכון ל-org5) או שהיה ארגון אמיתי
> בשם "may way" שנמחק/שונה בנפרד. אין לנחש — הבעלים צריך לאשר.

Each organization has an active encrypted `integration_connections` row for
`sumit`.

## Local SQLite

When the app runs locally without Docker and no `DATABASE_URL` override is set,
it uses:

```text
sqlite:///./cfo.db
```

This file exists in the repository working directory and contains development
data only. It is not the production source of truth. `cfo.db` is git-ignored,
so each worktree/environment has its own independent copy — counts below vary
per developer machine and are never representative of production.

Verified local snapshot (2026-08-05, fresh worktree, `uv sync --frozen` +
`alembic upgrade head` from a clean checkout, no seed data loaded):

| Table | Count |
| --- | ---: |
| organizations | 0 |
| users | 0 |
| integration_connections | 0 |
| invoices | 0 |
| bills | 0 |
| expenses | 0 |
| transactions | 0 |
| bank_transactions | 0 |
| sync_runs | 0 |

> This is a snapshot of *this session's* freshly-created worktree DB, not a
> claim about any other developer's populated local `cfo.db`. The earlier
> 2026-06-30 snapshot (organizations=3 etc.) reflected a different, previously
> populated local database and is left above only as history — do not treat
> either row as current without re-running the query below yourself.

Use this DB for local experiments only.

## Docker Local Postgres

Docker Compose runs a separate local Postgres database:

```text
Host URL: postgresql+psycopg://cfo:cfo_local_password@127.0.0.1:5433/cfo
Container URL: postgresql+psycopg://cfo:cfo_local_password@db:5432/cfo
Volume: rezef_postgres_data
```

Verified Docker snapshot:

| Table | Count |
| --- | ---: |
| organizations | 2 |
| invoices | 0 |
| bills | 0 |

Use this DB for containerized local testing only.

## Rules

- Production must use persistent Postgres through `DATABASE_URL`.
- Vercel must not run on SQLite; the app validates this on startup.
- SQLite is acceptable for local development and tests, not for live customer
  data.
- Docker Postgres is isolated from production and from local SQLite.
- New customers are represented as `organizations` rows and scoped by
  `organization_id`, not by separate physical databases.
- Integration credentials live per organization in encrypted
  `integration_connections` rows.

## Safe Audit Commands

Pull production env, run a read-only readiness check, then delete the env file:

```bash
vercel env pull /tmp/rezef-prod.env --environment=production
PYTHONPATH=. uv run python scripts/production_readiness_check.py \
  --env-file /tmp/rezef-prod.env \
  --require-postgres
rm -f /tmp/rezef-prod.env
```

Check local SQLite:

```bash
PYTHONPATH=src uv run python - <<'PY'
from sqlalchemy import create_engine, inspect, text
engine = create_engine("sqlite:///./cfo.db")
with engine.connect() as conn:
    tables = inspect(conn).get_table_names()
    for table in ["organizations", "invoices", "bills", "sync_runs"]:
        print(table, conn.execute(text(f"select count(*) from {table}")).scalar_one() if table in tables else "MISSING")
PY
```

Check Docker Postgres:

```bash
PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH" \
docker exec rezef-local-db-1 psql -U cfo -d cfo \
  -c "select count(*) from organizations;" \
  -c "select count(*) from invoices;" \
  -c "select count(*) from bills;"
```

