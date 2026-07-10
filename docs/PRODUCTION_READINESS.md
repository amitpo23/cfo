# CFO Production Readiness Goal

## Goal

Run the CFO system in production on Vercel with a persistent Postgres
database, live SUMIT integration, gated Open Finance integration, and working
financial workflows for cash flow, profit and loss, balance sheet, bank
reconciliation, categories, and office/client management.

## Current Readiness Snapshot

- Vercel project: `cfo-2`
- Live site responds at `https://cfo-2.vercel.app`
- Local backend/frontend tests pass
- Production `DATABASE_URL` is configured, persistent, and reachable
- SUMIT production credentials are configured and ping successfully
- Open Finance is not testable until `OPEN_FINANCE_USER_ID` is configured
- Production Vercel env has been populated for SUMIT, security, CORS,
  persistent DB, and Open Finance client credentials where values existed
- `OPEN_FINANCE_USER_ID` and Google OAuth client IDs must be supplied before
  those login/integration paths can be live-tested
- SUMIT write-back verified live (2026-07-03): quote document created (ID
  2095660684, number 1001, ₪1 symbolic), PDF downloaded successfully (83034
  bytes). **Cancellation failed** ("Cancelling this document isn't allowed") —
  quotes may need a different cancel/delete path than invoices; document
  1001 still open in SUMIT pending manual cancellation and investigation
  (tracked as a follow-up task).
- Schema drift check against Neon production (2026-07-03): OK, no drift
  (checked both before and after the Epic 1 stability deploy below).
- **Epic 1 (stability) deployed to production 2026-07-03.** Sequence: full
  suite green (457) -> `vercel deploy` (preview) -> preview smoke blocked by
  Vercel Deployment Protection (no automation bypass secret configured; not
  a code defect — see route-audit doc) -> `vercel deploy --prod` (aliased to
  `cfo-2.vercel.app`) -> `POST /api/admin/db/migrate` (`upgraded`, no pending
  columns/tables) -> live `prod_smoke.py`: **14/14 OK**. First live run was
  13/14 (one 422 on `/api/daily-reports/vat`, a required-query-param gap in
  the smoke script itself, fixed in the same iteration) — confirms the
  earlier 403s were purely due to the 3-day-stale deploy, now resolved.
- **Wave 2 (Epic 1 completion sprint) deployed to production 2026-07-03.**
  Adds: real COGS/liquidity/payroll calculations, alert isolation, expense
  `deduction_percent`, collection-case worklist (backend + AR dashboard tab),
  document-issuance SUMIT API gaps (scheduled-document cloning, cash/cheque
  payment forwarding, credit-note linking via `OriginalDocumentID`), an
  AI chat assistant with a server-enforced write-confirmation gate, and
  `scripts/qa_gate.py` as a consolidated pre-deploy gate. Sequence: full
  suite green (527) -> real end-to-end `qa_gate.py` run, all 6 automated
  sections PASS -> `vercel --prod --yes` (aliased to `cfo-2.vercel.app`) ->
  `POST /api/admin/db/migrate` -> `{"action":"upgraded","current_revision":
  "3a8a9532010b","schema_sync":{"tables":[],"columns":{}}}` (only the new
  `ai_chat_messages` migration needed applying) -> `schema_drift_check.py`
  against Neon: clean -> `prod_smoke.py` **14/14** -> spot-checked
  `GET /api/ai/chat/{session_id}` (200, empty history) and
  `GET /api/collections/cases` (200, empty list) live -> confirmed
  `POST /api/ai/chat` returns a clean 400 (not a 500) while
  `ANTHROPIC_API_KEY` is unset.
  **Update 2026-07-04**: `ANTHROPIC_API_KEY` was added and a redeploy done.
  The first live chat request confirmed the key is valid and correctly
  wired (a real request reached `api.anthropic.com` and got a structured
  response) — but the Anthropic account itself has no credit balance
  ("Your credit balance is too low to access the Anthropic API"). This is
  a billing gap on the Anthropic account, not a code issue. Fixed a real
  code gap this surfaced: the SDK's `anthropic.APIError` wasn't caught,
  leaking a raw 500 — now maps to a clean 503 (`AIChatUpstreamError`).
  **Still not complete**: once credit is added at console.anthropic.com,
  the same two live tests (one read-only query, one write-with-confirmation
  action) still need to run before Wave 2's chatbot piece is verified
  end-to-end.
  **Update 2026-07-04 (continuation directive)**: all other Wave 2 items
  (stages 7-11) are code-complete — verified via direct re-inspection, not
  just re-reading prior notes. A live SUMIT data-parity check (org 1) found
  and fixed a real P0 bug (customer identity sync, see `.superpowers/sdd/
  progress.md`'s "WAVE 2 CONTINUATION DIRECTIVE" entry and `docs/audits/
  2026-07-04-data-parity-sumit.md`) and closed the last open item, 7.8's
  UI-surfacing half. 635 tests passing, qa_gate green, deployed and
  smoke-tested throughout.

## Required Production Environment Variables

Set these in Vercel Production:

```env
DATABASE_URL=postgresql+psycopg://...
JWT_SECRET_KEY=...
CREDENTIALS_ENCRYPTION_KEY=...
REGISTRATION_SECRET=...
CRON_SECRET=...
CORS_ALLOWED_ORIGINS=https://cfo-2.vercel.app
OPEN_FINANCE_CLIENT_ID=...
OPEN_FINANCE_CLIENT_SECRET=...
OPEN_FINANCE_USER_ID=...
OPEN_FINANCE_WEBHOOK_SECRET=...
SUMIT_API_KEY=...
SUMIT_COMPANY_ID=...
APP_URL=https://cfo-2.vercel.app
GOOGLE_CLIENT_ID=...
VITE_GOOGLE_CLIENT_ID=...
ANTHROPIC_API_KEY=...   # required for the AI chat assistant (/api/ai/chat); without it the route returns a clean 400
```

## Deployment Checklist

1. Keep `DATABASE_URL` pointed at the persistent managed Postgres database.
2. Add the remaining Open Finance variable: `OPEN_FINANCE_USER_ID`.
3. Add Google OAuth client IDs if Google Sign-In should appear in the UI.
4. Add separate strong secrets for JWT, credential encryption, cron, registration,
   and Open Finance webhook verification.
5. Run Alembic migrations against the production database.
6. Deploy the current branch to Vercel.
7. Verify:
   - `/api/health`
   - login/register flow
   - SUMIT sync/read endpoints
   - Open Finance token ping and connections
   - profit/loss report
   - balance sheet
   - cash-flow statement and projection
   - ledger trial balance
   - bank reconciliation suggestions
   - expense category controls

## Notes

- The derived ledger, annual reports, and daily reports are automatic drafts
  derived from synced data. They are not a replacement for SUMIT's official
  books and must remain clearly labeled as draft/derived.
- Bank reconciliation now has an explicit hub boundary: Open Finance matches
  are persisted locally, then tracked as SUMIT dispatch `not_sent`,
  `confirmed`, `failed`, or `unsupported`. If the connector has no real SUMIT
  write-back endpoint, the system says so instead of pretending it posted.
- The live deployment observed before this checklist was still an older build
  and had wildcard CORS headers.
- Google Sign-In is implemented as `/api/admin/auth/google` using Google
  `tokeninfo` verification. The UI shows the button only when
  `VITE_GOOGLE_CLIENT_ID` is configured.
- Tenant separation is organization-based inside one database. Each
  self-registered user gets a separate organization and can store its own
  encrypted SUMIT/Open Finance credentials. The app does not currently create a
  separate physical database per user.
