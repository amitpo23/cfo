# Invoice → collection request → receipt → bank: local implementation

This extends stabilization commit `7d25c76` on the existing working branch. The
podcast learning document and other contributors' changes were preserved. The
canonical status board remains `docs/MASTER_EXECUTION_PLAN.md`.

## Implemented slice

A final, source-identified SUMIT tax invoice in ILS, with a known customer and open
balance, can be proposed for collection through Open Finance or SUMIT. The proposal
is an existing `IrreversibleActionRequest`: invoice/customer source identities,
amount, currency, selected channel, creditor account and required receipt type are
inside its immutable payload. Existing organization policy and signing authority
are checked at proposal, approval and execution. An unresolved request prevents a
second channel/request for the invoice. A timeout locks the attempt for review.

Open Finance execution uses the existing `create_payment` and `get_payment`
methods. SUMIT uses existing `beginredirect` through `DocumentIssuanceService`,
including the documented `ExternalIdentifier` and receipt `DocumentType` fields.
The amount is the approved partial/full balance. No message is sent to a customer.
The creditor details are explicitly presented for signing review; this slice does
not assert that an arbitrary entered creditor account has been independently
verified as the company's account.

Request creation does not change AR. The existing action status `verified` is kept
for compatibility and explicitly qualified as `verification_scope=payment_request`.
The separate money state distinguishes pending, failed, cancelled, debtor-settled,
provider-settled and unknown. Even `ACCC` does not, by itself, close the invoice.
SUMIT returns a payment-page URL, not a payment ID or readback; its request remains
executed and unverified.

Settlement reuses a final SUMIT receipt already in `Payment` and a positive,
booked, non-provisional Open Finance `BankTransaction`. The admin records the
reviewed identity/reference evidence. Customer, amount, currency, invoice scope,
existing allocations and bank ownership of the local match are checked. A new
`CollectionPaymentAllocation` links these existing records and the request. It
stores the allocated amount, receipt identity, actor, decision, source hashes and
observation dates. Unique constraints prevent reuse of a request, receipt or bank
movement in this single-invoice slice. Replay returns the same allocation.

A partial allocation leaves the residual balance and `PARTIALLY_PAID` status.
Already-linked receipts are not deducted twice, and a linked billing observation is
not counted as an additional accounting receipt. This includes the unambiguous
legacy billing shape carrying `payment_id` without a receipt document identity. Unexplained source-paid totals
remain a parity problem requiring review. Subsequent invoice sync preserves the
reviewed balance, including receipts linked before this allocation workflow.
Conflicting normalized updates supplied to sync (including a
changed customer, document type or cancelled receipt) are refused for reversal
review. Manual match/unmatch cannot silently overwrite these allocations.

The receipt satisfies the document step without creating another document. A
missing receipt is `awaiting_existing_receipt_or_approved_issue`; an existing tax
invoice calls for a receipt under the local knowledge base. Proformas, exempt
business document selection, refunds and ambiguous document types are outside this
slice and require a separate reviewed accounting decision. This implementation
never automatically issues a second receipt.

## Revalidated findings

| Finding | Current outcome |
|---|---|
| Amount/date matched at 1.0, including provisional bank data | Reproduced, corrected. Similarity returns `candidates`, with review reasons, not confirmed matches. Payment observations join the candidate pool, including partial receipt amounts. |
| Local match treated separately from SUMIT writeback | Preserved and tightened. Missing connector operation stays `unsupported`; even a dynamically present write method requires a reviewed approval adapter. No automatic posting or provider acknowledgement is labelled official confirmation. |
| SUMIT payments omit invoice link | Confirmed against the saved August Swagger. Billing payment and receipt-list schemas expose no invoice link. No field is invented. The connector labels this limitation, separates `billing:` and `receipt:` IDs, and excludes failed/pending charges and draft receipts from receipt ingestion. |
| Sync misses later invoice relationships | Fixed: an explicit normalized invoice reference is resolved on updates even when the source payload hash is unchanged. Legacy IDs are upgraded only when their entity type is unambiguous. |
| Chat bank request has no invoice relationship | Fixed: the tool requires the invoice and durable approval ID and delegates to the linked workflow. Old unlinked calls fail before provider construction. The legacy SUMIT HTTP/chat payment-link entry points require that same durable invoice/channel-bound approval. Old stored chat envelopes fail the existing schema-change guard. |
| `verified` can accompany provider `PENDING` | Confirmed. Reviewed consumers: approval serialization, policy budget states and payment orchestration. Kept action-state compatibility; added explicit request-verification scope and independent money state to readback and API output. No `Payment` or debt closure is created from this status. |

Daily automation's former payment-by-amount linker now also returns candidates
without changing `Payment.invoice_id`/`bill_id`. The synthesis worklist asks for
identity/document review rather than recommending a new document from a bank
amount. Billing-payment observations are retained as source evidence but excluded
from a second accounting/customer-card credit. Existing legacy decisions are not
bulk-reversed or retrospectively asserted to be verified.

