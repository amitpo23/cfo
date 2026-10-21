# Agent handoff — stopped at the owner's request

7 September 2026. This is a handoff snapshot, not another status board.
`docs/MASTER_EXECUTION_PLAN.md` remains the sole status board.

## Start here

- Workspace: `/Users/mymac/coding/cfo`.
- Branch: `fix/rezef-stabilization-20260906`; baseline HEAD `ab3fd18`.
- Read AGENTS.md, CLAUDE.md, the operating-system/capability/master-plan documents,
  competitor C01–C36 research and the relevant bookkeeper KB before continuing.
- Preserve **all staged, unstaged and untracked work**. The checkout contains prior
  provider/collection work and other editors' documents. No reset, stash, broad
  checkout or wholesale overwrite. No commit was made during this continuation.
- The user requested English communication and Hebrew RTL product UI.
- No live SUMIT/Open Finance, production, payments/refunds, filing, book/batch close,
  client messages, quota/20-hour bypass, push or deploy. Use synthetic providers.
- **Never run pytest concurrently.** Full suite must pass before any commit.
- At handoff, our pytest and leftover Vite processes were stopped. The owned local
  PostgreSQL cluster had already been stopped. Recheck processes before testing.

## What was implemented locally

Prior September 6 AR/AP work is preserved: CollectionWorkbench, payable workbench,
partial/split allocations, source-parity and reversal history, provider event
receipts, late sync relationships, Open Finance/Financy product boundaries.

September 7 additions:

1. Shared durable source intake across supported email attachments, upload and
   enabled chat intake; organization/content deduplication, original bytes and
   channel history, explicit extraction/retry, honest missing amounts/currency.
2. Versioned manual source correction with reason, actor and Note history; a pending
   Expense is separate from accounting approval, books and money.
3. PDF split/merge with durable page recipes, original preservation, retired parent
   processing, replay/conflict guards and native PDF locking. Multipage OCR no
   longer silently reads only page one.
4. Durable organization-scoped report templates, schedules, executions and files;
   occurrence claims, saved downloads and explicit failures. No external delivery.
5. Source-bound SUMIT expense draft filing, connected to HTTP, the RTL workbench
   and Moshko. See details below.
6. **Latest change:** local raster source previews (PDF and supported image formats,
   including multi-frame TIFF), page controls, original downloads and integrity
   checks. Native iframe preview was blank in Chromium; the shared PNG preview is
   now visually verified. Preview is read-only and does not run OCR or sync.

C02 is recorded as complete only within its declared local PDF scope. C01, C04,
C12, C22 and broader provider capabilities remain partial. Do not claim the entire
source → official books → payment → bank → close journey is complete.

## Filing implementation and contracts

Primary files:

- `src/cfo/services/expense_filing_workflow.py`
- `src/cfo/services/expense_filing_service.py`
- `src/cfo/services/irreversible_action_service.py`
- `src/cfo/services/ai_chat_service.py` and `ai_chat_tools.py`
- `src/cfo/services/document_intake.py`
- `src/cfo/services/sync_engine.py` (shared saved-configuration resolver)
- `src/cfo/api/routes/expenses.py`
- `src/cfo/integrations/sumit_models.py` and `sumit_integration.py`
- `frontend/src/components/ExpenseFilingWorkbench.tsx`
- `frontend/src/components/DocumentSourcePreview.tsx`
- `frontend/src/components/DocumentIntakePanel.tsx` and `ExpenseFiling.tsx`

The immutable existing IrreversibleActionRequest includes source/expense IDs,
original SHA-256, exact reviewed amounts/fields and destination SUMIT company and
connection. Credentials and source bytes are excluded. Execution rechecks actor,
membership, policy/signing, duplicate evidence, source and provider destination.
It uses one durable execution claim and requests documented `IsDraft=true`.

A consistent DocumentID gives Expense `submitted` / action `executed`, with
`official_books_verified=false`. Missing/contradictory IDs or timeout persist
`outcome_unknown`; repeat execution and replacement proposals are blocked. A
source change during execution preserves the acknowledgement and approved values
as `source_conflict`. Editing, reclassification and local account filing cannot
silently overwrite these unresolved states. Later sequential list sync recognizes
the exact saved acknowledgement and does not create another Expense.

A signer may withdraw an unexecuted approval with a reason, retaining the old
payload and signing history. Approval/withdrawal use row locks and conditional
updates. Withdrawal cannot undo an execution. The existing approval API is reused.

**Latest consumer fix:** `ActionOutcomeUnknownError` keeps the corresponding
Moshko ChatMessage `unknown`, rather than returning it to retryable pending.
The chat confirmation test also proves that confirmation alone cannot replace
an approved source-filing request.

No new migration was needed for filing or previews. Additive source/report/PDF
revisions are `a6fc4173db59`, `b70d5284ec60`, `c81e6395fd71` respectively, following
the preserved provider migrations. Local SQLite is at `c81e6395fd71`.

## Test evidence — read this before claiming green

**The latest complete focused run passed 104 tests / 1,296 warnings in 45.95s:**

`/private/tmp/rezef-source-filing-final-focused.log`

It covers source previews/intake/review/derivation, AI chat service and filing.
Other passing runs include 77 filing/approval tests, 100 chat/filing/approval tests,
83 source/provider-target/tenancy tests, and 4 preview tests. These overlap; do not
sum them as a test denominator.

Frontend lint and production build passed after the shared raster preview change:

- `/private/tmp/rezef-filing-final-lint.log`
- `/private/tmp/rezef-filing-final-build.log`

Route audit: 267 exercised GET routes, 176 OK, 51 expected 4xx, 40 environment
responses, zero unexpected failures. Local schema parity and colscan passed:

