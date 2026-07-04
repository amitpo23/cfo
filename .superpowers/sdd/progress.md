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
  Investigated further (Wave 2, ground-truth swagger spec now available): the full
  84-path spec has exactly ONE document-cancel endpoint
  (/accounting/documents/cancel/, same one already used) and NO document-delete
  endpoint at all — the "isn't allowed" rejection is a genuine SUMIT business rule
  for this document type (quote), not an implementation bug; nothing to fix in our
  code. A generic /crm/data/deleteentity/ (EntityID-only) exists that might apply
  to the leftover test customer, but its semantics against a live SUMIT account are
  unverified and it's a destructive, hard-to-reverse call against a real third-party
  system — deliberately NOT attempted autonomously. Manual cleanup via the SUMIT
  web UI remains the correct, safe path; still open.
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

CONTINUOUS-IMPROVEMENT LOOP — iteration 1 (gap-mapping): Wave 1+2 are green
  in prod (per the goal directive's own gate: no improvement loop before
  they're green), so entered the loop per docs/superpowers/plans/
  2026-07-03-rezef-goal-directive.md. Scanned docs/PRODUCT_AUDIT_AND_
  ROADMAP.md (dated 2026-06-19, from a 20-agent read-only audit) against
  current code — found it materially stale. Confirmed FIXED (already, not
  by me this iteration): VAT-split fallback (commit 23353ca, this
  morning), `/ap` route now renders CFOAPDashboard (was CFOARDashboard),
  AgreementCashFlow now persists to CashflowAgreement/CashflowEntry
  tables, CashFlowDashboard now routed+in nav at /cashflow-detail, ledger
  opening-balances now implemented. Updated the roadmap doc to match
  reality (all with file/line evidence) rather than trust stale flags —
  this is exactly the "multi-agent audit reliability" lesson from memory
  product-audit-2026-06 in the other direction: this time verifying
  against live code/DB instead of trusting a document.
  NEW FINDING (P0, evidence-backed, NOT fixed, NOT autonomous — surfaced
  to user): investigated the roadmap's old P1 "balance_sheet missing
  derived:true+disclaimer" and found it understates the problem badly.
  `/api/reports/balance-sheet` + `/api/reports/profit-loss`
  (financial_reports_service, dashboard `/reports`) read Account/
  Transaction tables that are ENTIRELY DISCONNECTED from the real
  SUMIT-synced Invoice/Bill data that /ledger and /dashboard/pnl
  correctly use. Measured live in prod for org 1 (21 real invoices
  ₪512,327 + 875 real bills -₪942,428): /api/ledger/balance-sheet's AP
  line = -942,428.02 (exact match to real bills sum, correct); /api/
  reports/balance-sheet total_assets = -24,634.68 (built from just 6
  Account rows / 127 Transaction rows that are NOT real bank data — every
  sampled row is transaction_type=EXPENSE, amount=0.00, description=
  "15: Unknown"). Root cause: data_sync_service.py:129 `is_income = doc.
  document_type in ['invoice','receipt','tax_invoice']` compares SUMIT's
  NUMERIC document_type code against string literals -> always False ->
  every doc miscategorized as a $0 expense with a garbage description.
  This runs on EVERY real sync via run_post_sync_tasks (called from
  cfo_sync.py, office.py, cron.py, admin.py) -- not a one-time artifact,
  actively generating garbage rows in prod right now.
  Did NOT fix the type-comparison bug: per advisor consultation, fixing
  it alone would convert obviously-wrong data (zeros, "Unknown") into
  plausibly-wrong data from a system that still wouldn't reconcile with
  /ledger -- more dangerous, not less. Did NOT purge/retire anything:
  that's destructive to existing prod rows -> stop-rule (א) in the goal
  directive, and whether this Account/Transaction system is abandoned
  cruft or an intended separate cash-basis view is a product-intent
  question code can't answer. ALSO found (not investigated further this
  iteration, flagged for next pass): 10 other services (ai_analytics_
  service, ap_service, ar_service, bank_statement_service, budget_
  service, cost_analysis_service, fees_service, forecasting_service,
  kpi_service, tax_service) import Account/Transaction too -- unknown how
  many actually depend on this broken data path in their live routes.
  Full evidence + recommendation written into PRODUCT_AUDIT_AND_ROADMAP.md
  under "ממצא חדש — שתי מערכות חשבונאות מקבילות". Reported to user for a
  repair/retire/keep-as-cash-view decision before any further action here.