## Local API journey

These are Rezef application routes, not newly assumed provider endpoints.

1. `POST /api/financial/collection/requests` with `invoice_id`, decimal-string
   `amount`, `channel` (`sumit`/`open_finance`), `idempotency_key`, and for bank
   collection `creditor={name,account_number,account_type}`.
2. Approve the returned `request_id` through the existing
   `POST /api/approvals/{id}/approve` signing workflow.
3. `POST /api/financial/collection/requests/{id}/execute` consumes the stored intent
   once. Return the generated link to the operator; payer authorization is external.
4. Normal cost-gated ingestion supplies receipt and bank observations. There is no
   screen/chat-triggered sync and no new unauthenticated payment webhook.
5. `POST /api/financial/collection/requests/{id}/allocate` with `payment_id`,
   `bank_transaction_id` and a meaningful reviewed `reason` records the decision.
6. `GET /api/financial/collection/requests/{id}` reads local stage state, remaining
   balance, request/receipt/bank identities, evidence and pending official readback.

The bank dashboard distinguishes candidate counts from confirmed local matches.
The HTTP workflow is the tested operator interface; a dedicated collection wizard
has not been added.

## Boundaries and release work

- Only the single-invoice, single-receipt, single-bank-movement ILS slice is covered.
  Many-to-many settlements, card clearing batches, FX/fees and reversals need their
  own allocation rules and evidence. They are not auto-guessed here. Receipt lists
  exclude non-final documents; this slice does not claim automatic detection or
  ingestion of later provider receipt cancellation/refund events.
- SUMIT billing and receipt list APIs do not identify the original invoice or each
  other. Explicit human identity review is the bridge when source identifiers do
  not establish the relationship. This is not automatic matching by amount.
- An existing receipt proves a source document observation, not official books,
  batch closure, reconciliation writeback or independent ledger readback.
- Pending/unknown provider results are not polled from status screens. Later bank
  evidence arrives through ordinary ingestion. Payment webhook authentication and
  automatic provider-result ingestion are not claimed by these offline tests.
- `62b80d39f715` is an additive migration after `51a79c28e604`. Production rollout,
  migration and configuration remain owner-controlled through the existing runbook.
- No live SUMIT/Open Finance request, payment, production write, filing, sync-budget
  override, push or deployment was performed. Live consent/freshness/quota evidence,
  official posting/readback, seven mornings and the calendar-month pilot remain
  required. Capability labels remain partial/gated/blocked.

## Validation

TDD runs first reproduced the missing workflow, weak-match confirmation, missing
request-vs-money status, source-ID collision, late-link loss, partial-balance reset,
and unsafe manual/sync mutation. Regression tests cover these and the HTTP journey,
PENDING/failure/cancellation, partial and already-recorded receipts, duplicate
execution/allocation, cross-organization refusal and unsupported writeback.

- Broad focused regression pass: 178 tests passed after the entry-point and
  consumer changes. The subsequent full suite passed 2,660 tests. Final review
  added six red regressions for duplicate billing credit and allocated source
  identity changes; the corrected focused run passed 53 tests. The QA gate then
  passed all nine local checks, including 2,666 backend tests; Neon was skipped.
  Two final regressions reproduced legacy billing duplication and loss of a
  previously linked receipt on sync. The corrected focused run passed 55 tests.
  Final full-suite result: **2,668 passed**, 38,751 warnings, 1,044.70 seconds.
  The implementation files matched their frozen hashes before commit.
- Frontend TypeScript/Vite build and lint passed.
- Fresh SQLite migration tests passed as part of the focused run. The local
  `cfo.db` was backed up before migration from `51a79c28e604` to `62b80d39f715`;
  structural drift now passes with the existing documented SQLite FK exemptions.
  Backup: `/private/tmp/rezef-before-collection-62b80d39f715.sqlite3`.
- PostgreSQL: 69-table fresh migration, schema parity and encrypted restore passed;
  request, payment and bank allocation uniqueness were additionally exercised with
  rolled-back synthetic inserts. No production backup was involved.

Evidence: [consolidated validation](evidence/2026-09-06-collection-validation.json),
[PostgreSQL restore](evidence/2026-09-06-collection-postgres.json),
[allocation constraints](evidence/2026-09-06-allocation-constraints.json),
[browser checks](evidence/2026-09-06-collection-browser.json) and
[candidate screen](evidence/2026-09-06-collection-candidates.png).

The synthetic browser check passed: opening the bank screen performed no mutation,
candidate and confirmed counts were distinct, provisional data was disclosed, and
there were no JavaScript errors. The browser check is included in CI with its own
artifact output; the CI-equivalent local invocation passed. Temporary browser and
PostgreSQL servers were stopped.