- `/private/tmp/rezef-september7-final-routes.log`
- `/private/tmp/rezef-september7-final-schema.log`
- `/private/tmp/rezef-september7-final-colscan.log`

**No clean full-suite result exists for the final changes.** The owner stopped the
last run near its beginning. Its log is:

`/private/tmp/rezef-september7-final-verified-suite.log`

Earlier interrupted full runs must not be treated as green despite filenames:

- `rezef-september7-final-full.log`: stopped after an outdated chat stub failed;
  the stub and a missing-approval regression check were fixed.
- `rezef-september7-final-full-green.log`: stopped for the explicit unknown-result
  consumer and PDF preview fixes; it has no complete passing result.

Historical full passes (2,789 initial September 7; 2,763 September 6) predate these
final changes. Full suite takes roughly 19 minutes, including slow synthetic
provider/backoff tests. Do not bypass production quota controls to accelerate it.

## Browser, concurrency and restore

`tests/browser_offline/document_intake_connected.py` uses real React → FastAPI ASGI
TestClient → temporary SQLite. API responses/business services are real; only the
SUMIT provider is fake, and external networking is blocked.

The journey covers three email attachments, cross-channel duplicate, source
correction, classification, distinct signing, withdrawal/replacement, one fake
SUMIT draft acknowledgement, split/page provenance, app-lifespan/connection-pool
restart, saved report/download and mobile RTL. It has **12 explicit browser writes**.
The latest browser extension additionally verifies visible raster source pixels and
navigation from page 1 to page 2. It passed before the final source-download
integrity guard; valid-source behavior was unchanged, but rerun it for final evidence.

Latest browser files (newer than some repository copies):

- `/private/tmp/rezef-connected-raster-preview-browser.log`
- `/private/tmp/rezef-connected-document-browser/evidence.json`
- `/private/tmp/rezef-connected-document-browser/source-preview.png` (visually read;
  shows the actual synthetic PDF text, not a blank iframe)
- `/private/tmp/rezef-connected-document-browser/filing.png`

Repository filing browser artifacts were copied **before the raster-preview
extension**. Refresh them after the final browser run; preserve older evidence as
historical snapshots when useful. The implementation audit likewise needs its
latest preview/unknown-consumer details and final validation result finalized.

`tests/postgres_offline/verify_expense_filing_concurrency.py` passed: overlapping
proposals share one request, concurrent execution makes one fake call, six signer
withdrawal versus execution races have one winner. Existing PDF/report concurrency
proofs also passed. A populated encrypted restore passed all 74 tables, 12 source
rows, 2 page recipes, 3 report rows and 2 filing acknowledgements, including hashes,
company/connection identity and schema parity.

These are local proofs; no production backup, real process restart or live provider
acceptance was established. PostgreSQL files remain preserved at:

- binaries `/private/tmp/rezef-postgres/bin`
- stopped cluster `/private/tmp/rezef-stabilization-pgdata`
- port 55432, user `rezef_test`, synthetic local databases only
- source DB `rezef_test_document_final_20260907_source`
- populated restore DB `rezef_test_filing_final_20260907_restore`

Do not drop/reuse a populated restore target; create a new explicitly synthetic
empty target if another restore is necessary. SQLite pre-migration backups remain
under `/private/tmp/rezef-before-*`.

## Next agent's immediate sequence

1. Inspect git diff/status and running processes; preserve all work and read the
   required repo instructions. No further permission is needed for authorized local
   development/tests, but the owner's latest instruction stopped this agent.
2. Run the full offline suite **alone** and resolve actual failures with TDD. Then
   run the required repo checks not already covered by equivalent final evidence.
   Do not run qa_gate concurrently with pytest; it starts pytest itself.
3. Re-run the connected browser using the webapp-testing skill's with_server helper
   on loopback port 5203. Ensure the spawned Vite child is actually stopped afterward;
   the helper previously stopped its shell but left some Vite child processes.
4. Refresh final browser artifacts, audit and MASTER's evidence wording. The
   capability registry is partial and already includes preview/unknown-state changes.
   `/private/tmp/rezef-september7-validation-source-hashes.json` records the modified
   code/test snapshot for the most recent full run. No final validation manifest was
   completed before the owner stopped work.
5. Continue the next central-flow package: reviewed multiline journal proposal and
   strict independent provider readback. Keep local implementation gaps distinct
   from provider/owner/professional dependencies.

## Explicit remaining gaps

- Strict raw SUMIT document readback and final journal/official-books evidence are
  **not implemented for this source-filing slice**. Legacy typed parsers fabricate
  defaults for missing ID/date/amount/currency; do not use those defaults as proof.
- Provider draft acknowledgement is not final classification, books or money.
  SUMIT batch finality still needs documented authorized portal evidence where the
  API does not support readback. No live action is authorized by development approval.
- Recovery after an unknown provider outcome; sync observing a provider document
  before its creation acknowledgement; business duplicate variants/concurrent
  imports need further reviewed resolution. Sequential late-sync proof is narrower.
- No complete combined source → approved journal → books → partial payment → bank
  → signed month-close journey yet. The preserved AR/AP slices are separate proofs.
- Interrupted extraction recovery, unattended queue/scheduler activation,
  collaboration/search/assignees, complex journals, real procurement three-way
  matching, FX/fees/aggregate settlements, official reversals, period locks,
  accruals/fixed assets and full close workpapers remain in the C01–C36 master map.
- Source preview is bounded to 100 pages, 1,200px output and a 40-million-pixel image
  limit. It neither extracts financial values nor changes the original.
- Competitor/public provider index coverage is incomplete; earlier HTTP 429 and
  unreviewed article gaps remain recorded. Do not invent coverage percentages.
