# CFO Platform Workflow Audit

## Target Product

One multi-tenant CFO/finance operations platform for Israeli businesses and
accounting offices:

- SUMIT-backed document issuance and official accounting data ingestion
- Open Finance-backed bank/card ingestion and reconciliation
- CFO hub dispatch from local bank matches to SUMIT status tracking
- AR, AP, procurement, payments, MASAV, payroll, VAT, tax drafts, and CFO dashboards
- Bank-facing report packages with P&L, balance sheet, cash position, AR/AP aging,
  debt schedules, and data freshness
- Strong tenant separation by `organization_id`, with encrypted integration
  credentials per organization

## Current Architecture

- Backend: FastAPI
- Frontend: Vite/React
- Local data source: `cfo.db` SQLite with real synced data
- Production target: Vercel + Supabase/Postgres
- Tenant model: one database, many `organizations`
- Source-of-truth integrations:
  - SUMIT for issued/received accounting documents
  - Open Finance for bank/card transactions

## Existing Workflow Coverage

| Area | Status |
|---|---|
| Auth and tenancy | Implemented with email/password and Google ID-token endpoint. Tenant scope comes from JWT user organization. |
| SUMIT sync | Implemented and locally verified. Local SUMIT read calls work. |
| Open Finance | Client/routes implemented, but live verification needs `OPEN_FINANCE_USER_ID`. |
| Expenses | DB-backed, SUMIT import/filing flow exists, PCN readiness exists. |
| Invoices | SUMIT-backed sync exists; legacy `/api/financial/*` invoice creation still needs unification with normalized DB plane. |
| AR/AP | DB-backed views exist over normalized invoices/bills/payments. |
| Bank reconciliation | Matching engine exists and tests pass; depends on bank transactions from Open Finance. Local matches now carry SUMIT dispatch status: `not_sent`, `confirmed`, `failed`, or `unsupported`. |
| Double-entry ledger | Derived shadow ledger exists and balances in tests; not yet official immutable books. |
| P&L / balance sheet | Multiple implementations exist; legacy reports use `Transaction`, derived reports use synced docs/ledger. Needs one canonical source. |
| Cash flow | Cashflow views and manual projections exist; some AR/AP-to-SUMIT TODOs remain. |
| Bank report | Exists, but needs stronger data freshness, reconciliation status, and supporting schedules. |
| Payroll | Deterministic payroll/Form 102/126 exists, but not filing-grade employee annual detail. |
| VAT/tax | VAT and annual draft flows exist, but PCN874/Form 6111 are not filing-grade. |
| MASAV | File generator exists; needs durable batch workflow and bank validation. |

## Benchmark Lessons

Mature accounting/ERP systems converge on the same core primitives:

- Official immutable general ledger, not only derived views
- Rich chart of accounts with report/tax mappings
- AR/AP subledgers tied to contacts, documents, payments, and collections
- Purchase order / receipt / supplier invoice lifecycle
- Bank import and reconciliation as a first-class workflow
- Audit log for every sensitive mutation and export
- Period close / lock / reversal mechanics
- Multi-company support and roles
- Exportable report packages

For Israel, add:

- SUMIT / invoice allocation number tracking
- 2026 allocation thresholds and VAT input eligibility checks
- PCN874/detailed VAT reporting
- MASAV payment batches and bank response import
- Form 6111 / annual report mapping
- Payroll Form 102/126/106 detail

## Critical Product Gaps

1. **Canonical accounting plane**
   - Today there are normalized synced DB models and separate `/api/financial/*`
     operational services, some of which are in-memory/default-org oriented.
   - Required: all invoice, expense, AP, AR, payment, and cash-flow mutations must
     land in the normalized DB models and feed dashboards/reports/ledger.

2. **Official ledger**
   - Current ledger is explicitly derived/shadow.
   - Required: persistent journal entries and lines, immutable postings, reversals,
     period locks, opening balances, accountant approval, and trial-balance-backed
     reports.

3. **Israeli chart of accounts and mappings**
   - Current chart is minimal.
   - Required: seeded Israeli COA with account type, VAT treatment, 6111 mapping,
     report mapping, category mapping, and organization overrides.

4. **VAT/PCN874**
   - Current flow is readiness/estimation-oriented.
   - Required: line-level VAT treatments, allocation-number checks, partial input
     VAT, exempt/zero-rated handling, credit notes, detailed report export.

5. **Production data**
   - Local SQLite has real data.
   - Required: migrate `cfo.db` to Supabase/Postgres and make Postgres source of
     truth.

6. **Approval and audit**
   - Some recommendations exist, but durable approval state is limited.
   - Required: approval actions for expenses, bills, payment batches, journal
     postings, and report exports, all with audit history.

7. **Bank package**
   - Current bank report exists but needs banker/accountant-grade metadata.
   - Required: data freshness, reconciliation status, source counts, AR/AP aging,
     debt schedules, covenant ratios, export hash, and disclaimer.

## Production Workflow

1. Back up `cfo.db`.
2. Obtain real Supabase Postgres `DATABASE_URL` with password.
3. Run Alembic against empty Supabase.
4. Dry-run SQLite-to-Postgres migration.
5. Execute migration.
6. Run readiness check against Supabase.
7. Set Vercel production env.
8. Deploy preview.
9. Validate SUMIT/Open Finance/auth/reports.
10. Promote production.
11. Configure the real SUMIT bank-reconciliation write-back adapter once the
    exact SUMIT endpoint/action is confirmed. Until then, dispatch is explicit
    and marked `unsupported` rather than silently claiming official posting.

## Added Operational Tools

- `scripts/production_readiness_check.py`
  - Read-only environment, database, table, count, SUMIT, and Open Finance checks.
- `scripts/migrate_sqlite_to_postgres.py`
  - Dry-run-by-default SQLite to Postgres importer.

## Next Implementation Waves

### Wave 1: Production Cutover
- Set `DATABASE_URL`
- Run Alembic
- Migrate SQLite
- Deploy current branch
- Verify workflows

### Wave 2: Canonical Accounting Plane
- Make `/api/financial/*` authenticated and tenant scoped
- Replace in-memory invoice/payment islands with normalized DB writes
- Add tests proving created documents feed AR/AP/ledger/reports
- Wire the SUMIT reconciliation dispatch adapter when the official endpoint is
  available; keep failed/unsupported rows visible in the CFO hub.

### Wave 3: Official Ledger
- Add persistent journal line model
- Seed Israeli COA
- Add posting engine from invoices, bills, expenses, payments, payroll
- Add period locks and reversals

### Wave 4: Israeli Compliance
- PCN874 export/validation
- Form 6111 draft mapping
- Allocation-number audit
- Payroll 106/126 enrichment

### Wave 5: CFO/Bank Package
- Report package builder with source freshness and reconciliation status
- Export audit/hash
- Bank dashboard and PDF/XLSX package
