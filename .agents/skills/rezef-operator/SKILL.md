---
name: rezef-operator
description: Route Rezef CFO and Israeli-bookkeeping work to the repository's canonical knowledge, capability contract, daily workflows, safety gates, and active execution plan. Use for SUMIT, Open Finance, expenses, double-entry bookkeeping, bank reconciliation, AR/AP, collections, VAT filings, financial reports, CFO analysis, project planning, or capability-status questions in the cfo repository.
---

# Rezef Operator

Use Rezef's versioned sources of truth. Do not answer from a generic finance
skill, a session memory, or an old plan when the repository has a canonical
source.

## Start

1. Read `AGENTS.md` and `CLAUDE.md`.
2. Read `docs/rezef_capabilities.json`.
3. Select the capability that owns the request. Report its `status`,
   `honest_boundary`, and mandatory `gates` before claiming it works.
4. Read `docs/REZEF_OPERATING_SYSTEM.md` for stable ownership and workflow
   contracts.
5. Read `docs/MASTER_EXECUTION_PLAN.md` only for current gate/status.

For bookkeeping or tax work, also read `docs/bookkeeper_kb/README.md` and the
references it routes to.

## Route by domain

- SUMIT API/portal: `docs/SUMIT_KNOWLEDGE_BASE.md`,
  `docs/SUMIT_API_REFERENCE.md`, then the captured Swagger.
- Open Finance: `docs/OPEN_FINANCE_KNOWLEDGE_BASE.md`,
  `docs/OPEN_FINANCE_API_REFERENCE.md`, and provider coverage.
- Daily/monthly bookkeeping: `docs/BOOKKEEPER_ARMY_OPERATING_MODEL.md`.
- Tax classification/VAT evidence: `docs/bookkeeper_kb/README.md`; change
  executable rules only in `src/cfo/services/israeli_tax_rules.py`.
- Capability or architecture question: `docs/rezef_capabilities.json` and
  `docs/REZEF_OPERATING_SYSTEM.md`.
- Implementation priority: the active gate in `docs/MASTER_EXECUTION_PLAN.md`.

## Work in this order

1. Identify the source of truth, organization, period and `as_of`.
2. Verify source freshness and completeness.
3. Use existing normalized models and services; do not create a parallel data
   plane.
4. Preserve evidence lineage and idempotency.
5. Send ambiguity to a decision queue with a reason.
6. For code changes, write a failing offline test first.
7. Update the capability contract only when code and tests prove the new
   boundary.

## Hard boundaries

- Never bypass daily SUMIT/Open Finance budgets or trigger sync from a screen
  refresh or chat question.
- Never perform live provider or production calls unless the owner explicitly
  authorizes a separately guarded operation and repository policy permits it.
- Never treat the derived Rezef ledger as official SUMIT books.
- Never turn missing data into zero, a mock, a default forecast, or a success.
- Never file, pay, close a batch/period, delete a posted entry, or escalate
  collection without the required professional and owner approval.
- Every regulatory output requires the repository's triple-verification flow.

Generic Israeli bank, VAT, bookkeeping, payment or reporting skills may offer
technique, but they cannot override Rezef's knowledge bases, manifest, coded tax
rules, or active plan.
