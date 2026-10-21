# Rezef project review — 6 September 2026

**Assessment:** Rezef has substantial, useful implementation and strong accounting
and integration safeguards. It is not yet a proven, fully autonomous bookkeeping
operation. The highest priorities are tenant boundaries, consistent approval
coverage, trustworthy reporting, and repeatable recovery/release evidence.
Expanding the feature surface should follow those foundations.

This review describes the baseline at commit `260706b`. Implementation resulting
from the review is recorded separately in
[the stabilization report](2026-09-06-stabilization.md) and the
[canonical execution plan](../MASTER_EXECUTION_PLAN.md).

## Scope and method

I inspected the architecture contract, capability manifest, execution plan,
accounting knowledge index, integration documentation, authentication and tenant
resolution, payment/document routes, approval services, ledger and report sources,
forecasting, frontend navigation and organization selection, migrations, CI,
health monitoring, and backup/restore procedures. I ran the offline test suite,
frontend build/lint, schema and route checks, and synthetic browser reproductions.

The baseline contained 205 backend Python files (81,312 lines), 150 service files,
43 router files including package initializers, 63 frontend source files (24,730
lines), 288 Python test sources (57,487 lines), and 57 migrations. These counts
measure repository size; they are not completeness or quality scores.

No live SUMIT/Open Finance calls, production writes, filing, payment, deployment,
or customer communication formed part of the review. Browser API data was
synthetic. Production credentials, deployed revision, consent, quotas and current
customer data were not independently verified.

## Baseline verification

| Check | Observed result |
|---|---|
| Full backend suite | 2,590 passed, 1 failed, 37,891 warnings; approximately 1,001 seconds |
| Isolated failing test | The calendar-month cash-flow test also failed independently |
| Frontend build | Passed; main entry chunk about 654.8 KB, gzip 135.32 KB |
| Frontend lint | Passed with zero warnings |
| Local schema | Clean apart from explicitly documented SQLite FK exemptions |
| Phantom-column scan | Clean |
| Credential-cleared, network-guarded route audit | 263 routes: 173 successful, 50 warnings, 38 configuration gates, 2 honest refusals classified as failures by the old audit |
| Browser reproduction | Home-organization selection dropped the required header; mobile sidebar left only about 102 px for content at a 390 px viewport |

The route audit's own setup needed scrutiny: importing the application can load
`.env` credentials, and some GET routes perform provider work. A safe audit needs
both credential isolation and a network barrier. Calling a script “offline” does
not establish that property by itself.

## Findings and recommended work

### F01 — Critical: registration can cross a tenant boundary

The registration flow accepted a caller-supplied `organization_id`, joined that
organization, and could merge caller-provided plan/payment settings into the
existing business. A registration code or checkout should authorize entry to the
platform, not membership in an arbitrary customer's account.

Require self-registration to create a new tenant. Existing organizations must use
an invitation from an authorized member followed by acceptance tied to the invited
identity. Cover nonexistent, zero, negative and foreign organization IDs, and
verify refusal leaves no user, membership or settings side effects.

Relevant code: `src/cfo/api/routes/admin.py`, membership services and authentication tests.

### F02 — Critical: approval coverage is inconsistent

The durable irreversible-action workflow is real: it records immutable intent,
approvals, signing authority, policy decisions and an atomic execution claim.
Some production-facing routes already use it. Several older payment, refund,
mandate, recurring and document paths instead relied on an admin/user check and
called a provider directly. Provider quotas protect cost; they do not substitute
for an owner's approval of a particular financial action.

Route every irreversible operation through the same boundary. Bind approval to
the exact operation, organization, target and payload; reconstruct persisted
intent for execution; prevent replay; and distinguish provider acknowledgement
from independent verification. Fail closed when no durable adapter exists.
Verify that a provider failure cannot commit a local document that appears
successful. Never store raw card details in the approval ledger.

Relevant code: `src/cfo/api/routes/{payments,accounting,financial_operations,open_finance}.py`.

### F03 — Critical: public authentication bypass is configurable

The development authentication bypass can create or return a privileged user.
Public deployment configuration did not explicitly reject it. A local convenience
must not remain an effective production or preview setting.

