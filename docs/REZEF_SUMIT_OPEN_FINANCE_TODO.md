# Rezef ↔ SUMIT ↔ Open Finance — TODO

**Plan:** [`REZEF_SUMIT_OPEN_FINANCE_COMPLETION_PLAN.md`](REZEF_SUMIT_OPEN_FINANCE_COMPLETION_PLAN.md)  
**Rule:** Do not execute mutating production steps without the approval specified in the plan.  
**Pilot:** Organization 1 — עמית פורת

## Status legend

- `[ ]` Not started
- `[-]` In progress
- `[x]` Completed with evidence
- `[!]` Blocked — record blocker and owner

## P0 — Preconditions and safety

- [ ] **RSF-001** Confirm the active git branch/worktree and preserve unrelated changes.
- [ ] **RSF-002** Record the production deployment SHA and schema version before implementation.
- [ ] **RSF-003** Confirm current SUMIT block/quota/IP status without repeated test calls.
- [x] **RSF-004** Prove whether the Open Finance developer tenant matches the connected Financy account. — *2026-07-10: Vercel production `OPEN_FINANCE_CLIENT_ID/SECRET` prefixes match the keys shown at financy.open-finance.ai/settings for amitporat1981@gmail.com. Same tenant confirmed. Read-only check.*
- [x] **RSF-005** Obtain the supported Open Finance `user_id` for organization 1 without placing credentials in chat/docs/logs. — *2026-07-10: per official help center, for Financy-created connections `userId` = registration email. Set `OPEN_FINANCE_USER_ID` in Vercel production. `open_finance:ping` (token issuance) passes. Requires redeploy for the running deployment to pick it up.*
- [x] **RSF-006** Confirm that the account plan/API entitlement permits accounts and transactions APIs. — *2026-07-10: Financy plan upgraded to Starter (₪49/mo, 500 credits/mo, 495 remaining); token issuance succeeds. Actual accounts/transactions scope to be proven at RSF-041.*
- [ ] **RSF-007** Have the owner mark each Hapoalim account/card as business, personal or excluded.
- [ ] **RSF-008** Exclude the expired Hapoalim connections from the pilot. — *2026-07-10 live check: there are **four** EXPIRED connections (not two as the plan estimated), all hapoalim, zero data. Active connection: `01KX35DJ…`.*
- [ ] **RSF-009** Confirm the official SUMIT reconciliation/journal-import capability and document the source.
- [ ] **RSF-010** Decide the system-of-record policy when SUMIT write-back is unsupported.

## P0 — Call-volume protection

*2026-07-10: implemented as move M1 (two supervised Sonnet agents, TDD). Full suite: 831 passed / 0 failed. New: `SyncCheckpoint` model + migration `a3b4c5d6e7f8`, watermarks, page caps, circuit breaker, cron split, webhook delta-sync (`webhook_delta_sync.py`, `/sumit/webhooks` + subscribe route). NOT yet committed/deployed; prod deploy requires running the alembic migration.*

- [x] **RSF-020** Split SUMIT and Open Finance scheduled sync paths. — */cron/sync-sumit (hourly) + /cron/sync-open-finance (daily 05:30); legacy /cron/sync = SUMIT-only alias.*
- [x] **RSF-021** Stop hourly all-entity full sync before enabling Open Finance. — *OF cron gated to ≤1 successful full sync per org per 20h.*
- [x] **RSF-022** Pass `updated_since`/checkpoint state into connector fetches. — *watermark = last_success_at − 3d overlap (configurable).*
- [x] **RSF-023** Persist per-org/source/entity watermark, cursor, last success and cooldown. — *`SyncCheckpoint` (unique org/source/entity).*
- [x] **RSF-024** Add a cross-instance lock preventing overlapping sync runs. — *pg_try_advisory_lock session-level; SQLite no-op; `SyncSkipped` sentinel (not a SyncRun row).*
- [x] **RSF-025** Add configurable page, call and daily provider budgets. — *sync_max_pages_per_entity=20 → PARTIAL + resumable cursor; OF 20h budget.*
- [x] **RSF-026** Add provider-aware backoff and circuit breaker. — *breaking→circuit 6h; transient 5xx ≤2 jittered retries; FetchResult.retry_after honored.*
- [x] **RSF-027** Do not retry SUMIT authorization, billing-obligo, quota or IP-block failures. — *`_classify_error`: 401/403/quota/obligo/IP-block = breaking, zero retries.*
- [ ] **RSF-028** Reduce enrichment to new/changed unresolved documents in small batches. — *deferred; enrichment cron unchanged.*
- [x] **RSF-029** Add manual-refresh cooldown. — *POST /sync/run → 429 JSON + retry_after_seconds within 15 min.*
- [ ] **RSF-030** Prevent dashboards/chat/reports from triggering external calls. — *to verify separately (read paths audit).*
- [x] **RSF-031** Mark `PARTIAL`/`FAILED` runs and roster state honestly. — *page-cap → PARTIAL; SyncSkipped never recorded as a healthy run.*
- [x] **RSF-032** Test watermarks, page caps, locks, budgets and circuit state. — *tests/test_sync_call_protection.py (14) + tests/test_webhook_delta_sync.py (20).*