USER DECISION + FIX (2026-07-03): user chose "עצור והשבת מקור הזבל, לא
  לגעת בנתונים קיימים" (stop the garbage source, leave existing data
  alone) out of 4 options (repair the comparison bug / retire+redirect
  /reports / stop the hook only / investigate the other 10 services
  first). Implemented via TDD: RED test
  (test_client_automation_service.py) monkeypatches DataSyncService.
  sync_all to raise if called, confirmed it WAS called (RED, matching the
  real prod behavior) -> removed the "sumit" -> DataSyncService.sync_all()
  block from run_post_sync_tasks (client_automation_service.py) entirely,
  replaced with a comment explaining why -> GREEN. Verified no other code
  reads result["transactions"]/["transactions_error"] from this function
  (the one other "transactions" hit, cfo_brain_service.py:639, is an
  unrelated generic evidence-dict key). 528 passed (517->528, +1 real
  regression test net of the +10 from earlier this session). Full
  qa_gate.py PASSED end-to-end. Deployed to prod (no migration needed --
  no schema change) -> prod_smoke.py 14/14 -> **live-verified the fix
  itself**: recorded transactions row count per org before
  (org1=127,2=23,3=23,4=23,5=23) -> triggered a REAL POST /api/sync/run
  for org 1 via X-Active-Org-Id super-admin override -> sync completed
  successfully (id 474, 5 accounts updated, 10 invoices skipped-as-
  unchanged) -> re-checked row counts: **unchanged (org1 still 127)** --
  confirms the auto-hook no longer fires and no new garbage rows are
  created, while the real sync itself still works fine.
  NOT done (explicitly out of scope per the user's chosen option and the
  advisor's repeated caution against scope creep): the existing 127+23*4
  garbage rows are untouched; /api/reports/balance-sheet and
  /api/reports/profit-loss are still unreliable (still read the same
  Account/Transaction tables, now frozen rather than growing) --
  documented in PRODUCT_AUDIT_AND_ROADMAP.md as still-open; the 10 other
  services that import Account/Transaction were not audited for real
  dependency this iteration. Task #6 in TaskCreate tracks the still-open
  repair/retire decision for /reports itself.

BROWSER VERIFICATION (live prod, real logged-in user): a background fork
  logged in as the real user (Amit Porat, not the smoke-test admin) and
  checked /ar and /documents on cfo-2.vercel.app. /ar: aging tab shows
  real data (245,527 severely overdue); collection-cases tab switches
  cleanly to an empty-state ("אין תיקי גבייה") with working filters and
  the "פתח תיקים" button -- no crash. /documents: real document list
  (credit notes, delivery notes, real amounts/dates) renders; "Create New
  Document" modal opens correctly (type/customer/email/items/SUMIT
  checkbox/total) -- closed without submitting (no real SUMIT writes).
  Console: zero app-level errors on either page (only unrelated MetaMask
  extension warnings). Both of this batch's frontend changes (7.3's
  collection-cases tab, 7.9's document-issuance result screen) are
  confirmed clean against real production data, not just local dev.

