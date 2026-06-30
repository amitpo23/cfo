# Rezef / רצף

Rezef is a multi-tenant finance operating system for Israeli companies and
accounting offices. It combines a CFO dashboard, double-entry accounting
workflows, document issuance, daily P&L, cash-flow control, collections,
expense filing, reconciliation workflows, anomaly detection, and client-office
automation.

The production app is deployed on Vercel at:

```text
https://cfo-2.vercel.app
```

## Current Architecture

- Backend: FastAPI, SQLAlchemy, Alembic, PostgreSQL.
- Frontend: React, TypeScript, Vite, Recharts.
- Auth: JWT with organization scoping and a `SUPER_ADMIN` override header.
- Tenancy: one persistent production database; every client is an
  `Organization` with its own encrypted integration credentials.
- Automation: Vercel Cron hits protected cron endpoints to sync connected
  organizations and run post-sync tasks.
- Local runtime: Docker Compose with Postgres, API, and frontend services.

## Production Status

The current production deployment has:

- Persistent PostgreSQL `DATABASE_URL` configured and reachable.
- Security secrets configured.
- SUMIT credentials configured and pinging successfully.
- Five active organizations in production.
- Core tables present, including organizations, users, integration connections,
  invoices, bills, expenses, transactions, bank connections, bank transactions,
  sync runs, and Alembic metadata.

Known gated items:

- Open Finance is intentionally blocked until `OPEN_FINANCE_USER_ID` is added.
  Client ID, client secret, and webhook secret are already present.
- Google Sign-In is hidden until `GOOGLE_CLIENT_ID` and
  `VITE_GOOGLE_CLIENT_ID` are configured.
- PCN874 export/reporting still requires final validation against the official
  VAT file format before it should be treated as production-ready.

## Main Capabilities

- Super-admin client roster and cross-company overview.
- Per-organization SUMIT sync into Rezef's local database.
- Daily P&L, revenue, expenses, cash-flow, AR/AP, VAT position, dashboards, and
  CFO insights.
- Document issuance flow backed by Rezef DB, with optional SUMIT issuance:
  invoice, receipt, invoice-receipt, proforma, quote, order, purchase order,
  work order, delivery note, credit note, and payment request.
- Expense intake, OCR/review workflows, expense filing, and supplier controls.
- Manual and dispatch-tracked bank reconciliation workflows.
- Office/client onboarding, roster repair, and post-sync automation.
- Budgeting, reports, collections, reminders, payroll, inventory, MASAV, and
  Israeli tax/reporting modules in varying maturity levels.

## Environment Variables

Required for production:

```env
DATABASE_URL=postgresql+psycopg://...
JWT_SECRET_KEY=...
CREDENTIALS_ENCRYPTION_KEY=...
REGISTRATION_SECRET=...
CRON_SECRET=...
CORS_ALLOWED_ORIGINS=https://cfo-2.vercel.app
APP_URL=https://cfo-2.vercel.app
OPEN_FINANCE_WEBHOOK_SECRET=...
SUMIT_API_KEY=...
SUMIT_COMPANY_ID=...
```

Required when enabling Open Finance:

```env
OPEN_FINANCE_CLIENT_ID=...
OPEN_FINANCE_CLIENT_SECRET=...
OPEN_FINANCE_USER_ID=...
```

Required when enabling Google Sign-In:

```env
GOOGLE_CLIENT_ID=...
VITE_GOOGLE_CLIENT_ID=...
```

Optional:

```env
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
STRIPE_SECRET_KEY=...
STRIPE_PRICE_COMPANY_UP_TO_2_5M=...
STRIPE_PRICE_COMPANY_ABOVE_2_5M=...
STRIPE_PRICE_OFFICE=...
```

## Local Development

Install Python and Node dependencies:

```bash
uv sync
cd frontend
npm install
```

Run backend tests:

```bash
uv run pytest -q
```

Run frontend build:

```bash
cd frontend
npm run build
```

Run locally without Docker:

```bash
uv run uvicorn src.cfo.api:app --reload --host 0.0.0.0 --port 8000
cd frontend
npm run dev
```

## Docker Local Runtime

Docker Compose starts a local Postgres DB, API, and frontend:

```bash
docker compose build
docker compose up -d
```

If Docker Desktop is installed but `docker` is missing from `PATH` on macOS:

```bash
PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH" docker compose build
PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH" docker compose up -d
```

Local URLs:

```text
Frontend: http://127.0.0.1:8080
API:      http://127.0.0.1:8001
Health:   http://127.0.0.1:8001/api/health
```

Docker images:

```text
rezef-local-api:latest
rezef-local-frontend:latest
```

## Production Readiness Check

The read-only readiness script validates env, DB connectivity, core tables, and
optional integration pings:

```bash
vercel env pull /tmp/rezef-prod.env --environment=production
PYTHONPATH=. uv run python scripts/production_readiness_check.py \
  --env-file /tmp/rezef-prod.env \
  --require-postgres
rm -f /tmp/rezef-prod.env
```

Expected current result:

- DB and SUMIT pass.
- Open Finance fails only because `OPEN_FINANCE_USER_ID` is not configured yet.
- Google client IDs are optional until Google Sign-In is enabled.

## Deployment

Deploy production through Vercel CLI:

```bash
vercel --prod --yes
```

Verify:

```bash
curl -fsS https://cfo-2.vercel.app/api/health
vercel inspect https://cfo-2.vercel.app
```

## Important Boundaries

- Do not create real accounting documents in production tests unless explicitly
  approved. Use `send_to_sumit=false` for safe draft-only checks.
- Do not print secrets, API keys, JWTs, or pulled Vercel env files.
- Open Finance routes should return a clean configuration error until the final
  user ID is configured.
- The app stores separate tenant data by organization in the same production
  database; it does not create a separate physical database per customer.

