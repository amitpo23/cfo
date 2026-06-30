# Rezef 0.2.0 Release Notes

Date: 2026-06-30

## Scope

This release strengthens Rezef without replacing the existing SUMIT/Open Finance,
sync, ledger, reporting, or tenant infrastructure.

## Added

- Super Admin Command Center enrichment:
  - client data freshness
  - sync state
  - open work queues
  - unreconciled bank transaction counts
  - overdue receivables
  - payables due in 14 days
  - onboarding pending/failed counts
  - action score per client
- Read-only Accounting Event Plane:
  - `/api/accounting-events`
  - derived event stream for invoices, bills, payments, expenses, and bank transactions
  - evidence metadata on each event
  - org-scoped and authenticated
- Local Docker QA fix:
  - when `VITE_AUTH_BYPASS=true`, the frontend sends default `X-Active-Org-Id: 1`
  - this keeps local super-admin QA scoped without changing production auth behavior

## Guardrails

- No database schema migration.
- No existing routes removed.
- No new write-back to SUMIT or Open Finance.
- Accounting events are derived read-only projections, not a new accounting source of truth.
- Production auth remains gated because `VITE_AUTH_BYPASS` is false outside local Docker/dev builds.

## QA Evidence

- Backend full suite: `uv run pytest -q`
  - Result: 443 passed
- Frontend production build: `cd frontend && npm run build`
  - Result: passed
- Docker rebuild: `docker compose up -d --build`
  - Result: API, frontend, and Postgres healthy
- Browser smoke QA via Playwright against Docker frontend:
  - `/`
  - `/admin-clients`
  - `/business-menu`
  - `/ledger`
  - `/daily-reports`
  - `/of-ops`
  - Result: all HTTP 200, main UI rendered, no console errors

## Known Gates

- Open Finance live data remains gated by final production user/consent configuration.
- PCN874 must still be validated against the official filing format before being treated as filing-grade.
- Google Sign-In remains gated until Google client IDs are configured.
