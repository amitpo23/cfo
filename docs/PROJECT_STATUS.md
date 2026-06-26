# CFO Platform — Project Status & Gap Review

**Updated:** 2026-06-26 · **Branch:** `feat/sumit-ar-ap-documents-ocr` · **Scale:** 74 services · 33 route modules · 64 test files · 19 migrations.

This is the single entry point for "what exists, what's done, what's open". Every status below was verified against current code (not the unreliable multi-agent audit — see `PHASE13_VERIFIED_BUG_SCAN.md`).

---

## 1. What this platform is
An Israeli-market CFO platform on FastAPI + SQLAlchemy: AR/AP, P&L, cash-flow + forecasting, double-entry ledger, balance sheet, VAT/PCN874, Masav bank files, expense OCR + filing (SUMIT), Open Finance bank ingestion, payroll, tax drafts (1301/1214/856), ~40 dashboards, and now automated collection reminders. Frontend in `frontend/` (React).

## 2. Capability status (verified)
| Area | Status | Note |
|------|--------|------|
| AR / AP aging | 🟢 real | `ar_ap_aging`/`ar_service`; cashflow-aging now delegates to real (was zeros) |
| P&L (daily/monthly) | 🟢 real | `daily_reports_service`; dashboard COGS now honest-null (no fabricated 30%) |
| Cash flow + forecast | 🟢 real | `forecasting_service` (5 methods); `forecasting_advanced` now delegates (was hardcoded) |
| Double-entry ledger + balance sheet | 🟢 real | opening balances supported; Σdebit=Σcredit invariant tested |
| VAT / PCN874 | 🟡 draft | `vat_utils` split; PCN874 generator = draft pending Tax-Authority spec |
| Masav bank files | 🟢 real | 128-char format |
| Expense OCR + filing | 🟢 real | getpdf→vision→ח.פ→classify→file |
| Open Finance (bank) | 🟡 gated | client ~84 methods; **blocked on `OPEN_FINANCE_USER_ID` + consent** |
| Payroll | 🟢 real | income tax/BL/health/pension/credits |
| Tax (1301/1214/856) | 🟡 draft | drafts + disclaimers; Form 6111 not built |
| Analytics (revenue/expense/BI) | 🟢 real | Phase 13 column bugs fixed this session |
| Collection reminders (SMS/email) | 🟢 built | **opt-in + SMTP env gated** — see §4 |
| revenue by category / region | ⚪ unsupported | explicit (no schema field); product decision to defer |

## 3. This session's deliverables (commits on the branch)
1. **Phase-13 data-integrity fixes** (`e8ccf0f`): `forecasting_advanced` (was 100% hardcoded, live), `analytics_reporting` (16 non-existent column refs → crash), `revenue_analytics`/`expense_analytics` (same column bug), `expense_intake_email` import. + `PHASE13_VERIFIED_BUG_SCAN.md`.
2. **Collection reminders feature** (8 TDD tasks + 3 review fixes): model, opt-in, plan/dispatch, SMTP, cron, manual routes, vercel cron. Plan: `superpowers/plans/2026-06-25-collection-reminders.md`.
3. **Completion sprint — Epic 1 done** (4 fixes): removed every fabricated value (cashflow-aging zeros, dashboard COGS 30%, AI placeholder, `average_days_to_payment:30`, gross-profit 70%). Plan: `superpowers/plans/2026-06-26-completion-sprint.md`.

## 4. Open items / gaps (by priority)
**P0 — production blockers (user/env action, not code):**
- Open Finance: set `OPEN_FINANCE_USER_ID` + run consent journey.
- Verify SUMIT write-back (invoice/receipt round-trip).
- Deploy secrets: `DATABASE_URL`, Google OAuth, cron secret, **SMTP** (for collection email).
- **Merge `feat/sumit-ar-ap-documents-ocr` → main** — Vercel only sees main (cron + features invisible until merged).

**Sprint — Epic 1/2/4 COMPLETE (2026-06-26):**
- ✅ Epic 1 — every fabricated value removed (+ fixed a 500 the new tests surfaced).
- ✅ Epic 2 — de-vacuous analytics tests, `scripts/colscan.py` CI guard, AlertEngine/CFOBrain coverage.
- ✅ Epic 4 — verification gate passed: 401 tests · colscan clean · zero fabricated-value/status-in-list greps · audit_routes 39 fails all env-gated (SUMIT/OF), 0 code bugs, all `/api/analytics/*` = 200.

**Deferred (decided):** revenue by category (could derive from `Invoice.line_items`) / region (needs `Contact` geo fields) — kept "unsupported"; Form 6111; late-payment interest (Prime+2%); legal escalation (demand letters / small claims).

## 5. Where everything lives
- **Status & gaps:** this file.
- **Verified bug scan + audit-reliability lesson:** `docs/PHASE13_VERIFIED_BUG_SCAN.md`.
- **Roadmap (all remaining work):** `docs/superpowers/plans/2026-06-25-product-completion-roadmap.md`.
- **Plans:** `docs/superpowers/plans/` (collection-reminders, completion-sprint, prior buildouts).
- **Production readiness / integration guides:** `docs/PRODUCTION_READINESS.md`, `SUMIT_INTEGRATION_GUIDE.md`, `OPEN_FINANCE_API_GUIDE.md`.
- **Persistent memory (cross-session):** `~/.claude/projects/-Users-mymac-coding-cfo/memory/` (indexed in `MEMORY.md`).

## 6. Verification (run before declaring done / merging)
```
python -m pytest tests/ -q                 # full suite (384+ green)
python scripts/colscan.py                   # no bad column refs (after Epic 2 T2.2)
grep -rn "status_code in \[" tests/         # should be empty (after Epic 2 T2.1)
python scripts/audit_routes.py              # no non-env-gated 500s
```
