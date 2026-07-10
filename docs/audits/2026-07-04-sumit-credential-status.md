# SUMIT credential status per organization (2026-07-04)

Triggered while verifying the fetch_customers()/365-day-cap fix (see
`docs/audits/2026-07-04-data-parity-sumit.md`) actually propagated to every
org, not just org 1. Direct live testing against `cfo-2.vercel.app` found a
separate, pre-existing problem: **3 of 5 organizations have invalid SUMIT
credentials.**

## Findings

| Org | Name | SUMIT credential status | Notes |
|---|---|---|---|
| 1 | עמית פורת | **Working** | Verified in the data-parity audit; real customer names, real totals. |
| 2 | שף אליהב כהן | **Broken** — "Invalid Credentials (CompanyID/APIKey are incorrect)" on every fetch | Has 21 real historical invoices (₪1,498,072) already in the local DB, all showing customer "Unknown" — this data was synced before credentials broke (or before this session's `fetch_customers()` fix existed), and can no longer be corrected by a re-sync until the credentials themselves are fixed. Org created 2026-06-21. |
| 3 | מדיצ׳י שיווק בתי מלון בע״מ | **Broken** — same error | 0 invoices in the local DB. Org created 2026-06-30 — consistent with never having had valid credentials since onboarding, rather than a credential that broke later. |
| 4 | עומר ועודד פורת | **Broken** — same error | 0 invoices in the local DB. Same 2026-06-30 creation date as org 3 — same likely cause. |
| 5 | may way | **Working** | Confirmed via `/api/office/clients` — real recent successful sync (accounts updated, completed status). |

`GET /api/integration/status` reported `connections.sumit == "active"` for
**all five** orgs regardless of this, because connection status is set once
at configure-time and never updated from actual sync health — see the code
fix below.

## Code bug fixed this session (not the credential problem itself)

Two bugs made the above invisible to anyone, including the org owners:

1. Every `fetch_*` method in `sumit_connector.py` caught its own exception,
   logged it server-side only, and returned an empty-but-"successful"
   `FetchResult`. `run_full_sync()` reported `status=completed`,
   `error_summary=None` even when 100% of real SUMIT calls failed.
2. `IntegrationConnection.status` is set once at configure-time and never
   re-derived from actual sync health.

Fixed (commit `510f1e3`): `FetchResult` now carries an `error` field that
real fetch failures populate; `SyncEngine._sync_entity_type` raises when
it's set, routing into the existing error-aggregation machinery
(`errors`/`error_summary`/`error_details`/`SyncStatus.PARTIAL`) that already
existed but was never reached. `GET /api/integration/status` gained a
`last_sync_errors` field sourced from the latest `SyncRun` per org+source,
without changing `connections.sumit` or `configured.sumit` (4 existing
dashboards render `connections.sumit` truthily — checkmark vs. warning —
so overwriting it to `"error"` would misreport a broken-but-configured
connection as disconnected).

**Live-verified after deploy**: re-triggering `POST /api/sync/run?source=sumit`
for org 2 now returns `status: "partial"`, `error_summary: "4 entity types
had errors"`, and `GET /api/integration/status` for org 2 now shows
`last_sync_errors: {"sumit": "4 entity types had errors"}` while
`connections.sumit` stays `"active"` and `configured.sumit` stays `true`
(both correct — credentials ARE configured, just wrong). Orgs 1 and 5
(healthy) show `last_sync_errors: {}` — no regression.

`fetch_bank_transactions` was deliberately excluded from this error-surfacing:
`load_billing_transactions()` is permanently unsupported by the real SUMIT
API regardless of credential validity (see its own docstring), so treating
its failure as a health signal would falsely flag every org, including the
two healthy ones.

## What is NOT fixed (user action required)

The actual SUMIT `CompanyID`/`APIKey` values for orgs 2, 3, and 4 are wrong
and need to be re-entered via each org's own Settings page. This is not
something that can be fixed from here — entering or guessing credential
values is out of scope regardless of who's asking, and there is no way to
know the correct values from the code side. Org 2 in particular is worth
prioritizing: it has real financial history (₪1.5M) sitting with incorrect
customer names that a working credential + one re-sync would immediately
correct (the underlying `fetch_customers()` fix already deployed and
verified against org 1 is known-good — it just can't reach org 2/3/4 until
their credentials work).
