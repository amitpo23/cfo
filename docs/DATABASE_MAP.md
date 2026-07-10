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

Active organizations:

| Org ID | Name | Integration |
| ---: | --- | --- |
| 1 | עמית פורת | SUMIT |
| 2 | שף אליהב כהן | SUMIT |
| 3 | מדיצ׳י שיווק בתי מלון בע״מ | SUMIT |
| 4 | עומר ועודד פורת | SUMIT |
| 5 | may way | SUMIT |

Each organization has an active encrypted `integration_connections` row for
`sumit`.

## Local SQLite

When the app runs locally without Docker and no `DATABASE_URL` override is set,
it uses:

```text
sqlite:///./cfo.db
```

This file exists in the repository working directory and contains development
data only. It is not the production source of truth.

Verified local snapshot:

| Table | Count |
| --- | ---: |
| organizations | 3 |
| users | 2 |
| integration_connections | 1 |
| invoices | 40 |
| bills | 320 |
| expenses | 834 |
| transactions | 101 |
| bank_transactions | 0 |
| sync_runs | 9 |

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

