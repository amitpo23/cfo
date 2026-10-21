# Rezef stabilization implementation — 6 September 2026

The local stabilization work from the approved review plan is implemented on `fix/rezef-stabilization-20260906`,
starting from `260706b`. The canonical status board is
[MASTER_EXECUTION_PLAN](../MASTER_EXECUTION_PLAN.md). This document records the
changes and evidence; it does not promote production capability statuses.

## Changes

| Review finding | Implemented behavior | Evidence |
|---|---|---|
| F01 — registration/tenancy | Self-registration always creates an owned tenant; any supplied organization ID is refused. Existing tenants use authenticated invitations and membership acceptance. | `tests/test_registration_boundary.py`, membership HTTP tests |
| F02 — irreversible actions | Typed legacy adapters require a durable approval, match the full operation/path/body intent, reconstruct persisted inputs, claim once, and record provider acknowledgements as unverified. Raw card data is refused before persistence. Failure rolls back uncommitted business rows before recording the action outcome. | `tests/test_legacy_action_approvals.py`, `tests/test_document_issuance.py` |
| F03 — public authentication bypass | Public deployment configuration rejects backend bypass; compiled frontend builds cannot enable the development bypass. | registration boundary tests; frontend build |
| F04 — P&L consistency | Bill/Expense echoes are deduplicated, credit signs preserved, and manual/payroll/imported journal contributions included. Imported/derived reporting limitations are disclosed. | `tests/test_report_consistency.py`, ledger report tests |
| F05 — cash projections | Historical figures come from bank movements. Forward amounts use outstanding AR/AP and the existing disclosed recurring assumptions. Calendar months replace 30-day steps. Unsupported balance, runway and risk figures stay unavailable through API, UI and Excel. | `tests/test_projection_boundary.py`, live cash-flow tests, export and risk tests |
| F06 — checkout | Server verifies session completion, payment state, buyer email, configured price, subscription mode and current subscription state. Checkout consumption is atomic with tenant creation. Mock sessions must exist and expire after 24 hours; they never activate paid status. Signed subscription events are deduplicated and older state cannot overwrite newer state. | `tests/test_checkout_boundary.py`; migration `51a79c28e604` |
| F07 — dependencies | FastAPI, Starlette, Pydantic, multipart, JOSE and HTTPX upgraded with consistent requirements and lockfile. SheetJS upgraded from 0.18.5 to the publisher-maintained 0.20.3 distribution; React Router upgraded to 7.18.3 for the redirect/security fixes, compatible with the existing React 18 and Node 20 CI. | full QA gate; package lockfiles |
| F08 — health/errors | Database failure returns HTTP 503. Unknown revision degrades health. Error logs retain exception type and stack locations without exception values or query strings. | `tests/test_readiness_boundary.py`, self-monitoring tests |
| F09 — browser UX | Membership-aware persistent organization picker, explicit home-organization header, mobile navigation, logout scope cleanup, route-level dashboard loading. | offline Playwright journeys for both admin roles; screenshots |
| F10 — QA | Fixed the date-sensitive cash test. Route checks use the public OpenAPI inventory, classify known unavailable capabilities by path/status, and allow zero unknown failures. Route audit blocks external network and provider credentials. Default schema checks stay local. | route/QA tests; audited routes; CI |
| F11 — recovery | Added a local-only encrypted PostgreSQL restore drill and CI job. Fixed the optional `pg_trgm` migration so a missing extension does not abort the full migration transaction. | 68-table synthetic PostgreSQL drill |
| F12 — maintainability | Route code splitting and removal of unused report queries address measured costs. Broader service rewrites remain outside this stabilization change. | frontend build; source diff |
| F13 — status clarity | Current implementation/evidence linked from the canonical plan and capability map, with live gates kept explicit. | canonical documentation |

## Legacy actions that remain intentionally gated

The in-memory InvoiceService/PaymentRequestService prototypes cannot support
reliable execution across requests. Their issue/cancel/credit-note/payment/standing-order
mutation routes now refuse execution with an explicit approval-adapter error.
Unreviewed batch charging, accounting-setting mutation and document-number mutation
also fail closed. They are not reported as implemented financial workflows.