TASK #7 (audit: do other services really depend on the broken Account/
  Transaction tables?): audited all 10 services identified earlier via
  precise identifier-usage grep (not just import lines). Result: the
  blast radius is WIDER than the /reports finding alone --
  REAL, active queries against Account/Transaction (not dead imports):
  - ai_analytics_service.py: Transaction grouped by category (90-day
    expense-concentration insight, feeds generate_insights/AI insights).
  - ai_intelligence_agent.py: Account.balance sum for cash_balance.
  - balance_snapshot.py: Account.balance sum -- called from BOTH
    bank_report_service.py AND kpi_service.py (so kpi_service is an
    indirect dependent despite not querying the tables itself).
  - budget_service.py: Transaction date-range filter for budget-vs-actual.
  - cost_analysis_service.py: Transaction grouped by category (EXPENSE).
  - fees_service.py: Transaction amount sum.
  - forecasting_service.py: Transaction grouped by category (cash-flow
    forecast input).
  - tax_service.py: _get_annual_profit_estimate() -> already refactored
    away from directly querying Transaction (good, has an explicit
    comment about why), but now calls FinancialReportsService.
    generate_profit_loss() instead -- which STILL internally reads the
    same broken Account/Transaction tables. Feeds calculate_tax_advance()
    (מקדמות מס), reachable via a real route (financial_management.py ->
    registered in api/__init__.py) but NOT called from any frontend
    component currently -- no live UI surfaces this number today, so real
    user exposure is currently zero, but the number would be wrong if
    anyone did call the endpoint.
  Import-only, NOT actually querying the tables (effectively dead
  imports): ap_service.py, ar_service.py, kpi_service.py (directly --
  though it does depend transitively via balance_snapshot, above).
  NOT fixed this iteration -- this is a large-blast-radius architecture
  question (8-9 features quietly built on the same frozen, mostly-garbage
  dataset), exactly the kind of thing that needs a dedicated repair/retire
  decision rather than a piecemeal fix. Documented for the user; Task #7
  updated with the fuller picture.

RE-VERIFICATION + prod_smoke hardening: a context-compaction gap caused a
  redundant re-run of the Step 11 deploy sequence (vercel --prod, db/migrate,
  schema_drift_check --env-file, prod_smoke.py, browser checks of /ar,
  /documents, /ai-chat) — all confirmed identical to what's already recorded
  above (revision 3a8a9532010b, clean drift, ANTHROPIC_API_KEY still absent).
  One genuinely new gap closed: prod_smoke.py's CRITICAL_PATHS never actually
  included /api/ai/chat/{session_id} or /api/collections/cases despite the
  ledger saying they were "spot-checked live" — that was a one-off curl, not
  a standing regression check. Added both via TDD (RED test in
  test_prod_smoke.py asserting their presence, confirmed it failed against
  the old CRITICAL_PATHS list, then added the two routes, GREEN). Re-ran live:
  16/16. Full suite still 528 passed.
  Also confirmed live in the browser: /ai-chat itself (not just /ar and
  /documents) loads cleanly in prod and sending a real message renders the
  exact clean Hebrew "ANTHROPIC_API_KEY חסר" banner, not a crash — this
  specific check hadn't been recorded before.
  Status unchanged from the entry above: Wave 2 remains open pending the
  user adding ANTHROPIC_API_KEY + a redeploy + a live 9.5 test. Task #1
  (SUMIT doc 1001 / customer 2095660683) and Task #7's wider Account/
  Transaction blast-radius question also remain open.

