# Provider business-flow expansion — local implementation evidence

Status authority: [MASTER_EXECUTION_PLAN.md](../MASTER_EXECUTION_PLAN.md).
This report extends the committed [collection slice](2026-09-06-collection-settlement.md).
The working branch is `fix/rezef-stabilization-20260906`, based on `ab3fd18`.
Existing unrelated work, including the podcast notes, competitor research and `sites/`,
has been preserved. This expansion is not a production rollout.

## Implemented local workflows

### Customer collection and allocation

An identified SUMIT tax invoice can be proposed for collection through SUMIT or
Open Finance, reviewed through the existing signing workflow, executed once and
read back as a **payment request**. Pending, failed, cancelled and unknown outcomes
remain distinct from receipt and bank evidence. Authenticated Open Finance event
observations are visible without triggering synchronization or changing debt.

An existing final SUMIT receipt can be allocated across several invoices and bank
movements. Several receipts can settle one invoice. Amounts are bounded by the
remaining invoice, receipt, bank and request capacities. Excess stays unallocated.
A receipt that predates a request is considered before proposing another collection.
The existing provider document is reused; a second receipt is not issued by this flow.
An explicitly reviewed reversal retains the original allocation and appends history.

The `/collections` screen and Moshko share the same saved workbench. Proposal,
approval, execution, exact source selection, remaining balances, excess, provider
conflicts and reversal evidence are accessible under the existing permissions.
The legacy payment-request route redirects here; unsupported in-memory creation,
send and mark-paid prototypes fail closed.

### Supplier request and bank settlement

The new `/supplier-payments` screen and Moshko tools support an identified SUMIT
supplier bill, a reviewed beneficiary, an explicit withholding decision, a signed
ILS payment request and an independently read provider result. The reviewed payee
and bill identities are frozen in the approved payload. Missing bank information,
changed identity, revoked authority, unresolved attempts and unreflected existing
payments block execution or further proposals.

A pending provider request does not reduce the bill. An admin with reconciliation
permission can link an exact, final booked bank outflow with a reason. Several
outflows can settle one request, and a request may cover only part of a bill.
One organization lock protects capacities; same-bank replay does not add another
payment. The resulting local payment links the supplier, bill, request, provider
reference and immutable bank-decision history. Split bank dates remain separate
in the derived journal, contact ledger, accounting event view and draft export.
Local reversal restores the bill balance without initiating a refund.

This adapter supports owner-reviewed cases where withholding is not required or a
valid exemption has been established. It does not infer exemption from a default
zero contact rate. Withholding deductions, multi-bill outgoing bulk payments,
schedules, charges, fees and FX remain separate required adapters.

### Synchronization and product boundaries

Authenticated provider event receipts preserve duplicate/conflicting/out-of-order
observations. Ambiguous organization identity is rejected. Payment, connection and
bank identifiers have distinct meanings; matching numbers cannot create a relation.
Callbacks do not update balances or freshness and do not bypass the 20-hour budget.

Page records and checkpoints commit together. Missing or repeated continuation
cursors fail visibly; failed pages roll back without discarding earlier committed
pages. Missing transaction identity, amount, currency or date cannot become a made-up
transaction. Explicit account and bill links can resolve later, within organization
and source boundaries. Inactive credentials cannot fall back to environment access.

Reviewed collection and supplier decisions are protected from conflicting sync.
A late official supplier payment is blocked for explicit parity review before it
can double-count an existing local bank settlement. No relationship between official
and local payments is invented to bypass that review.

Open Finance and Financy now require explicit product configuration. Financy's paid
plan and connected-party rules are separate from platform route availability.
Configuration writes require an admin. The account model retains exact provider
account-number evidence for a reviewed funding party. Financy connections remain a
portal step. Payment writes are not automatically replayed after token errors or
ambiguous provider outcomes.

## Verification and preservation

Tests use synthetic records and fake provider clients. Red tests were observed
before the allocation, source-integrity, product-boundary and supplier changes.
Supplier regression tests cover partial/multiple settlement, provider status variants,
duplicate proposal/execution, timeout, missing evidence, existing payments, organization
isolation, revoked authority, policy denial, later source changes and reversal history.
HTTP and Moshko share the same workbench and services.

The full-suite result for this expansion is pending at the time of this report's
initial write. The earlier 2,668 result is the committed baseline, not validation of
these changes. Final validation evidence will be recorded here after completion.

Passing local evidence already recorded:

- Both offline browser journeys, with all API calls intercepted, including mobile
  width, partial allocation/settlement, pending status and reversal history.
- Frontend TypeScript/Vite build and zero-warning ESLint.
- Route audit: 264 routes, 174 successful, 50 expected 4xx, 40 environment-dependent,
  zero unexpected failures. No live readiness scripts were used.
- Clean column-reference scan and local schema drift check; three documented SQLite
  foreign-key limitations remain visible, with PostgreSQL checked separately.
- Fresh PostgreSQL migration and encrypted synthetic restore at revision
  `95eb3062ca48`: 71 tables, all-table hashes, schema parity, foreign keys and checkout
  uniqueness. This is not evidence of an actual production backup or PITR recovery.
- PostgreSQL concurrency checks for customer allocations and supplier settlements:
  over-capacity competitors are blocked, replay is idempotent and reversal history
  remains intact.

The migrations add event history, generalize the existing collection allocation
constraints and retain provider account identity. The earlier allocation migration
was tested against an existing row with unchanged evidence. Legacy records do not
receive invented reversal/balance evidence. Downgrades refuse to discard the new
relationships. Local SQLite backups were preserved before each local upgrade.
Production migration remains governed by the owner-approved deployment runbook.

## Remaining work and live-use gates

The [41-row business matrix](../provider_business_evidence.json) is a process
inventory, not a complete provider capability denominator. Its partial and untested
rows remain open. The [public contract review](2026-09-06-provider-contract-review.md)
records the current product differences and incomplete SUMIT help crawl.

| Boundary | What remains |
|---|---|
| Official SUMIT books | Local settlement/reconciliation is not official posting. Confirm supported receipt/payment relationships and batch readback; use the authorized portal procedure where the API lacks the required operation. |
| Professional document selection | The collection slice uses an existing tax invoice and receipt. Advances, invoice-receipts, credit documents and withholding accounting require business/event evidence and the applicable bookkeeping SOP. |
| Advanced payments | Multi-bill outgoing bulk, schedules, mandates, recurring installment outcomes, returns and refund settlement need their own complete business adapters and provider contract evidence. |
| Advanced reconciliation | Card aggregate fees, FX differences, internal transfers and counter-movements remain partial; amount/date/name are candidates, not proof. |
| Office capabilities | Assets, annual adjustments, corrective filings, filing continuity, material cycles and cross-client workflows remain individually recorded in the matrix and representative gap register. They have not been declared complete by this release. |
| Public knowledge discovery | SUMIT returned HTTP 429. The current comparison includes 161 article IDs missing locally and 144 uncached collection pages. Missing article bodies were not represented as reviewed. |
| Owner/provider configuration | Verify product/plan, scopes, live consent, exact funding identity, callback delivery configuration, beneficiary and withholding evidence. Stored configuration is not live entitlement proof. |
| Release/pilot | No production schema change, push, deployment, live sync, payment, message, filing or batch close occurred. The existing owner-approved pilot and professional verification gates still apply. |

The broad completion request is therefore **not fully closed**. This report proves
the bounded local workflows above and identifies unfinished implementation separately
from provider and owner gates. It does not claim full SUMIT/Financy coverage.
