# Open Finance — Full Integration Design (2026-06-16)

## Goal
Integrate the **entire** Open Finance / Financy API into the CFO system, with full
functions for every capability, plus a **Bank Intelligence** layer that turns raw
bank-statement data into actionable insights (anomalies, duplicate charges, unused
subscriptions, fee waste, recurring/standing orders, savings opportunities,
month-over-month trends, end-of-month forecast) and **bank reconciliation** against
SUMIT invoices/bills.

## Scope (approved: A + B + C, full)
- **A — Data & insights:** connections/consent journey, accounts, transactions
  (+ rich fields + categorization + update), reports (monthly/financial/securities/
  aggregations), webhooks, and the insights engine.
- **B — Payments:** create/cancel/refund/status, periodic & bulk, ATM codes, mandates.
- **C — Credit & CRM:** credit-sessions + leads, decision/scoring, customers CRM,
  merchants, providers, communication (WhatsApp).

## Architecture

### 1. `OpenFinanceClient` (`services/open_finance_client.py`)
Low-level async client covering **every** endpoint. Responsibilities:
- OAuth token lifecycle keyed on `expiresIn` (ms), refresh on expiry and on 401.
- Per-group base URLs: `OAUTH_URL`, `V2` (`/v2`), `V3_LOANS` (`/v3/loans`).
- Generic `_request(method, base, path, *, params, json, expect_status)`.
- One typed method per endpoint, grouped by region (connections, accounts,
  transactions, reports, decisions, payments, atm, mandates, merchants, providers,
  credit_sessions, customers, communication).
`userId` defaults to the configured `OPEN_FINANCE_USER_ID` but is overridable.

### 2. Connector adapter (`services/open_finance_connector.py`)
Keeps the `AccountingConnector` contract for the sync engine; delegates HTTP to the
client. Transaction normalization is enriched to keep `category.main/sub`,
`merchantName`, `installments`, `isDuplicate`, `markupFee`, `balancePerEndDay` (the
full raw record is already persisted in `BankTransaction.raw_data`). Adds a
`sync_connections()` path.

### 3. Models (`models.py` + alembic)
- `BankConnection` — org-scoped consent state: connection_id, provider_id, bank_name,
  status, expiry_date, connect_url, counts, last_refresh, raw.
- `BankInsight` — generated insight: org, type, severity, title, description, amount,
  currency, period, related_external_ids (JSON), status (new/ack/dismissed), evidence
  (JSON), created/updated.

### 4. Insights engine (`services/bank_insights.py`)
Pure analyzer functions over normalized transaction dicts + accounts + monthly report,
returning `BankInsight` rows. Analyzers:
- `duplicate_charges` — same account+amount+(merchant|desc) on same day (and API `isDuplicate`).
- `subscriptions` — recurring same-merchant monthly debits; flag likely-unused (no other engagement signal) — surfaced for user review.
- `recurring_payments` — standing orders / fixed monthly debits, next expected date, installments ending soon.
- `fee_waste` — bank/card fees (FINANCE category, `markupFee` FX fees) summed; cut candidates.
- `category_trends` — per-category month-over-month deltas; flag spikes (e.g. dining +40%).
- `cashflow_forecast` — income vs expense run-rate → projected end-of-month +/-.
- `savings_opportunities` — categories with high variance / large discretionary spend.
- `anomalies` — unusually large/odd transactions vs personal baseline; charges after cancellation.
- `risk_signals` — surface monthly-report risk fields (nsf, canceledChecks, foreclosure, fallingBehind).

### 5. Reconciliation (`services/bank_reconciliation.py`)
Match `BankTransaction` rows to SUMIT invoices (inflow) and bills/expenses (outflow)
by amount + date window + name similarity; set `matched_entity_type/id`; report
unmatched both directions.

### 6. API routes (`api/routes/open_finance.py`)
Org-scoped endpoints exposing all client capabilities + insights + reconciliation +
a webhook receiver (`POST /api/open-finance/webhooks`). The consent journey:
`POST /api/open-finance/connections` returns `connectUrl` for the user to complete.

### 7. Frontend
- `OpenFinanceInsights.tsx` — insights dashboard grouped by type/severity with amounts.
- Connect-bank button (launches `connectUrl`), connections list, bank-statement table.
- Nav entry.

## Sequencing
1. Reference + spec (this doc). 2. Client. 3. Connector + sync. 4. Models + migration.
5. Insights engine. 6. Reconciliation. 7. Routes. 8. Frontend. 9. Tests.

## Validation gate
`OPEN_FINANCE_USER_ID` is ours to set (done in code/config). Real data requires the
user to complete one consent journey; until then, insights/reconciliation are validated
against fixture data in unit tests.

## Testing
- Client: httpx transport mock — auth, base-URL routing, pagination, 401-refresh.
- Insights: fixture transactions → expected insights per analyzer.
- Reconciliation: fixture txns + invoices → expected matches/unmatched.
- Smoke: import app, route audit.