## P1 — Open Finance configuration and ingestion

- [ ] **RSF-040** Configure encrypted per-org Open Finance credentials for organization 1 using the existing route/service.
- [x] **RSF-041** Perform one read-only connection test. — *2026-07-10: token + `GET /v2/connections` via `OpenFinanceClient` succeeded (read-only, local run, no persistence). Note: direct `urllib` calls get WAF 403 — must use httpx (the project client works).*
- [x] **RSF-042** List provider connections once and confirm the expected active Hapoalim connection. — *2026-07-10: 5 connections; 1 ACTIVE hapoalim (`01KX35DJ…`, lastFetched=2026-07-10, expiry=2029-07-09, 1 account+1 card+1 savings, 1884 txns) and 4 EXPIRED with zero data.*
- [x] **RSF-043** Pull accounts once and classify bank/card/savings/loan/excluded types. — *2026-07-10: 6 accounts returned (read-only, not persisted): 1 CHECKING (274 txns; provider returns currency "ILY" — data-quality quirk to normalize), 1 CARD "מסטרקארד קורפורייט זהב" (1610 txns), 1 SAVINGS "פר\"י" (status=blocked), 3 LOAN rows (incl. מסגרת חח"ד). Owner classification (RSF-007/044) still pending.*
- [ ] **RSF-044** Persist only owner-approved business accounts.
- [x] **RSF-045** Pull transaction window. — *2026-07-10: owner instructed full ingestion; full available history pulled via `SyncEngine`+`OpenFinanceConnector` into prod org 1: 6 accounts updated, 1,884 bank_transactions total (1,784 created + 100 pre-existing), `is_provisional=True`, zero duplicate external_ids.*
- [-] **RSF-046** Validate debit/credit sign convention using known transactions. — *2026-07-10 read-only 7-day sample (2026-07-03..10, 30 txns, not persisted): sign convention confirmed — positive `chargedAmount` = inflow (זיכוי +15,000), negative = outflow (card charges, Isracard settlement −18,324.41). `type` values observed are `CHECKING`/`CARD` (not `BANK`). Card settlement is identifiable via `category: INCOMES_EXPENSES/CREDIT_CARD_CHECKING` — key for RSF-086/087. `status` includes `PENDING`/`BOOKED`. Owner confirmation of a known-transaction sample still needed for full acceptance.*
- [ ] **RSF-047** Validate dates, currency, description/merchant and account linkage.
- [ ] **RSF-048** Preserve raw payload and stable external ID/hash.
- [x] **RSF-049** Repeat the same pull and prove zero duplicates. — *2026-07-10: second identical full run: bank_transactions {created: 0, updated: 0, skipped: 1884}, duplicate_external_ids=0. Idempotency proven.*
- [ ] **RSF-050** Compare source↔Rezef count and debit/credit totals.
- [ ] **RSF-051** Expand to 30 days only after seven-day acceptance.
- [ ] **RSF-052** Expand to 90 days only after 30-day acceptance.
- [ ] **RSF-053** Record per-account freshness and last successful provider refresh.

## P1 — Existing UI and operations

- [ ] **RSF-060** Log in to Rezef production with explicit authorization.
- [ ] **RSF-061** Verify organization 1 is selected on every tested screen.
- [ ] **RSF-062** Verify connected accounts and freshness are visible.
- [ ] **RSF-063** Verify real bank/card transactions are visible.
- [ ] **RSF-064** Verify source, account, date, amount, description and provisional status are visible.
- [ ] **RSF-065** Verify matched/unmatched state is visible.
- [ ] **RSF-066** Verify partial/error sync state is visible and not green.
- [ ] **RSF-067** Verify accounting-event and executive views consume the same org-scoped records.
- [ ] **RSF-068** Document minimal UI wiring gaps; do not create a duplicate dashboard.

## P1 — Reconciliation

- [ ] **RSF-080** Review and port the `suggest_matches()` fix onto the current branch.
- [ ] **RSF-081** Review and port shared unmatched-transaction classification without merging the divergent branch wholesale.
- [x] **RSF-082** Run local reconciliation in dry-run mode. — *2026-07-10: `reconcile_organization` dry-run on org 1: 1,884 txns, 214 raw matches (23×1.0, 35×0.9, 26×0.8, 39×0.7, 73×0.6, 18×0.5). 104 strong matches (score≥0.7, exclusion-filtered) persisted as `is_reconciled=True`; weak 0.5–0.6 left as suggestions. Card-settlement (35 txns, ₪219k), cash, transfers, standing orders, fees excluded from matching.*
- [ ] **RSF-083** Review candidate scoring on an owner-approved sample.
- [ ] **RSF-084** Verify incoming bank movement ↔ invoice/payment matching.
- [ ] **RSF-085** Verify outgoing bank/card movement ↔ bill/expense matching.
- [ ] **RSF-086** Detect card merchant transactions separately from the bank card-settlement debit.
- [ ] **RSF-087** Prevent card settlement double-counting.
- [ ] **RSF-088** Verify one-to-one/compatible matching constraints.
- [ ] **RSF-089** Verify manual match, unmatch and feedback flows.
- [ ] **RSF-090** Persist score components and supporting evidence.
- [ ] **RSF-091** Measure match precision and approve/reject an auto-match threshold.

## P1 — Missing supporting documents

- [ ] **RSF-100** Define outgoing business-transaction eligibility.
- [ ] **RSF-101** Exclude internal transfers.
- [ ] **RSF-102** Exclude or separately classify card settlements.
- [ ] **RSF-103** Exclude or separately classify taxes and National Insurance.
- [ ] **RSF-104** Exclude or separately classify payroll.
- [ ] **RSF-105** Exclude or separately classify loans and owner movements.
- [ ] **RSF-106** Handle bank fees according to the approved document policy.
- [ ] **RSF-107** Produce `missing_expense_document` insight/task with transaction evidence.
- [ ] **RSF-108** Verify link-existing-document action.
- [ ] **RSF-109** Verify existing expense upload/OCR/review action.
- [ ] **RSF-110** Verify approved SUMIT filing without duplicate document creation.
- [ ] **RSF-111** Run targeted SUMIT delta after document arrival.
- [ ] **RSF-112** Re-run reconciliation and close the case with a stable document link.
- [ ] **RSF-113** Verify dismiss-with-reason and audit trail.

## P1 — Financial insights and questions

- [ ] **RSF-120** Verify bank insights run only on persisted organization-scoped data.
- [ ] **RSF-121** Verify cash-flow and forecasting include bank data where designed.
- [ ] **RSF-122** Verify CFO Brain surfaces unreconciled and missing-document risks.
- [ ] **RSF-123** Verify AI chat questions do not trigger provider refreshes.
- [ ] **RSF-124** Add/verify response metadata: period, organization, `as_of`, source coverage and caveats.
- [ ] **RSF-125** Run current liquid-position question.
- [ ] **RSF-126** Run monthly inflow/outflow/net question.
- [ ] **RSF-127** Run missing-document question.
- [ ] **RSF-128** Run incoming-payment-without-document question.
- [ ] **RSF-129** Run unreconciled-transactions question.
- [ ] **RSF-130** Run recurring-charges question.
- [ ] **RSF-131** Run supplier/category change question.
- [ ] **RSF-132** Run duplicate/anomaly question.
- [ ] **RSF-133** Run 7/30/60/90-day cash forecast questions.
- [ ] **RSF-134** Run upcoming-liquidity-risk question.
- [ ] **RSF-135** Run interest/bank-fees question.
- [ ] **RSF-136** Run data-completeness/freshness question.
- [ ] **RSF-137** Compare numerical answers to deterministic service outputs and source evidence.

## P2 — SUMIT completion path

- [ ] **RSF-150** Verify account-specific SUMIT API permissions against official documentation.
- [x] **RSF-151** Determine whether a real reconciliation/journal-batch/transaction-import API exists. — *2026-07-10: **YES — journal-batch API exists**: `POST /books/transactions/createbatch/` in the live swagger (`api.sumit.co.il/swagger/v1/swagger.json`, 84 paths). Request: `{Credentials{CompanyID, APIKey}, DatabaseID, BatchDescription, Transactions[{Reference1, Reference2, ReferenceDate, ValueDate, DebitAccountCode, CreditAccountCode, AmountILS, Details}]}`. It is the ONLY /books/ endpoint — double-entry journal import, not a bank-reconciliation API per se. Open questions: requires the internal-accounting (Books) module active on the SUMIT company + a chart-of-accounts code mapping + DatabaseID; bookkeeping currently lives at the accountant's SUMIT company. Help-center has no article for it (undocumented publicly, but in the official spec). No bank-row import or reconciliation-record API exists; SUMIT's own bank module (Growth plan+) uses SUMIT's bank feed with manual "generate document from row" workflow.*
- [ ] **RSF-152** If an API exists, document request, idempotency and confirmation identifiers before implementation.
- [ ] **RSF-153** If no API exists, document the SUMIT UI file-import format and validation rules.
- [ ] **RSF-154** Rename/represent customer remark outcome as `remark_posted`, not reconciliation confirmation.
- [ ] **RSF-155** Keep unsupported bill/expense write-back honest.
- [ ] **RSF-156** Produce a dry-run payload/file for one approved sample only.
- [ ] **RSF-157** Obtain explicit action-time approval before SUMIT mutation/import.
- [ ] **RSF-158** Execute one controlled approved case.
- [ ] **RSF-159** Verify SUMIT batch/record identifier, count and totals.
- [ ] **RSF-160** Persist confirmation evidence in Rezef.
- [ ] **RSF-161** Verify correction/reversal procedure.

## P2 — Quality gates

- [ ] **RSF-170** Add/update connector fixture tests without live network calls.
- [ ] **RSF-171** Add reconciliation cases for inflow, outflow, card purchase, settlement, transfer and missing document.
- [ ] **RSF-172** Add tenant-isolation tests.
- [ ] **RSF-173** Add partial/error-status tests.
- [ ] **RSF-174** Add financial-question regression tests.
- [ ] **RSF-175** Run targeted backend tests.
- [ ] **RSF-176** Run full backend suite.
- [ ] **RSF-177** Run frontend production build.
- [ ] **RSF-178** Run production smoke checks without accounting mutations.
- [ ] **RSF-179** Record call-volume and source-parity evidence.
- [ ] **RSF-180** Conduct owner review of real matches, exclusions and missing documents.

## P2 — Rollout

- [ ] **RSF-190** Complete organization-1 read-only shadow run.
- [ ] **RSF-191** Approve organization-1 canary scope.
- [ ] **RSF-192** Enable persisted ingestion only.
- [ ] **RSF-193** Enable owner-approved local matching.
- [ ] **RSF-194** Keep SUMIT actions per-action approval-gated.
- [ ] **RSF-195** Review daily completeness, errors and provider budget during canary.
- [ ] **RSF-196** Approve or reject controlled automation.
- [ ] **RSF-197** Document rollback and execute a non-destructive rollback drill.
- [ ] **RSF-198** Update `PROJECT_STATUS.md`, production-readiness docs and release evidence.

## Completion evidence

- [ ] **RSF-200** Active source identity and business-account allowlist recorded.
- [ ] **RSF-201** Source↔Rezef account and transaction parity recorded.
- [ ] **RSF-202** Zero-duplicate replay demonstrated.
- [ ] **RSF-203** Reconciliation accuracy and card-settlement handling demonstrated.
- [ ] **RSF-204** Missing-document lifecycle demonstrated.
- [ ] **RSF-205** Financial-question suite demonstrated with evidence and freshness.
- [ ] **RSF-206** SUMIT path demonstrated or explicitly accepted as local-only/unsupported.
- [ ] **RSF-207** API budget/circuit-breaker evidence recorded.
- [ ] **RSF-208** Final owner acceptance recorded.
