# Sprint: Data-Integrity Completion & Test Hardening

**Sprint goal:** Bring the platform to a verified, no-fabricated-data state and harden the test suite so CI actually catches the class of bug the audit missed. Every fix is TDD; the sprint ends only when a verification gate passes.

**Branch:** `feat/sumit-ar-ap-documents-ocr` (frequent commits; no merge to main without the user).

**Grounding:** every item below was verified against current code on 2026-06-26 (not the stale 19/6 roadmap, not the unreliable multi-agent audit). Baseline now: 384 tests pass; `colscan.py` clean; one vacuous-test file; 5 confirmed fabricated-value sites.

**Definition of Done (sprint-level):**
- Zero fabricated values served to users (Epic 1 closed or each remaining one explicitly labeled `estimated`/`unsupported` with disclaimer).
- `python -m pytest tests/ -q` green; no vacuous `status_code in [...]` assertions remain.
- `colscan.py` clean and wired into CI.
- `scripts/audit_routes.py` reviewed; no 500s except env-gated (SUMIT/OF).
- `docs/PHASE13_VERIFIED_BUG_SCAN.md` updated to "all code-closable items closed".

---

## Epic 1 — Eliminate fabricated values (Group B + estimates) — VERIFIED, highest priority

### T1.1 — `cash_flow_service` AR/AP aging stubs return all zeros
**Files:** `src/cfo/services/cash_flow_service.py:400-432` (`get_receivables_aging`, `get_payables_aging`); routed at `src/cfo/api/routes/cashflow.py:314,329`.
**Problem:** both return hardcoded zeros (`# TODO`), so `/cashflow/receivables-aging` and `/payables-aging` serve empty data while real aging exists in `ar_ap_aging.py` / `ar_service.py`.
**Fix:** delegate to the real aging service (prefer `ar_ap_aging.py`; confirm its bucket shape and adapt to the route's expected keys `current/days_30_60/days_60_90/over_90/total`). Do NOT invent a third aging implementation.
**TDD:** seed overdue invoices/bills → assert the route returns non-zero buckets matching the seeded amounts. RED first (current zeros).
**Acceptance:** seeded data appears in the aging buckets; numbers reconcile with `ar_service.get_aging_report`.

### T1.2 — `dashboard_service:380` fabricated COGS (`expenses * 0.3`)
**Files:** `src/cfo/services/dashboard_service.py:375-382`.
**Problem:** `cogs = expenses * 0.3` is an arbitrary 30% feeding `gross_profit`/`opex` on a dashboard.
**Fix (decision in T-DEC-1):** either (a) derive COGS from expense categories tagged as cost-of-sales, or (b) stop fabricating — set `cogs=None`, present operating profit (revenue − total expenses), and add `cogs_available: false`. Default recommendation: (b) until a COGS category mapping exists.
**TDD:** seed expenses → assert response has no fabricated 30%; gross/operating figures derive from real totals.
**Acceptance:** no `* 0.3` in the path; dashboard shows honest profit with a clear flag.

### T1.3 — `ai_intelligence_agent:262` fake fallback string
**Files:** `src/cfo/services/ai_intelligence_agent.py:255-262`.
**Problem:** the else-branch returns literal `"...[Analysis would be provided here]"`.
**Fix:** return an honest "insufficient data to answer that" message (or a real derived summary if the data supports it). Never a placeholder.
**TDD:** call the agent with an unmatched question → assert the response is the honest fallback, not the placeholder string.
**Acceptance:** the placeholder string does not exist anywhere in the codebase (`grep` clean).

### T1.4 — `revenue_analytics` hardcoded estimates
**Files:** `src/cfo/services/revenue_analytics.py:175` (`gross_profit_estimate = revenue*0.7`), `:290` (`average_days_to_payment: 30`), `:205` (`estimated_growth = revenue*0.3`).
**Fix:**
- `average_days_to_payment`: compute from real `Payment` records (issue→payment days); fall back to `None` when no payments (not 30).
- `gross_profit_estimate` / `estimated_growth`: these are *labeled* heuristics. Keep them ONLY if the field name and an accompanying `is_estimate: true` make the heuristic explicit; otherwise remove. Decision in T-DEC-1.
**TDD:** seed payments → `average_days_to_payment` reflects them; with none → `None`.
**Acceptance:** no unlabeled fabricated number reaches the user.

### T-DEC-1 (decision, user) — for T1.2/T1.4: prefer "honest null + label" over "labeled estimate"? Confirm before implementing those two.

---

## Epic 2 — Test hardening ("test everything") — VERIFIED need

### T2.1 — Replace vacuous tests in `tests/test_phase13_analytics.py`
**Problem:** assertions of the form `assert resp.status_code in [200, 401, 403]` pass even when the endpoint 500s-then-401s or returns wrong data — this is exactly what hid the Phase-13 column bugs.
**Fix:** rewrite each as an authenticated test (use the `owner`/`fresh_org` fixtures) that seeds data and asserts real response shape + derived values. Where an endpoint needs SUMIT/OF, assert a clean 400/503, not "in [200,401,403]".
**Acceptance:** `grep -rn "status_code in \[" tests/` returns nothing; the file's tests assert behavior.

### T2.2 — Wire `colscan.py` into CI as a guard
**Problem:** the wrong-column class of bug (`total_amount` vs `total`) passed CI because nothing checks model attributes statically.
**Fix:** move `scratchpad/colscan.py` to `scripts/colscan.py`, make it exit non-zero on any real bad ref (whitelist the `Payment.status` comment FP), and add a test `tests/test_no_bad_column_refs.py` that runs it and asserts exit 0. (Optionally add to the CI workflow.)
**Acceptance:** introducing a `Model.nonexistent` ref fails the test.

### T2.3 — Coverage for untested critical services
**Problem (from audit):** `alert_engine` and `cfo_brain_service` have no dedicated tests.
**Fix:** add at least one seed-and-assert behavior test each (e.g. alert fires on low cash; cfo_brain returns a derived insight on seeded data). Keep scope to one meaningful test per service.
**Acceptance:** both services have a passing behavior test.

---

## Epic 3 — Schema-gap resolution (revenue category/region) — VERIFIED, needs decision

### T3.1 — revenue-by-category (currently "unsupported")
**Decision (T-DEC-2):** implement by deriving category from `Invoice.line_items` (JSON) OR keep "unsupported". If implement: add `analyze_revenue_by_category` real impl + TDD (seed invoices with line_items categories → grouped revenue).

### T3.2 — revenue-by-region (currently "unsupported")
**Decision (T-DEC-2):** add geographic fields to `Contact` (migration) + populate, OR keep "unsupported". Adding fields is a product call (where does geo data come from?). Default: keep "unsupported" until a data source exists.

---

## Epic 4 — Verification & sign-off gate (run after Epics 1-3)

Run, in order, and record outputs in `docs/PHASE13_VERIFIED_BUG_SCAN.md` (Resolution section):
1. `python -m pytest tests/ -q` → all green.
2. `python scripts/colscan.py` → clean.
3. `grep -rnE "expenses \* 0.3|Analysis would be provided here|average_days_to_payment.*: 30|TODO: לממש"` over `src/cfo/services/` → no hits (or each remaining is explicitly labeled).
4. `python scripts/audit_routes.py` → no non-env-gated 500s.
5. Smoke: launch the app, hit the previously-broken analytics + cashflow-aging + dashboard endpoints with a seeded org; confirm non-fabricated values.
**Acceptance:** all five pass; sprint DoD met.

---

## Epic 5 — P0 production blockers (spikes; mostly user/env action) — track, don't block code work

These cannot be closed by code alone — schedule as spikes with the user:
1. **Open Finance live** — set `OPEN_FINANCE_USER_ID` + run the consent journey. Unblocks bank flow + amount-sign item. (Owner: user + 1 dev day wiring/verify.)
2. **SUMIT write-back verification** — confirm invoice/receipt creation round-trips to SUMIT. (Owner: dev, needs live SUMIT.)
3. **Deploy secrets** — `DATABASE_URL`, Google OAuth, cron secret, SMTP for collections. (Owner: user.)
**Acceptance:** each either closed or explicitly parked with a written blocker.

---

## Suggested sequence
1. Epic 1 (T1.1 → T1.4) — removes live fabricated data. ⟵ start here.
2. Epic 2 (T2.1 → T2.3) — locks the gains so they can't regress.
3. Epic 3 — only after T-DEC-2.
4. Epic 4 — the gate.
5. Epic 5 — in parallel with the user, as a spike.

Estimated code-closable scope: Epics 1-2-4 ≈ a focused sprint; Epic 3 depends on decisions; Epic 5 is user-gated.