Reject backend bypass on public deployments and restrict the frontend bypass to
development builds. Verify configuration failures with synthetic settings; inspect
actual production configuration separately through the release procedure.

### F04 — High: financial reports do not consistently share accounting inputs

A Bill and Expense representing the same external document could both enter the
P&L even though the derived ledger deduplicated them. Separately, manual/payroll
journal entries could affect the trial balance while being absent from the P&L.
Absolute-value handling can turn a credit into another positive expense.

Use consistent source selection, signs and deduplication. Test one isolated
synthetic business containing document echoes, credit notes, manual journals,
payroll and imports. Reconcile P&L, trial balance and balance sheet using the same
period and explain limitations explicitly. Imported/derived records must never
be presented as independently verified official books. Legacy transaction and
unmapped-account cases require explicit source treatment, not guessed classification.

Relevant code: `financial_reports_service.py`, `ledger_service.py` and report tests.

### F05 — High: old cash projection presents assumptions as cash history

The old bank projection averaged document totals, including unpaid invoices,
as historical cash inflow. It selected an arbitrary asset account as the opening
cash balance and fell back to zero. Thirty-day increments could also duplicate or
skip calendar months. Missing evidence then propagated into apparently precise
balances and runway figures.

Bank movements should supply cash history. Outstanding, partially paid AR/AP
should supply dated forward obligations; recurring and overdue assumptions must
be visible. Accept only a trustworthy bank balance or a clearly labeled user
scenario. Unknown balances/runway must stay unavailable through the API, UI,
risk calculations and exports. Use calendar-month arithmetic.

Relevant code: `financial_reports_service.py`, `live_cash_flow_service.py`,
`live_forecast_service.py`, report and risk screens.

### F06 — High: checkout is not a sufficient entitlement boundary

A completed/paid Stripe session was accepted without a durable redemption record,
email binding or configured-price verification. Registration also accepted the
client's selected plan and payment status. Arbitrary mock-prefixed IDs were
accepted outside production.

Verify the session server-side, including buyer email, price, subscription mode
and current subscription state. Derive the paid plan from configured server prices.
Consume the session once in the tenant-creation transaction. Persist mock sessions,
expire them and keep them unpaid. Subscription updates need authenticated,
idempotent processing that cannot restore stale state.

### F07 — High: several dependency pins predate security fixes

The baseline included python-multipart 0.0.6, python-jose 3.3.0 and an old
FastAPI/Starlette combination. Upgrade compatible versions and validate the full
application rather than changing a pin alone. Keep the production requirements,
project metadata and lockfiles synchronized.

SheetJS 0.18.5 also needs maintenance attention. Its observed application use was
export-only, which matters when assessing import-related advisories; that does not
make an outdated distribution a good long-term dependency. Use the maintained
publisher distribution and verify exports.

