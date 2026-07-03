# SDD Progress — collection-reminders
Plan: docs/superpowers/plans/2026-06-25-collection-reminders.md
Base before Task 1: 56f7d30

Task 1: complete (commit 39140ca..d0da245, review clean)
  Minor (for final review): sent_at DateTime lacks timezone=True (codebase footgun); test asserts 2 fields only — both brief-mandated.
Base before Task 2: d0da245
Task 2: complete (commit d0da245..d2e10ec, review clean)
  Minor (final review): migration omits Create Date docstring/typing header (cosmetic). ⚠️ fresh_org default — confirmed OK by passing test.
Base before Task 3: d2e10ec
Task 3: complete (commit a7483a6..ca96cd6, review clean; Important timezone finding FIXED ca96cd6)
  Minor (final review): _recently_sent ignores injected today (uses wall clock) — intentional, note testability.
Base before Task 4: ca96cd6
Task 4: complete (commit ca96cd6..52fef1d, review clean)
  Minor (final review): duplicate local 'from decimal import Decimal'; test imports mid-file (PEP8). Both brief-mandated.
Base before Task 5: 52fef1d
Task 5: complete (commit 52fef1d..0d0d7ee, review clean)
  Minor (final review): duplicate asyncio import (test); no SMTP timeout (network-hang risk, out of task scope).
Base before Task 6: 0d0d7ee
Task 6: complete (commit 5f246f9..cf6bf16, review clean)
  Minor (final review): no per-org try/except in cron loop (one org error aborts batch — /cron/sync wraps per-org); skipped_no_sumit undercount; import order.
Base before Task 7: cf6bf16
Task 7: complete (commit cf6bf16..069bddc, review clean)
  Minor (final review): mid-file imports (E402, recurring); thin preview-test assertion; run route untested (acceptable).
Base before Task 8: 069bddc
Task 8: complete (commit 069bddc..cb8e464, full suite 383 passed)

=== FINAL REVIEW (opus) + fixes ===
Final review: Needs-fixes -> all resolved.
  Critical (d) SMTP timeout=10: fixed f4b9dd2
  Critical (e) per-org cron try/except+rollback+errors: fixed f4b9dd2
  Important opt-in gate on manual run (user: gate it): fixed 02b2c4e (403 when disabled)
  Minors (a,b,c,f,g): deferred per final-review triage.
FEATURE COMPLETE: 8 tasks + 3 fix commits, full suite 384 passed. HEAD 02b2c4e.

# === SPRINT: completion + test-hardening ===
Plan: docs/superpowers/plans/2026-06-26-completion-sprint.md
Decisions: T-DEC-1 honest-null+flag; T-DEC-2 keep unsupported (Epic 3 skipped)
Base before T1.1: 8fbf3f0
T1.1: complete (commit 8fbf3f0..b0b95bc, review clean) — real AR/AP aging via ARAPAgingService
Base before T1.2: b0b95bc
T1.2: complete (commit b0b95bc..6bcb980; controller-verified, 5 dashboard tests pass) — fabricated COGS removed, honest null+flag
Base before T1.3: 6bcb980
T1.3: complete (commit 6bcb980..a2ff8e8; controller-verified) — honest AI fallback, placeholder removed
Base before T1.4: a2ff8e8
T1.4: complete (commit a2ff8e8..421c734) — real average_days_to_payment + gross_profit null. Epic 1 DONE.
Base before T1.4 review: a2ff8e8
T1.4 review: clean. EPIC 1 COMPLETE (T1.1-T1.4).
T2.1: complete (commit 421c734..80f0938; controller-verified: grep status_code-in empty, 394/394 pass)
  T2.1 SURFACED BUG: revenue_analytics:199 cust['percentage_of_total'] vs 'percentage_of_total_revenue' -> 500 on /opportunities + /ai/executive-summary when customer has >=4 invoices.
Base before T2.1b (bug fix): 0f3136e
T2.1b: complete (commit 80f0938..ea041c3; 395/395) — fixed surfaced 500 (percentage_of_total_revenue key)
Base before T2.2: ea041c3
T2.2: complete (commit ea041c3..3cddf28; 396 passed; colscan guard catches Invoice.total_amount probe, removed before commit)
Base before T2.3: 3cddf28
T2.3: complete (commit 3cddf28..b6b2844; 401 passed). EPIC 2 COMPLETE.