CONTINUOUS-IMPROVEMENT LOOP — iteration 2: continued gap-mapping per the
  goal directive. Re-checked several previously-flagged roadmap P1/P2 items
  against current code before touching anything -- most turned out already
  fixed or mischaracterized: AR credit_limit=100000 is a real tiered
  credit-score output (200k/100k/50k/0 by score bucket), not a flat
  hardcode; supplier withholding (856) returning empty is intentional
  honest-null (only suppliers with an explicit withholding_rate are
  included); tax_service's company tax_id already loads from
  Organization.tax_id with an honest all-zeros fallback, not "123456789".
  AP's discount_percent=0 hardcode (ap_service.py:564) IS still real but
  low-priority: neither Bill nor Contact has any discount/payment-terms
  column at all, so there's no data source to wire up -- an honest
  placeholder for a feature with no backing data, not a computation bug.
  Left as-is (P2, no action).

  NEW FINDING + FIXED (data correctness, per directive priority (א)):
  grep for random.* across services/ surfaced AdvancedAIService
  (ai_analytics_service.py, live at /ai-analytics) fabricating data in two
  more places beyond the already-known, already-tested illustrative
  recommendations:
  - predict_metric(): computed a "forecast" (trend/confidence-interval/
    scenarios) entirely from random.randint/random.uniform noise
    (_get_metric_history, _get_seasonality_factor) -- looked computed via
    real-looking math, was pure noise every call. Not reachable from any
    current frontend, but a live authenticated GET route.
  - get_ai_analysis(): with no OPENAI_API_KEY, returned canned generic
    Hebrew reassurance text for any question. Worse: even with a key
    configured, since the real frontend (AIAnalyticsDashboard.tsx) never
    sends a context param, it silently fed GPT-4 a 100%-hardcoded fake
    financial context (_prepare_financial_context: revenue_mtd=450000 etc,
    identical for every org) and returned the result as if it were real
    personalized advice.
  Checked for existing tests/decisions before acting (avoided the "delete
  a deliberately-designed feature" mistake): found
  test_ai_recommendations_flagged.py already asserts get_ai_recommendations
  returns is_illustrative=True by design (a documented "Phase 2" decision,
  real data-derived recommendations deferred to "Phase 11"). Left that
  function untouched -- the actual live bug there was that
  AIAnalyticsDashboard.tsx's TS interface didn't even include
  is_illustrative, so a real user saw 5 identical fake ₪-amount
  recommendations (REC-001..005, e.g. "move to cloud accounting" -- from a
  cloud accounting product) with zero indication they were examples, not
  analysis.
  Fix (TDD, 6 new tests in test_ai_analytics_honest_fallbacks.py): added
  AIAnalyticsNotConfiguredError (mirrors AIChatNotConfiguredError exactly)
  + an app-level handler -> clean 400. predict_metric raises it always
  (deleted the two random-noise helper functions). get_ai_analysis raises
  it when no OpenAI key OR no explicit context passed (deleted
  _prepare_financial_context and _get_fallback_analysis entirely -- no
  silent fake-context fallback survives). Frontend: added is_illustrative
  to the AIRecommendation TS interface + a visible amber "לדוגמה בלבד —
  לא מבוסס על נתוני העסק שלך" badge; added the missing onError handler on
  analysisMutation (same gap class as ChatAssistant.tsx's earlier fix --
  neither had error handling, a failed call left the user staring at
  nothing).
  Caught along the way: a REAL OPENAI_API_KEY exists in this local shell's
  environment (not in prod -- confirmed via `vercel env ls production`,
  absent) -- caused one new test to pass for the wrong reason until an
  explicit monkeypatch(openai_api_key=None) was added; a reminder that
  tests must not rely on ambient shell state.
  route_audit baseline moved 39->40 in scripts/qa_gate.py, documented:
  /api/financial/ai/predict/{metric} now correctly returns 400 instead of
  a silently-wrong 200 -- a deliberate, understood addition, not a
  regression. 534 passed, tsc+build clean, qa_gate PASSED. Deployed to
  prod, 16/16 smoke, and live-verified directly: predict_metric -> 400
  "היסטוריית נתונים אמיתית", analyze -> 400 "OPENAI_API_KEY חסר",
  recommendations -> still returns 5 illustrative-flagged examples
  (is_illustrative: true confirmed in the live response).
  NOT investigated further (logged as a next-iteration candidate per
  advisor guidance, not run now): a systematic sweep for the rest of this
  "abandoned-prototype-serving-fake-data-on-a-live-route" class of bug
  across the codebase -- this session has now found two instances
  (Account/Transaction, AdvancedAIService) via targeted grep, not an
  exhaustive search.

CONTINUOUS-IMPROVEMENT LOOP — iteration 3: ran the suggested random.*
  sweep across all of src/cfo/services/ -- confirmed clean (only the
  AdvancedAIService docstring comment matches now, no live random.* calls
  remain anywhere). Investigated kpi_service.py's hardcoded
  comparison_to_budget (500000/400000 fixed targets) and
  comparison_to_previous (8.5%/5.2%/12.3% fixed percentages) in
  get_executive_summary -- traced the underlying data source
  (_get_financial_data -> FinancialReportsService.generate_profit_loss)
  and confirmed this is the SAME already-documented, already-deferred
  Account/Transaction subsystem (a more direct dependency than the
  balance_snapshot-mediated one already listed for kpi_service in the
  Task #7 audit). Per the explicit instruction to avoid re-treading that
  ground, did NOT touch kpi_service.py this iteration -- "fixing" the
  hardcoded comparison values with real math over the same frozen/garbage
  data would just be a second instance of the "plausible-but-wrong is
  worse than obviously-wrong" mistake already avoided once this session.
  Noted in PRODUCT_AUDIT_AND_ROADMAP.md's existing Account/Transaction
  section for whoever eventually makes the repair/retire call.

  Pivoted to a different, safe area per the wakeup prompt's alternative
  suggestion: alert_engine.py had only 3 tests covering 1 of its 6 checks
  (_check_overdue_invoices; the other 2 existing tests cover
  evaluate_all's general resilience, not individual check logic). Added
  12 new tests covering the other 5 checks (bills_due_soon,
  large_transactions, stale_collection_cases, low_cash, spend_spike),
  each with a fires-correctly case and (where meaningful) a
  does-not-fire case. Confirmed _check_low_cash reads Account.balance
  (the cached field kept live by the modern SyncEngine, NOT the broken
  Account/Transaction-derived path) before trusting it as testable real
  logic -- correctly distinct from the already-documented issue.
  Writing the stale-collection-case test surfaced a REAL bug:
  _check_stale_collection_cases compared a naive last_activity_at
  (case.created_at round-tripped through SQLite's DateTime(timezone=True),
  which doesn't actually preserve tz-awareness) against a tz-aware
  cutoff, raising TypeError -- silently caught and logged by the
  per-check isolation wrapper, meaning this check would just stop firing
  with zero visible error. Fixed: normalize a naive last_activity_at to
  UTC before comparing. Also had to fix two of my own test-authoring bugs
  along the way (a day-count vs calendar-month date-boundary sensitivity
  in the spend_spike tests) -- both caught by the tests themselves
  failing for the wrong reason, not by inspection.
  545 passed (up from 534), qa_gate PASSED, deployed to prod, 16/16
  smoke. NOTE: one inaccuracy in commit b364b5a's message -- it claims
  "fixed the alert_engine.py file's own import list" which did not
  happen (only the tz-fix was made to that file); the import-list change
  was in the test file, not the service file. Recorded here since commit
  history isn't being amended for a message-only inaccuracy.

CONTINUOUS-IMPROVEMENT LOOP — iteration 4: followed up on the previous
  iteration's "scan for other silently-swallowed-exception patterns"
  suggestion. cfo_brain_service.py's run_analysis() calls 9 _*_insights()
  generators directly with NO isolation between them (unlike alert_
  engine.evaluate_all(), which already isolates each check via
  _run_check) -- a single generator's exception aborts the entire
  analysis. Since run_post_sync_tasks (client_automation_service.py)
  wraps the WHOLE run_analysis() call in a try/except that just logs and
  continues, this is worse than the alert_engine case: one broken
  generator would silently zero out EVERY insight for an org on every
  subsequent sync, invisibly, org-wide.
  Fix (TDD): RED test monkeypatches _cashflow_insights to raise, confirms
  the current code aborts run_analysis() entirely (no insights at all,
  not even from unrelated generators) -- then added _run_generator(),
  a direct copy of AlertEngine._run_check's isolation pattern, wrapping
  all 9 generator calls + a self.last_run_failures list (mirroring
  AlertEngine's own attribute name/shape exactly, for consistency).
  GREEN: the other 8 generators' insights still come through when one
  fails. 546 passed, qa_gate PASSED, deployed to prod, 16/16 smoke.
  Test coverage for cfo_brain_service.py's individual insight generators
  (8 of 9 still only exercised indirectly via run_analysis, same gap as
  alert_engine had before iteration 3) remains a candidate for a future
  iteration -- not pursued now given time already spent this session.

CONTINUOUS-IMPROVEMENT LOOP — iteration 5: closed the coverage gap flagged
  at the end of iteration 4. Traced each of the 8 remaining insight
  generators' real data source before writing anything (avoided assuming
  they're all entangled with the already-documented Account/Transaction
  issue just because two of them are): reconciliation, collections,
  cashflow, payables, and large-unreconciled-bank all read Invoice/Bill/
  BankTransaction/Account.balance -- real, separate tables, unaffected.
  Only profitability and budget read the legacy Transaction table;
  tested those by seeding Transaction directly, which validates the
  insight decision logic in isolation from the separate "does the real
  sync path populate Transaction correctly" question (already documented,
  not re-opened). Added 14 tests (fires + does-not-fire pairs where
  meaningful). One naming gotcha handled correctly on the first pass:
  _large_unreconciled_bank_insights shares insight_type="reconciliation"
  with _reconciliation_insights but has a distinct fingerprint
  ("reconciliation:large_unmatched_bank_movements") -- checked by
  fingerprint, not type, to isolate it.
  All 18 passed on the first real run -- unlike alert_engine's equivalent
  exercise, no new bug surfaced this time. That's a legitimate outcome:
  these 8 generators' logic checks out as correct. 560 passed (full
  suite), qa_gate PASSED. Test-only change (no service code touched) --
  not deployed, since there's no runtime behavior difference to verify
  live; the already-deployed iteration-4 build is unaffected.

CONTINUOUS-IMPROVEMENT LOOP — iteration 6: attempted the directive's own
  step 2 (live browser walkthrough of SUMIT's office UI at app.sumit.co.il
  vs Rezef's coverage) -- blocked cleanly: needs a real SUMIT login the
  agent doesn't have and must not enter itself (stop-rule ב, missing
  credential only the user can provide). No existing authenticated
  browser tab either. Did not force this; pivoted instead to scanning for
  more instances of the silently-swallowed-exception class already fixed
  twice this session (alert_engine, cfo_brain_service) -- checked
  reconciliation_dispatch.py, sync_engine.py, and expense_ocr_pipeline.py's
  except-Exception blocks specifically. All three turned out to be
  well-designed already: each surfaces per-item failures visibly (status
  fields, error lists, sync_run.error_summary) rather than swallowing them
  silently -- a real, different pattern from the two bugs already found,
  not a third instance of the same one. No new bug found here; logged as
  checked so a future pass doesn't re-scan the same three files.
  Pivoted again to a productive substitute for the blocked live-SUMIT-UI
  check: re-verified SUMIT_MODULE_COVERAGE.md's "Partial" items against
  the already-downloaded swagger spec (same ground-truth method used
  earlier this session for Step 8) instead of a live walkthrough. Found
  concrete, documented API endpoints for 3 of 8 Partial items that were
  previously just vague labels: payment pages (POST /billing/payments/
  beginredirect/ -- generates a hosted payment-page URL given a customer
  + line items, directly useful for the collections workflow: "send a
  payment link" instead of just a balance notice); wallet activation
  (POST /billing/generalbilling/openupayterminal + setupaycredentials --
  Upay card-terminal setup); triggers (POST /triggers/triggers/subscribe
  -- SUMIT's own description says "usually done by make.com/zapier, but
  can also be used directly" -- a real webhook mechanism that could let
  Rezef receive push notifications instead of relying purely on polling
  sync, a potentially higher-value finding than a coverage checkbox).
  None implemented -- documented with exact endpoint names + effort
  estimates in SUMIT_MODULE_COVERAGE.md for whoever picks this up next.
  Remaining Partial items (Masav mandates/returns, outgoing email/domain
  settings, custom dashboards/views builder, file storage quotas) turned
  up nothing under any obvious API terminology -- likely genuinely
  correctly classified, not just unchecked.

CONTINUOUS-IMPROVEMENT LOOP — iteration 7: implemented the highest-value
  item scoped in iteration 6 -- "payment pages" moved from documented-gap
  to built feature. sumit_models.PaymentLinkResponse;
  SumitIntegration.create_payment_link() (POST /billing/payments/
  beginredirect/), reusing the existing _customer_ref/_charge_items
  helpers charge_customer() already uses, for consistency;
  DocumentIssuanceService.create_payment_link(invoice_id) -- org-scoped
  lookup, rejects zero/negative-balance invoices, resolves the customer
  from the linked Contact (falls back to name when no SUMIT external_id
  recorded, matching _customer_ref's own convention); new route POST
  /api/financial/invoices/{invoice_id}/payment-link; frontend button
  ("קישור תשלום") on each AR-aging invoice row in CFOARDashboard.tsx,
  opens the link in a new tab, with a real onError path (not silent).
  10 new tests (3 integration-client via the established fake-transport
  pattern, 4 service/route). 566 passed, qa_gate PASSED including
  tsc+build this time (skipped in recent test-only iterations). Deployed,
  16/16 smoke.
  LIVE VERIFICATION (real org 1, real invoice #13, balance ₪7,500): called
  the new endpoint against production. Result: a clean, structured 502
  ("ההרשאה נדחתה: המודול סליקת אשראי אינו מותקן בעסק" -- this SUMIT
  company's account doesn't have its card-clearing module activated),
  via SumitAPIError's ALREADY-EXISTING app-level handler (not something
  built this iteration -- confirmed present, not a gap). This is a
  genuine positive result, not a failure: it proves the payload reaches
  SUMIT correctly and the real business-rule rejection surfaces cleanly
  instead of leaking a raw exception. Could not verify a successful
  payment-link generation against this org's real account because that
  account itself lacks the prerequisite SUMIT-side activation (matches
  the already-documented "wallet activation" gap item from iteration 6 --
  this company would need to complete SUMIT's own Upay setup first, an
  account-level SUMIT configuration step outside Rezef's control).

CONTINUOUS-IMPROVEMENT LOOP — iteration 8: two items per the wakeup
  prompt's suggestions, both investigate-before-build.
  (1) Triggers webhook: read the Subscribe/Unsubscribe request schemas in
  full ({URL, Folder, View, TriggerType}) and cross-checked what Folder/
  View actually are (/crm/schema/listfolders, /crm/schema/getfolder,
  /crm/views/listviews -- all CRM-module-only). Conclusion: this trigger
  mechanism can only push CRM-entity change notifications, NOT
  invoice/bill/document creation events -- the thing that would actually
  matter for real-time-instead-of-polling sync. This deflates iteration
  6's own optimistic framing ("potentially higher-value than it looks");
  corrected SUMIT_MODULE_COVERAGE.md before anyone builds against the
  wrong assumption. Not pursued -- correctly de-prioritized after
  investigation, not left unchecked.
  (2) Open Finance goal-directive finish line #7 ("activation screen
  ready + instructions for the user"): the screen already existed
  (CFOSyncDashboard.tsx's Client ID/Secret/User ID form) but had zero
  explanatory text. Before writing anything, grepped every
  OPEN_FINANCE_USER_ID usage across the whole codebase to resolve an
  ambiguity in docs/OPEN_FINANCE_API_GUIDE.md (one line suggested userId
  might be Rezef-generated per end-user; another said clientId/
  clientSecret are "provided by Open Finance during onboarding") --
  confirmed from the actual code that all three are read identically
  everywhere (same settings fallback, same per-org credentials dict),
  meaning all three are static business-level credentials from Open
  Finance's own onboarding, not something Rezef drives via an in-app
  consent flow. Added a short, accurate instruction above the form
  (points to the business's own Open Finance onboarding + the already-
  documented official reference URL, not a new/guessed one). Pure
  frontend text change -- 566 passed (full suite unaffected), tsc+build
  clean, deployed, 16/16 smoke.

CONTINUOUS-IMPROVEMENT LOOP — iteration 9: investigated the PCN874 VAT
  export gap (roadmap's own P1 item). Confirmed tax_service.
  _format_shaam_file is a made-up pipe-delimited format, not the real
  Israeli Tax Authority fixed-width standard. Researched via WebSearch +
  WebFetch: real spec exists (S/T sale/purchase markers, 9-digit
  reference-number field, whole-shekel rounding, per multiple third-party
  accounting-vendor sources), but the exact byte-position field layout
  lives only in PDFs this environment can't reliably extract (WebFetch
  returned raw PDF binary/undecodable; the Read tool's PDF-to-image path
  needs poppler, not installed). Deliberately did NOT guess at exact
  field widths and ship a fixed-width-shaped-but-wrong file -- for a real
  government tax submission, a plausible-looking-but-wrong format is
  worse than the current obviously-not-official placeholder (nobody
  would mistake pipe-delimited text for an official file and actually
  submit it; a subtly-wrong fixed-width file might be). Documented the
  research + what's needed to finish properly (poppler + careful
  transcription, or a more machine-readable spec source) in
  PRODUCT_AUDIT_AND_ROADMAP.md. No code changed -- nothing to deploy.

CONTINUOUS-IMPROVEMENT LOOP — iteration 10: rather than leave PCN874
  deferred indefinitely, installed poppler (`brew install poppler`) to
  properly unblock the PDF-reading path flagged as the blocker last
  iteration, then re-attempted the research. The two vendor PDFs
  (rivhit.co.il, h-erp.co.il) turned out to be user-guides for their own
  software UI, not the byte-level spec -- confirmed by actually reading
  them page-by-page after the poppler fix, not just assuming. Followed a
  citation trail from the h-erp guide to a real gov.il URL
  (tax-vat-online-invoice-reporting), which itself 403'd via WebFetch,
  but a targeted site:gov.il search surfaced the actual official Tax
  Authority PDF for "מבנה אחיד" (Service_Pages_Income_tax_horaot-131.pdf,
  Computerized Audit Department, v1.31/2009) -- read successfully with
  real, precise field tables (field number/type/length/start-end column
  for every field in every record type).
  IMPORTANT CORRECTION discovered in the process: "PCN874" and "מבנה
  אחיד" are NOT the same specification, despite the roadmap doc's own
  wording treating them as one ("PCN874 (מבנה אחיד)"). מבנה אחיד is a
  separate, broader general-ledger/audit-trail export (produced on
  demand during a tax audit; record types A100/Z900/C100/D110/D120/
  B100/B110/M100) -- not the periodic online VAT summary file PCN874
  actually is. Corrected this in PRODUCT_AUDIT_AND_ROADMAP.md before
  anyone builds the wrong one thinking it satisfies both requirements.
  The real מבנה-אחיד spec is now verified and its source URL documented
  for a future implementer (not committed to the repo -- *.pdf is
  git-ignored project-wide, deliberately not overridden). PCN874's own
  specific byte-spec is STILL not located in a machine-readable source
  -- both remain correctly unimplemented, neither guessed at. This
  closes out the PCN874 investigation thread for this session: real
  research invested, a genuine and useful correction made, two distinct
  well-scoped future features identified, nothing rushed.