SUMIT acknowledgements from new adapters are `executed_unverified`; they do not
prove official posting, independent readback, or period closure. The existing
separate-approver rules and signing-authority checks remain in force. The SUMIT
request-limiter structural test and cost gates remain intact.

Adapter intent shape for decorated legacy routes is:

```json
{
  "operation": "open_finance.refund_payment",
  "arguments": {"payment_id": "provider-reference", "body": {"amount": 10}},
  "amount": 10
}
```

Propose and approve through the existing irreversible-action workflow, then send
`X-Rezef-Approval-Id` on the matching endpoint. The three explicit payment adapters
use their typed request fields at the top level plus an operation name. No raw
card information belongs in an approval request.

## Deployment and owner gates

1. Review the local changes and release through the repository's PR process.
2. Apply `51a79c28e604` under the existing Gate 0 owner-approved migration procedure;
   verify drift and revision. The local SQLite database was backed up and migrated.
3. Configure `STRIPE_WEBHOOK_SECRET` and deliver signed subscription snapshot events
   to `/api/admin/billing/webhook`. Configure server-owned price IDs and verify the
   actual Stripe account/domain setup before enabling production checkout.
4. Prove actual production backup retrieval, decryption-key availability and restore;
   the synthetic drill does not verify these or the production RPO/RTO.
5. Complete the pilot with authorized provider access: valid bank consent, ownership
   mapping, measured quotas, 20 correctly filed documents, official-book evidence,
   seven consecutive morning cycles and a triple-verified reporting package.
6. Measure the approved calendar-month pilot and require at least 25 green days
   before expansion.

No production deployment, provider payment, filing submission, period closure,
message to a customer, or live sync was performed in this implementation session.
The gated/blocked capability statuses remain unchanged.

## Evidence

[Consolidated validation record](evidence/2026-09-06-validation.json).

- PostgreSQL: [synthetic restore result](evidence/2026-09-06-postgres-restore.json).
- Browser: [journey result](evidence/2026-09-06-browser-journeys.json) and
  [390 px screenshot](evidence/2026-09-06-settings-mobile-fixed.png).
- Route audit: 262 routes; 172 successful, 50 expected authorization/input warnings,
  40 configuration/capability gates, zero failures.
- Local schema: no drift; the three previously documented SQLite FK exemptions
  remain visible. PostgreSQL schema and constraint checks passed.
- Frontend: TypeScript/Vite build and lint passed. Main application chunk reduced
  from 654.8 KB to 117.44 KB (gzip 30.40 KB) in the final dependency build; this is
  the entry chunk, not total transferred JavaScript.
- Full backend suite: **2,626 passed**, 37,392 warnings, 974.98 seconds.
- QA run: full suite, route audit, local schema, frontend lint/TypeScript/build,
  column scan and tenancy checks passed. After staging the new referenced files,
  the capability/skill evidence gate passed separately: **9 tests passed**.
  All nine local QA checks now have passing evidence; the live Neon check was skipped.
- Final production dependency audit (`npm audit --omit=dev`): **zero known vulnerabilities**. The build, lint and browser journeys were repeated after the React Router upgrade. This audit covers npm production dependencies, not a comprehensive Python or infrastructure security scan.
- SheetJS 0.20.3 XLSX round trip preserved a numeric amount and an unknown (null) balance.
- Focused tenancy pass: 86 tests. Earlier upgrade/consumer failures were reproduced
  and fixed; their failing runs are not presented as passing release evidence.

Dependency sources: [Stripe session retrieval](https://docs.stripe.com/api/checkout/sessions/retrieve),
[Stripe webhook verification](https://docs.stripe.com/webhooks),
[FastAPI package metadata](https://pypi.org/project/fastapi/0.141.1/),
[JOSE release notes](https://github.com/mpdavis/python-jose/releases),
[SheetJS maintained distribution](https://docs.sheetjs.com/docs/getting-started/installation/nodejs/),
[React Router v7 upgrade requirements](https://raw.githubusercontent.com/remix-run/react-router/react-router%407.18.3/docs/upgrading/v6.md).