Sources: [multipart advisory](https://github.com/Kludex/python-multipart/security/advisories/GHSA-2jv5-9r88-3w3p),
[JOSE release fixes](https://github.com/mpdavis/python-jose/releases/tag/3.4.0),
[SheetJS advisory](https://cdn.sheetjs.com/advisories/CVE-2023-30533).

### F08 — High: monitoring can miss an unhealthy service

The health response could report an unhealthy database with HTTP 200. Generic
error logging counted failures but omitted useful stack locations. Unknown schema
revision also needed to be distinguished from a healthy, known deployment.

Return a failure status for database unavailability and retain safe diagnostic
stack information. Do not leak credentials, exception values or request query
strings into diagnostics. Test both the HTTP response and durable error counter.

### F09 — High: organization selection and mobile navigation are incomplete

Selecting the operator's home organization removed `active_org_id`, although the
backend requires a super-admin to choose explicitly. Regular users with multiple
memberships lacked a persistent switcher. At 390 px, the fixed 288 px sidebar left
an unusably narrow content area.

Use a server-authorized membership list, always send the chosen organization ID,
clear cached/session scope at switch/logout, and provide mobile navigation that
preserves content width. Test both privileged and regular multi-organization users
in the browser, including API failures and logout.

### F10 — Medium/high: QA results depend on date and fragile assumptions

The failing cash-flow test generated transactions on days 10 and 11 but evaluated
them as of September 6. That is a fixture error, not a reason to include future
transactions in actual cash history. The route gate compared failure counts to an
allowance, so an unrelated regression could hide behind a known refusal. CI lacked
an executed PostgreSQL migration/constraint check and browser journeys.

Fix the fixture's evaluation date; classify expected refusals by endpoint and
response; require zero unexplained failures; assert the route inventory is not
empty. Run fresh migrations, constraints and recovery on PostgreSQL as well as
SQLite. Keep pytest runs sequential.

### F11 — High operational gap: production recovery is unproven

The repository contains a scheduled encrypted backup workflow and a restore
runbook. The runbook's drill and PITR evidence fields were incomplete. A successful
backup job or a matching schema is not proof that a real backup can be decrypted
and restored within the target recovery time.

Automate a synthetic encrypted round trip with row fingerprints and constraints.
Separately retrieve a real production backup, prove key availability, restore to
an approved isolated destination, verify the data and record measured RPO/RTO.
Do not overwrite production to conduct the drill.

### F12 — Medium: large modules and loading costs increase maintenance risk

The integration client, models and several UI/service files are large. The frontend
loads many screens eagerly. Some reports fetch unused transaction lists or scan
complete source tables in Python. These are reasons for focused improvements,
not evidence that React/FastAPI should be replaced or that microservices are needed.

Split loading by route, remove demonstrated unused queries, and extract shared
boundaries around actual changes. Defer a wholesale rewrite until correctness and
operational evidence are stable.

### F13 — Medium: status documents are difficult to reconcile

Older measured baselines, historical deployment statements and current capability
notes coexist. Some repository instructions still described local schema drift
that was no longer present. File existence in a capability manifest does not prove
an end-to-end workflow.

Keep one current status board with dated evidence and explicit blockers. Generate
source counts reproducibly. Preserve historical observations as history and avoid
promoting capabilities solely because an endpoint or test file exists.

## Strengths to preserve

The stable operating contract and accounting knowledge base are unusually explicit.
SUMIT safeguards operate at several layers: a required real limiter at construction
and request time, durable counters, daily/monthly budgets, environment checks and
fail-closed quota handling. The structural limiter test should remain unchanged.

Membership is re-evaluated on each request. Signing authority is separate from a
user's role. The approval workflow has immutable intent and an atomic claim.
Many tests cover tenancy, duplicate records, credits, migrations and provider cost.
The test network barrier prevents accidental provider traffic. These foundations
are worth extending rather than replacing.

## What remains incomplete under the capability contract

The baseline manifest reported one implemented capability, six partial, four gated
and one blocked. These are declared boundaries, not a percentage-complete score.

Official double-entry posting/readback, reversals and period locking remain blocked;
creating an open SUMIT batch alone is not verified official posting. Open Finance
needs current consent and account ownership mapping. Filing needs a complete,
triple-verified period package and professional/owner approval. The daily workflow
needs deployed evidence over consecutive mornings. Expense filing, reconciliation,
collections and management reporting need a complete evidence-backed pilot loop.
New channels or voice should follow that loop rather than distract from it.

## Work order and completion gates

1. Close registration and public-authentication bypasses; retain green tenancy tests.
2. Close legacy action bypasses and checkout replay/client-trust gaps.
3. Reconcile reports and cash projections with synthetic duplicate/credit/manual/
   partial-payment cases, including unavailable-data handling.
4. Upgrade dependencies; repair QA classification/date assumptions; add PostgreSQL CI.
5. Complete organization/mobile browser journeys and route loading improvements.
6. Prove database-failure monitoring and a documented recovery drill.
7. Complete the authorized live pilot: 20 correctly filed documents, official-book
   evidence, valid bank consent, seven consecutive morning cycles, and a verified
   reporting package.
8. Measure one calendar month, requiring at least 25 green days before expansion.

The original rough estimate for local work was 15–30 net engineering days across
these areas; provider/owner waits and the calendar-month pilot are additional.
Implementation can accelerate the code portion but cannot replace elapsed pilot
measurement or external evidence. Production actions remain subject to the
repository's owner-approval and PR/deployment rules.

Baseline evidence: [review notes](evidence/2026-09-06-review.txt) and
[original mobile screenshot](evidence/2026-09-06-settings-mobile.png).