# === Admin User Mgmt build ===
Plan: docs/superpowers/plans/2026-06-28-admin-user-management.md
Decision: admin types password; gaps = provisioning + role mgmt (isolation already complete)
Base before T1: bf47e02
T1: complete (commit bf47e02..34c5e81) — app-user CRUD; SUMIT create moved to /sumit-users
SECFIX: complete (commit 35f3bf1) — org-scope + privilege-ceiling on POST/PATCH/DELETE users; 6 sec tests RED->GREEN (caught by auto security review)
NOTE: test_check_aging_report (test_phase9_features.py:144) FAILS at base 3920d86 too — pre-existing date-sensitive flaky test, NOT a regression. Optional separate fix.
Base before T2 (frontend): 35f3bf1
T2: complete (commit 35f3bf1..efc1662) — AdminDashboard wired (create/role-edit/deactivate). EPIC done.

# === SDD run (Task 1 backend, this session) ===
T1 (SDD): complete (commit bf47e02..12d7b0c) — implementer 34c5e81 + fix wave 12d7b0c. Task reviewer (opus) flagged Important org-scoping gap on all 3 endpoints + tests encoding cross-org violation; fix added cross-org 403 + super_admin privilege-ceiling + rewrote last-admin tests (SUPER_ADMIN cross-org actor reaches genuine 409). Re-review (opus): APPROVED, spec-compliant. 23/23 admin tests pass; full suite green except pre-existing test_check_aging_report (fails at base bf47e02 too).
  Minor (for final review): unauth test asserts 403 not 401 — correct per HTTPBearer(auto_error=True), codebase-wide convention; no test hits PATCH/DELETE 404 branch (impl correct, coverage gap); renamed /sumit-users dropped response_model=UserResponse (intentional — SUMIT output isn't a UserResponse).
  NOTE: branch HEAD advanced to efc1662 (frontend T2) by concurrent actor during this run.
FINAL REVIEW (opus): Ready to merge — BOLA/IDOR+escalation fully closed on POST/PATCH/DELETE; passwords bcrypt+not exposed; guards intact; FE omits super_admin.
  Minor (follow-up, non-blocking): (1) no AuditLog on user mutations; (2) PATCH ignores email field; (3) super-admin POST with bad org_id -> 500 on Postgres; (4) 404-before-403 user enumeration.

# === EPIC 1: יציבות ותשתית ===
Plan: docs/superpowers/plans/2026-07-03-epic1-stability.md
Spec: docs/superpowers/specs/2026-07-03-epic1-stability-design.md
Decisions: audit-first; prod access approved (additive only); SUMIT write-back via quote+cancel
Base before Task 1: fb36504
Task 1: complete (commits fb36504..c1441d9, review clean)
  Minor (final review): report arithmetic narrative inconsistent (cosmetic); BudgetService constructed inside loop (trivial).
Base before Task 2: c1441d9
Task 2: complete (commits c1441d9..5ffce21, review clean)
  Minor (final review): DROP COLUMN test needs SQLite>=3.35 (plan-mandated); env-file open without context manager + single-quote strip; no FileNotFoundError handling.
  FINDING: local cfo.db has drift too (collection_reminders table + 2 org columns missing).
Base before Task 3: 5ffce21
Task 3: complete (commits 5ffce21..cdd69c6 = c9c1036 impl + cdd69c6 fix; re-review APPROVED)
  Fixed Important: NOT-NULL guard now keys only on server_default (CreateColumn never emits python default); alembic conflict except narrowed to DatabaseError + tested.
  Minor (final review): Postgres path unverified locally — Tasks 7/8 verify live vs Neon; fallback test pins OperationalError only; " NOT NULL" substring replace hack (pre-existing).
Base before Task 4: cdd69c6
Task 4: complete (commits cdd69c6..1cff52a, review APPROVED)
  Audit: 231 GET routes — 167 OK, 35 env-gated (clean 400), 4 real-bug routes (one root cause -> Task 4.1), 25 artifacts. Doc: docs/audits/2026-07-03-route-audit.md.
  Spawned Task 4.1: /api/sync/sumit/* uncaught ValueError from DataSyncService._get_sumit (data_sync_service.py:53) -> raw 500. Fix at route/domain-exception layer (service used by CLI too — no HTTPException in service).
  Minor (final review): sumit_integration.py:275 _post_binary raise_for_status uncaught -> 503 instead of accurate 4xx (include in 4.1).
Base before Task 4.1: 1cff52a
Task 4.1: complete (commits 1cff52a..1983f1e, review APPROVED)
  SumitNotConfiguredError(ValueError) + 400 handler; _post_binary -> SumitAPIError. 453 passed.
  Spawned Task 4.2: (a) _get_sumit env fallback ungated (any org gets env creds — cross-tenant leak; gate to org_id==1 like dependencies.py:298); (b) sync_engine.py:625 bare ValueError same family.
Base before Task 4.2: 1983f1e
Task 4.2: implemented (commits 1983f1e..03043ac = 997ba6b fix + 03043ac test; 456 passed)
  REVIEW INCOMPLETE — reviewer died on monthly spend limit. RESUME: re-dispatch task reviewer on package .superpowers/sdd/review-1983f1e..03043ac.diff (risks: gate airtight for non-org-1? vault flow untouched? tests exercise real path?).
SESSION END (user: "סיים", spend limit hit). NEXT: review 4.2 -> Tasks 5 (prod_smoke) -> 6 (SUMIT write-back) -> 7 (Neon drift) -> 8 (deploy+readiness). Briefs ready: .superpowers/sdd/task-{5,6,7,8}-brief.md.

# === Handoff plan resumed (docs/superpowers/plans/2026-07-03-epic1-handoff.md) ===
Step 1 (Task 4.2 deterministic verification, waived LLM review): verified —
  test_upstream_error_handling.py 6/6 passed; `organization_id == 1` gate
  present in both data_sync_service.py:60 and sync_engine.py:617;
  SumitNotConfiguredError 400 handler registered in api/__init__.py:59-60.
  Task 4.2: verified deterministically (tests+grep), review waived by user cost decision.
Base before Task 5: 03043ac
Task 5: complete (commit 03043ac..7c5db41) — scripts/prod_smoke.py + tests/test_prod_smoke.py,
  local TDD only. Full suite 457 passed. NOT yet run live against production —
  SMOKE_EMAIL/SMOKE_PASSWORD absent from .env.local, needs user-supplied creds (handoff step 2).
NOTE: session that authored the 3 planning docs + Task 5 commit (Fable 5, session 4d63fec8)
  crashed on an API error (advisor_tool_result/tool_use_id mismatch, 400) right after the
  commit and did not continue. No further commits since 7c5db41 (18:02). Resuming that
  session would replay the corrupted turn; continue with a fresh session instead.
NEXT: get SMOKE_EMAIL/SMOKE_PASSWORD from user -> run prod_smoke live (handoff step 2) ->
  Task 6 (SUMIT write-back live) -> Task 7 (Neon drift) -> Task 8 (deploy+readiness).

Step 2 (live prod_smoke): no known admin creds; user approved creating a dedicated
  smoke-test@rezef.internal SUPER_ADMIN user directly in prod DB (script in scratchpad,
  password stored in scratchpad .env.prod only, never committed). First live run:
  4/14 OK, 8 FAIL (403 "not scoped to org") + 2 FAIL (404). Diagnosed: the 403s are NOT
  a bug — production (cfo-2.vercel.app) hasn't been deployed in 3 days, so the
  SUPER_ADMIN-defaults-to-org-1 fallback (commit 23353ca, today) isn't live yet; expected
  to clear after Task 8 deploy. The 404s WERE real smoke-script bugs (wrong paths):
  fixed in commit 61e0e65 (profit-loss, ap-aging) + regression assertion added. 457 passed.
Task 6 (SUMIT write-back live): commit <pending, see below>. Created scripts/verify_sumit_writeback.py
  with corrected real signatures (DocumentItem.price not unit_price; customer_id as
  free-text name for walk-in customer; get_document_details not get_document). Live run:
  create OK (doc id 2095660684, number 1001, quote, customer "בדיקת מערכת רצף — למחיקה",
  ₪1) -> PDF OK (83034 bytes) -> **cancel_document FAILED**: "Cancelling this document
  isn't allowed". Per handoff stop-rule (create succeeded + cancel failed = stop, report
  doc id to user) — reported. User: don't block, log as follow-up task + memory, continue.
  OPEN ITEM (tracked in TaskCreate #1 + memory rezef-completion-epics): document 1001 needs
  manual cancel in SUMIT UI; investigate whether quotes need a different cancel/delete
  endpoint than invoices. Task 6 NOT fully closed — write-back chain verified up through
  PDF download, cancellation path unverified/broken for this document type.
Task 7 (Neon drift check): `python scripts/schema_drift_check.py --env-file <scratchpad>/.env.prod`
  -> "OK — אין drift: הסכמה החיה תואמת את המודלים". Clean, no action needed.
Task 8 (deploy): `vercel deploy` (preview) -> preview smoke blocked by Vercel Deployment
  Protection (no bypass secret; confirmed prod itself is unprotected) -> `vercel deploy --prod`
  (aliased cfo-2.vercel.app) -> `POST /api/admin/db/migrate` (upgraded, no pending changes)
  -> live smoke: first run 13/14 (422 on /daily-reports/vat, missing required year/month
  query params — smoke-script bug, fixed by building the path with date.today()) -> second
  run **14/14 OK**. All 8 earlier 403s gone, confirming they were caused by the 3-day-stale
  deploy, not a real bug. Post-deploy: schema_drift_check OK, full suite 457 passed.
  Commits: 61e0e65 (already pushed) covers profit-loss/ap-aging path fix; vat query-param
  fix + doc updates in the commit right after this entry.

=== WAVE 1 (EPIC 1 STABILITY) COMPLETE — deployed to production 2026-07-03 ===
All 6 handoff steps done: Task 4.2 verified, Task 5 (prod_smoke) built+fixed, Task 6
(SUMIT write-back) partially verified (create+PDF confirmed live; cancel blocked — open
item, see memory rezef-completion-epics + TaskCreate #1), Task 7 (Neon drift) clean,
Task 8 (deploy) done with 14/14 smoke green. NEXT: Wave 2 per
docs/superpowers/plans/2026-07-03-epic1-handoff.md steps 7-11 (10 upgrades, SUMIT API
gaps 8.1-8.6, AI chatbot 9.1-9.5, qa_gate.py, final deploy) — tracked in TaskCreate #4.
User approved starting Wave 2. Correctness-first spot-check before piling on features:
live VAT report re-checked against prod (org 1, months 4-6/2026) — input_vat non-zero
(earlier VAT=0 fix from memory `accounting-engine-buildout` still holds), output_vat=0
matches known "no synced sales this period" state (memory `sumit-may2026-vat-state`),
not a new regression.

=== WAVE 2 — step 7 (10 upgrades) in progress ===
7.1 COGS: DONE (commit f0fab9a). dashboard_service.get_pnl now computes real COGS from
  Transaction rows classified via CostAnalysisService.DIRECT_CATEGORIES (reused, not
  duplicated); honest None+cogs_available=False unchanged when nothing is classified.
  Full suite 458 passed.
7.2 AI honest fallback: the plan's original target (ai_intelligence_agent.py ~line 262)
  was ALREADY fixed in an earlier session (T1.3, see memory completion-sprint-2026-06) —
  verified, not duplicated. Found the real remaining fabricated-number instance in the
  same subsystem: `_calculate_liquidity_score` always returned hardcoded 20.0. DONE
  (commit 5e0657d): now computes real cash-to-burn runway from bank Account balances vs.
  expense trend; honest 0+unavailable_components flag when no bank/expense data exists
  (health-score aggregate stays summable for existing consumers). Full suite 460 passed.
7.6 Alert engine resilience: DONE (commit 3ffa7e1). evaluate_all() had zero exception
  handling — one check raising crashed the whole run, silently dropping every other
  check's alerts too. Added `_run_check()` wrapper: logs + records failures in
  `last_run_failures`, other checks still execute. New test proves isolation. Note: a
  tests/test_alert_engine.py file already existed (2 tests) — plan's "no tests exist"
  claim was stale; extended it rather than creating a new file. Full suite 461 passed.
7.5 Duplicate expense detection: DONE (commit ed07568). New `duplicate_expense` check
  in document_anomalies.py: same vendor+amount within 3 days, or same bill_number.
  Restructured detect_document_anomalies (had an early-return on zero invoices that
  would have skipped the new bill-only check entirely). 7 anomaly tests pass. Full
  suite 464 passed.
7.8 Bank sync idempotency: verified ALREADY SATISFIED, no code change needed. Both
  ingestion paths checked: sync_engine.py upserts by (org,external_id,source) against
  a real DB unique index; BankStatementService (CSV/manual import) already has a
  content-match duplicate check (date+amount+description) — zero prior test coverage
  though. Added regression test proving double-import creates 0 extra rows (commit
  c2a6348) instead of a redundant is_provisional column. Full suite 465 passed.
7.4 Payroll->journal: DONE (commit 9d239ee). run_payroll posts a balanced derived
  entry per payslip (5100 gross expense / 2300 deductions liability / 2110 net
  liability) via new ledger_service.add_payroll_entry (reuses add_manual_entry's
  line-normalization, not duplicated). Upserts by external_id
  payroll:{org}:{emp}:{year-month} so re-running a period updates, not duplicates.
  Wired into build_journal via new _payroll_entries. Full suite 467 passed.
7.7 Expense deduction_percent: DONE (commit 6ebee85). Consulted israeli-expense-categorizer
  skill before implementing — real deduction rules (vehicle higher-of, phone 50%-or-1380
  floor) need per-case inputs (odometer, use-value tables) this system doesn't have, so
  did NOT auto-compute a category->percent default (would risk a wrong real tax filing).
  Instead: nullable Expense.deduction_percent (migration 7c2e9a4f1d63), honored ONLY in
  form_1301 as a taxable-income add-back for the disallowed portion — deliberately NOT
  applied to the VAT report (VAT recovery uses different rates entirely, e.g. vehicle
  running-cost VAT's separate 2/3-vs-1/4 split). NULL = 100% recognized, verified
  byte-identical to prior behavior via dedicated test. Full suite 469 passed.
  NOTE: fixed an alembic revision-id collision (accidentally reused an existing hex id
  from add_contact_bank_fields.py) before this landed — caught by full suite, not by CI.
7.10 Warnings cleanup: DONE (commit a799c83). Real distinct-location count was 24 (18
  DeprecationWarning + 6 LegacyAPIWarning) in our own code, NOT the plan's claimed
  ~2,285 (that figure was the total repeated-firing count across all tests, not
  distinct bugs). Fixed: datetime.utcnow()->now(timezone.utc) at all real call sites
  (Column-level defaults in models.py, ~55 sites, deliberately NOT touched — bigger,
  separate, higher-risk pass); @app.on_event->lifespan; Query regex->pattern
  (pydantic v2); .query(Model).get()->db.get(Model,id) (sqlalchemy 2.0); BaseModel
  .dict()->.model_dump(); declarative_base import moved to sqlalchemy.orm. Zero
  distinct our-code warning locations remain (verified via full-suite grep); ~2150
  remaining warning instances are 100% third-party library internals. 469 passed
  throughout, no naive/aware comparison broke.
7.3 Collection workflow: BACKEND DONE (commit 308f47d). New CollectionCase model
  (migration e4d8b1f6a2c9) + collection_case_service.py (open_cases_for_overdue
  idempotent, log_attempt only advances status on real signal, set_status,
  list_cases) + /api/collections/* routes, full org isolation verified. Confirmed
  NOT redundant with existing CollectionReminder/collection_service.py (that's
  automated SMS/email dispatch; this is human-collector case tracking).
  Connected to alert_engine: new _check_stale_collection_cases (broken promise or
  no activity in 7 days), reuses the _run_check isolation wrapper from 7.6.
  19 new tests, full suite 485 passed. Frontend UI tab NOT done — deferred with 7.9.
7.9 Document issue wizard (frontend): not started.
9/10 upgrades' backend done (7.1,7.2,7.3-backend,7.4,7.5,7.6,7.7,7.8,7.10).
  Remaining: 7.3's AR-dashboard tab + 7.9's DocumentIssueWizard.tsx — both need
  npm build + tsc + manual preview verification, same batch of work.

DEPLOY (Wave 2, backend-only slice): user explicitly asked to deploy the
  backend-complete state now rather than let it accumulate further, given 13
  unreleased commits including 2 new migrations (deduction_percent,
  collection_cases). Sequence: full suite green (485) -> `vercel --prod --yes`
  (built + aliased to cfo-2.vercel.app) -> logged in as smoke-test admin ->
  POST /api/admin/db/migrate -> {"action":"upgraded","current_revision":
  "e4d8b1f6a2c9","schema_sync":{"tables":[],"columns":{}}} (no drift) ->
  prod_smoke.py 14/14 -> spot-checked GET /api/collections/cases -> 200. All 9
  backend upgrades + the new collections routes are now live in production.
  Local dev environment fixed for frontend verification: cfo.db had schema
  drift (mirroring the prod issue) blocking uvicorn startup; recreated fresh
  via init_db()+alembic stamp head, confirmed the vite dev server (port 3000)
  proxies to it correctly and is drivable via claude-in-chrome (screenshot/
  scroll/read_page all verified against the real RezefLanding page). This is
  now the verification path for 7.3's AR tab + 7.9's DocumentIssueWizard,
  since Vercel preview deploys remain protection-blocked.

7.3 (frontend) + 7.9: DONE (commit ee6c265). CFOARDashboard gained a tab
  switch (aging / collection cases); new CollectionCasesTab.tsx drives
  open-cases / list / log-attempt against the existing /api/collections/*
  routes (also enriched those routes at the route layer with contact
  name/phone/email + summed balance, commit 0c27068 — the service's
  case_to_dict only carried contact_id, not usable in a worklist UI).
  7.9's actual gap turned out to be much smaller than the plan assumed:
  DocumentManager.tsx's CreateDocumentModal already had full type/customer/
  line-item entry (a real DocumentIssueWizard already existed) — the only
  missing piece was that onSuccess just alert()'d and discarded the
  response. Replaced with a result screen showing document number/total/
  status + a PDF download button. Did NOT build a new wizard component or
  touch CustomerDashboard.tsx (that page is a disconnected stub — customers
  query hard-returns [] with a comment saying the list endpoint doesn't
  exist; wiring document-issuance into it would mean building a whole real
  customer-list feature, out of scope for this item).
  Verified end-to-end locally via claude-in-chrome: seeded an overdue
  invoice+contact, opened a case, logged a "promised" attempt with a
  promise date, watched status/attempts/promise-date update live in the
  UI. One accidental alert() (my own new code, the "open cases" success
  message) blocked the automated tab via a native dialog — fixed by
  replacing it with an inline transient banner instead of chasing the
  dialog. DocumentManager's SUMIT create-flow itself was NOT exercised
  live (no SUMIT credentials in the local dev org) — verified by
  tsc --noEmit + npm run build (both clean) + code review only; flagging
  this honestly rather than claiming full verification.
  tsc --noEmit clean, npm run build clean. No frontend test runner exists
  in this repo (no vitest/jest configured) and ESLint has no config file
  either — both pre-existing gaps, not introduced or fixed here.
  486 passed (backend, unchanged by frontend work). ALL 10 WAVE 2 UPGRADES
  NOW COMPLETE (backend deployed to prod; this frontend slice not yet
  deployed — next deploy should bundle it with whatever Step 8/9 work
  follows, per the user's "deploy now, then continue" pattern).

STEP 8 (SUMIT API gaps 8.1-8.6): DONE with major scope correction. Audited
  against the real OpenAPI spec (api.sumit.co.il/swagger/v1/swagger.json,
  pulled directly — WebFetch's own summarization silently dropped schema
  fields, so fetch-and-grep-locally is the reliable method here) instead of
  guessing field names. Most of the plan's 8.1-8.5 wording assumed SUMIT
  capabilities that don't exist; user approved creating live test artifacts
  in prod if needed for this audit (not exercised — everything below is
  TDD against mocks, matching advisor guidance not to add more live-write
  residue like doc 1001/customer 2095660683 until genuinely needed).
  8.1 (future documents): create_scheduled_document(document, schedule_date)
    was already an honest stub (raised with a clear message) — replaced with
    create_document_from_existing(document_id), the real endpoint shape
    (clones an existing DocumentID; there is no date-driven scheduling
    endpoint at all). Wired into DocumentIssuanceService.
    create_scheduled_occurrence() + new POST /financial/documents/{id}/
    schedule-next. Commits d8aa70a, f6ac68a.
  8.2 (checks/cash): built exactly as specified — DocumentRequest.payments
    (DocumentPayment: cash/cheque) adds SUMIT's real "Payments" array to
    document creation, field names taken directly from
    Accounting_Typed_Payment_Cheque (BankNumber/BranchNumber/AccountNumber/
    ChequeNumber/DueDate). Wired through the service and
    POST /financial/documents. Commits d8aa70a, f6ac68a.
  8.3 (mandates + returns): NO create-mandate endpoint exists anywhere in
    the 84-path spec — recurring items are created some other way (SUMIT's
    own UI), not via API. list/cancel/update of an EXISTING
    RecurringCustomerItemID were already fully wired (/api/payments/
    recurring/*, payment_request_service.py) before this audit — nothing
    to build for that half. Found and fixed a real bug while auditing:
    POST /api/payments/recurring/{id}/charge routed to charge_recurring(),
    a documented Not-Supported Stub that always raises a bare Exception
    (not SumitAPIError) — uncaught, would leak a raw 500 in prod. Removed
    the route (kept the stub method). Commit 1662d6b.
  8.4 (refunds/credits): reshaped by the audit — there is NO refund/reversal
    endpoint anywhere in the API. But OriginalDocumentID on document-create
    is SUMIT's own documented mechanism for "keeping a relationship between
    an original and a created document (such as credits for debit
    invoices)" — a linked credit note IS the refund primitive SUMIT
    exposes. Built DocumentRequest.original_document_id +
    DocumentIssuanceService.create_document(original_invoice_id=...):
    org-scoped lookup, passes external_id as OriginalDocumentID, reduces
    the original invoice's local balance (floors at 0, PAID when fully
    offset else PARTIALLY_PAID). Commits d8aa70a, f6ac68a.
  8.5 (chargeback alerts): documented as a real gap, NOT built. No
    chargeback-specific endpoint or webhook trigger type exists (triggers
    are generic CRM-entity CreateOrUpdate/Create/Update/Archive/Delete,
    nothing payment-specific). The only signal, Payment.Status, is
    undocumented free text — any detection would be a heuristic guess with
    no real chargeback data to validate it against. Per advisor guidance,
    building speculative code here was explicitly deprioritized in favor
    of Step 9.
  8.6: already correctly deferred to Epic 5 per the plan's own text — no
    action needed.
  Full findings + exact field names documented in SUMIT_API_REFERENCE.md's
  new "Wave 2 Step 8 additions" section. 12 new tests across 3 files
  (test_sumit_document_api_gaps.py, test_document_issuance_step8.py,
  test_payments_recurring_routes.py), all mocked, zero live SUMIT writes.
  499 passed. NOT yet deployed — bundling with Step 9 per the user's
  established "build a coherent batch, deploy together" pattern.

STEP 9 (AI chatbot 9.1-9.4): DONE, one item (9.5 live test) blocked on the
  user adding ANTHROPIC_API_KEY to Vercel (asked via AskUserQuestion; user
  chose to add it themselves — not yet visible in `vercel env ls
  production` as of this entry, so still pending on their side).
  Audited first (per the established pattern this whole wave): ai_intelligence_
  agent.py doesn't actually use Anthropic despite its name (pure heuristic
  analysis); the real Anthropic usage is vision_extractor.py (OCR pipeline),
  confirming settings.anthropic_api_key already exists and anthropic==0.40.0
  is the pinned SDK. Verified the SDK's actual tool-use shapes
  (messages.create params, ToolParam/ToolUseBlock/ToolResultBlockParam
  fields) directly against the installed package rather than assuming.
  9.1 ai_chat_tools.py: ChatTool wrappers over DashboardService,
    collection_case_service, DocumentIssuanceService. category="read"|
    "write" per tool; org_id injected by the caller, never a model param.
  9.2 ai_chat_service.py + POST /api/ai/chat, POST /api/ai/chat/confirm,
    GET /api/ai/chat/{session_id}. ai_chat_messages table (migration
    3a8a9532010b).
  9.3 Confirmation gate: a write tool (issue_document,
    log_collection_attempt) is NEVER executed as a direct result of the
    model's call, on ANY turn — the loop halts and persists a
    pending_action on the assistant's ChatMessage row; only a separate
    confirm_action(message_id) executes it, re-reading tool/input from
    that DB row (never client-supplied), guarded by an `executed` flag.
    Verified the gate is load-bearing, not passing by construction: disabled
    the write-halt and confirmed 4 of 6 tests fail. The discriminating test
    checks turn 2 (an unrelated later message), not just turn 1 — the
    invariant a prompt-only "don't write on turn 1" rule would miss.
  9.4 ChatAssistant.tsx: new /ai-chat page + sidebar entry. Pending actions
    render as an explicit confirm-required card.
  SECURITY: an automated push review on commit a5b5406 correctly caught an
    IDOR I introduced — confirm_action and the history routes scoped
    ChatMessage queries by organization_id only, not user_id. Since
    ChatMessage.id is a small sequential integer, any user in the SAME org
    could read another user's session (session_id isn't a secret) or,
    worse, confirm+execute another user's pending write. Fixed immediately
    (commit bdaa322) by adding user_id to every query; 2 regression tests
    reproduce both holes pre-fix and pass now. This is the same class of
    bug as the org-scoping issues fixed earlier in the project — same
    principle, one level finer-grained (per-user, not just per-org).
  Also found + fixed via live manual testing (not just mocks): missing
    ANTHROPIC_API_KEY caused a bare TypeError deep in the anthropic SDK to
    leak as an unhandled 500; added AIChatNotConfiguredError + an app-level
    handler (same pattern as SumitNotConfiguredError) mapping it to a clean
    400, plus a frontend error banner (neither mutation had an onError
    handler before this — a failed request left the user staring at
    nothing). Verified live in the browser against the local dev backend.
  20 new tests across tools/service/routes. 517 passed. tsc --noEmit +
  npm run build both clean. NOT yet deployed.

STEP 10 (qa_gate.py): DONE, commit e392e30. Consolidated pre-deploy QA gate
  script (scripts/qa_gate.py) running all 7 plan sections except #7 (manual
  E2E, not automatable): full suite, route audit, local+remote schema
  drift, frontend tsc+build, colscan, tenancy-focused subset.
  Two real bugs found while wiring it up (not hypothetical):
  - Route audit's own exit code is unconditionally 1 whenever ANY route
    returns outside {200,401,403,404,422} — including the 39 already-
    documented, verified-correct env-gated 400s (SumitNotConfiguredError
    etc). Trusting the raw exit code would make qa_gate permanently red.
    Fixed by having qa_gate parse the script's own printed summary line
    and compare the failure count against a documented
    ROUTE_AUDIT_BASELINE_FAILURES=39 constant — the actual criterion is
    "zero NEW undocumented failures", not "exit code 0".
  - schema_drift_check.py required DATABASE_URL to be explicitly set even
    though cfo.config.Settings.database_url already defaults to the local
    sqlite db — so the documented "just run it locally" usage failed with
    exit 2. Fixed by removing the redundant guard.
  9 new tests (test_qa_gate.py, injectable fake-subprocess runner) + 1
  (test_schema_drift_check_script.py, real subprocess against the actual
  script). 527 passed. Real end-to-end qa_gate run (not just its mocked
  tests) passed all 6 automated sections against the actual repo.

STEP 11 (final deploy, Wave 2 backend+frontend since the earlier
  backend-only slice): `vercel --prod --yes` -> built + aliased to
  cfo-2.vercel.app -> logged in as smoke-test admin -> POST
  /api/admin/db/migrate -> {"action":"upgraded","current_revision":
  "3a8a9532010b","schema_sync":{"tables":[],"columns":{}}} (only the new
  ai_chat_messages migration needed applying; deduction_percent +
  collection_cases were already live from the earlier backend-only
  deploy) -> schema_drift_check.py --env-file against Neon: clean, no
  drift -> prod_smoke.py 14/14 -> spot-checked GET /api/ai/chat/{session}
  -> 200 {"messages":[]} and GET /api/collections/cases -> 200
  {"cases":[]} live in prod -> confirmed POST /api/ai/chat still returns
  a clean 400 ("ANTHROPIC_API_KEY חסר") rather than a 500, live against
  prod, since the key still isn't configured in Vercel as of this deploy.
  IMPORTANT — this deploy does NOT close out Wave 2. Per advisor review
  before deploying: the entire AI-chat tool-use loop (messages.create,
  tool_result round-trips, loop termination, the model's tool-call args
  actually matching the executor's kwargs) has ONLY ever been exercised
  against mocks — never against a real Claude response. That is 9.5, and
  it remains genuinely open, not a formality. Also: Vercel env vars only
  take effect on a NEW deploy, so even once the user adds
  ANTHROPIC_API_KEY, a redeploy is required before 9.5 is testable — the
  key alone won't activate anything on the deployment made here. Browser-
  verification of the two existing pages this batch touched (AR dashboard
  tab switch, DocumentManager's new result screen) against live prod
  (not just local dev) was dispatched as a follow-up check; see the next
  ledger entry for its outcome once it returns.
  Remaining before Wave 2 can be marked complete: user adds
  ANTHROPIC_API_KEY to Vercel production -> redeploy -> live 9.5 test
  (one read-only tool call first to verify loop mechanics, then one
  write-with-confirmation call) -> update PRODUCTION_READINESS.md +
  SUMIT_MODULE_COVERAGE.md -> final Hebrew status report to the user.
  Task #1 (SUMIT doc 1001 / customer 2095660683 stuck-open live-test
  artifacts) also remains open and untouched this session.
