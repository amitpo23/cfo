# BDO demo P0s: status

Branch `feat/bdo-demo-p0`, draft PR #104. Not merged. No prod migration, no prod writes, no SUMIT or Financy calls, no flag flipped.
This file contains no client figures. Every test uses made-up amounts.

## Round 1 (spec of 04.11)

| # | P0 | Status | Where |
|---|---|---|---|
| 1 | One October P&L on every screen | **Done.** Dashboard, /dashboard/pnl, /daily-reports, /pnl, /budget, the executive and the bank report all read `period_compare.books_months` (/cashflow/period books). Bill/Expense twins count once. If /pnl withholds a profit, every screen withholds it. | c7c13b7, b10ff59, `tests/test_bdo_one_pnl_source.py`, `tests/test_bdo_reports_one_pnl.py` |
| 2 | "Bank until · books until" banner | **Done** on the dashboard, /cashflow, /forecasting, the executive and the bank report (`org_partial_banner`). A missing stamp shows חסר. | 9c1de16, 82fa07c, `tests/test_live_forecast_service.py` |
| 3 | Balance / limit / used / available / overrun | **Done** on the dashboard, /cashflow, the executive and the bank report. All four use `credit_lines`, the last booked balance. A stale balance keeps its amount and shows its date. An overrun is red. | e8adbd8, 9c1de16, 82fa07c, `tests/test_bdo_credit_lines.py`, `tests/test_bdo_balances_everywhere.py` |
| 4 | 30-day forecast: outflows not 0, cheque discounting and loans count as financing | **Done** on /cashflow and the dashboard. Both read the 13-week forecast (loans, payroll, cards, VAT, run-rate). An unknown side shows חסר. | 49819a1, 9c1de16, `tests/test_bdo_cashflow_one_forecast.py` |
| 8 | Hide EXPIRED OF connections | **Done.** Expired consents with no accounts are left out of the status, the list and the provider count. | 04d4d1f, `tests/test_open_finance_routes.py` |
| 5 | A budget placeholder shows חסר | Not touched in this branch. `budget_fill` placeholder_warning is already on main and needs a visual check. | — |
| 6 | PR #103 bank match | Out of scope. It is handled on its own branch. | — |
| 7 | Issuing a document = preview only | **Left.** Don't press "הפק" in the demo. | — |
| 9 | /d/eliav share link | **Left.** It needs a logged-in owner to issue a new link. | — |

## Round 2 (CFO prod walkthrough)

| # | Finding | Status |
|---|---|---|
| 1 | Bank report margin 100× too high; net profit with 3 decimals | **Done.** The margin arrives as a percent and is no longer multiplied again. The Excel export writes it as a fraction. Amounts are rounded to whole shekels. (b10ff59) |
| 2 | Executive and bank report profit differ from /pnl | **Done.** Both use `books_pnl_summary` over the same range, so a profit /pnl calls undeterminable is חסר here too. Gross and operating profit can't be separated in the books, so they show חסר instead of a copy of the net. (b10ff59) |
| 3 | /cashflow and /forecasting disagree | **Partly.** /cashflow and the dashboard read the 13-week forecast. /forecasting is still the open-documents monthly view (`LiveForecastService`). It now says so and links to /cashflow. **Keep /forecasting out of the demo.** (78e691b) |
| 4 | Checking balance missing or 0 while diagnostics show an overdrawn stale balance | **Done** on the dashboard, /cashflow, the executive and the bank report: last booked balance, date, limit, used, available and overrun. On /cashflow, when today's balance is unknown the opening card shows the last booked balance with its date, and the forecast closing stays חסר. (82fa07c, 78e691b) |
| 5 | Budget variance 100% when actual = 0 | **Done.** With no actual, the variance shows חסר, with a reason, in the total and per category. (b10ff59) |
| 6 | Executive loads in ~10s | **Partly.** Insights are computed once instead of twice. Each panel returns `elapsed_ms`. Locally every panel is under 10 ms, so the prod slowness comes from data volume, and one read-only GET of `/api/dashboard/executive` on prod will show which panel is slow. No paid call was found: `generate_insights` is local, and OpenAI is used only by `get_ai_analysis`, which this screen doesn't call. (31a077d) |
| 7 | One org's books are empty because its SUMIT sync never ran | **Diagnosed, not fixed** (needs GO). See below. |
| 8 | Executive and bank report show 0 instead of חסר | **Done.** Missing amounts, ratios and percents show חסר on screen and in the bank Excel. The Excel also carries the checking lines and loans, reads the net bank flow from the right key (it used to write 0), and can't start a formula from an account name. (b10ff59, 809948b, 0f8c96e) |
| 9 | Loans tile mixed with the credit line | **Done.** Loans are a separate figure, labelled "הלוואות (יתרה, בנפרד מהמסגרת)". The credit line is in the credit-lines table. (82fa07c) |
| 10 | /cashflow opening/closing 0 and net 0 in weeks with inflows | **Done.** The old screen used `fmt(0)` on missing values. The new /cashflow shows חסר for an unknown opening or closing, and a week with nothing known on either side has net חסר, not ₪0. (9c1de16, 78e691b) |
| 11 | Command Center bank 0/0 for the current month | **Done.** A month with no bank rows is חסר, not 0/0. (82fa07c) |
| 12 | Prod bank data a week behind Financy | **Diagnosed. Code: an expired stored connection is now a named skip** (809948b). The data itself still needs GO. See below. |

## Diagnosis: books (7) and bank (12). Code reading only, nothing called.

### (12) Bank rows stop in late October

What the code does (`src/cfo/api/routes/cron.py::scheduled_sync_open_finance`):
- Since the owner decision of 23.10, the 02:00 cron syncs nothing unless `OPEN_FINANCE_SCHEDULED_SYNC_ENABLED` is on. Since 26.10, `OPEN_FINANCE_SCHEDULED_SYNC_ORG_IDS` can name orgs that are synced anyway. **Any org not on that list has had no automatic bank sync since 23.10.** That matches data ending 26–28.10.
- The cron sync **does not trigger a Financy refresh.** It only reads what Financy already holds: one accounts list plus the transactions list, paged, per org (`OpenFinanceConnector.fetch_accounts` / `fetch_bank_transactions`). Financy already has data to 3–4.11, so one read would bring it in.
- The read covers only the org's stored `connection_id` (inside the encrypted `integration_connections.credentials_encrypted`, `sync_engine.get_connector_for_org`). When a consent expires and the bank is reconnected, Financy issues a new connection id. If the stored id is the expired one, the sync returns nothing newer than the expiry. The six expired consents that P0-8 hides are what this looks like.
- **Code fix (809948b):** `_of_consent_gate` used to pass if *any* of the org's connections was ACTIVE. It now returns `skipped: stored_connection_not_active` when the stored connection is expired and a newer one is ACTIVE, so the next cron result names the cause instead of the feed going stale silently. Tests: `tests/test_bdo_of_stored_connection_gate.py`.

To confirm on prod (read-only, owner runs or approves):
1. `/admin/cost-protection-status` or `vercel env ls`: which org ids are in `OPEN_FINANCE_SCHEDULED_SYNC_ORG_IDS`, and whether `OPEN_FINANCE_SCHEDULED_SYNC_ENABLED` is set. An old Vercel CLI shows encrypted values as empty, so the admin route is safer.
2. `SELECT organization_id, connection_id, status, expiry_date, last_refresh_at FROM bank_connections WHERE source='open_finance' ORDER BY organization_id;` shows which consents are ACTIVE and which EXPIRED. The stored id is encrypted, so compare it through the cron result after this branch is deployed (`stored_connection_not_active`), or through an admin decrypt.
3. `SELECT organization_id, entity_type, last_success_at, cooldown_until FROM sync_checkpoints WHERE source='open_finance' ORDER BY organization_id;` gives each org's last success and any cooldown.

Fix after GO:
- Point each org's stored `connection_id` at its ACTIVE Financy connection (the bind flow in `bank_coverage.py` writes `connection_id` + `of_connection_ids`). This is a prod write.
- Then one manual sync per org, or add the org to `OPEN_FINANCE_SCHEDULED_SYNC_ORG_IDS`. Each sync costs list calls only (1 accounts call plus one transactions call per page; the number of pages depends on the rows since the last sync), no refresh credit, and stays inside the 20h gate. Do not use refresh-all (`I_CONFIRM_OPEN_FINANCE_REFRESH_20_CREDITS`). Financy already has the data.

### (7) One org's books are empty

What the code does:
- The daily SUMIT sync cron was removed (PR #38). The only automatic pull left is `/cron/sumit-weekly-pull` (Sunday 03:00 UTC), and it does nothing while `SUMIT_WEEKLY_PULL_ENABLED` is off (the default).
- Even with it on, an org is a target only if it has an **active** `integration_connections` row with `source='sumit'`, or a roster entry. Its SUMIT key must be its own, or the org id must be listed in `SUMIT_ENV_CREDENTIAL_ORG_IDS` (empty by default, which allows nobody).
- The weekly pull runs with `pull_expenses=False`. Expenses in the filing queue don't come through that path.

To confirm on prod (read-only):
1. `SELECT id, organization_id, status, config FROM integration_connections WHERE source='sumit';` shows whether this org has an active row. The SUMIT company id and key are in the encrypted `credentials_encrypted`, so checking that it is the expected company needs an admin decrypt.
2. `SELECT entity_type, last_success_at, cooldown_until FROM sync_checkpoints WHERE source='sumit' AND organization_id=<org>;`. No row means it never ran.
3. `SUMIT_ENV_CREDENTIAL_ORG_IDS` and `SUMIT_WEEKLY_PULL_ENABLED` in Vercel env.

Fix after GO (owner only, cost-gated):
- One manual SUMIT sync for this org. The code estimates **12 calls per org** (`SUMIT_WEEKLY_PULL_CALLS_PER_ORG`), against the test-track quota of 100/400 a month. Check `assert_paid_action_within_quota` and a fresh quota reading first. If the org uses env credentials, add its id to `SUMIT_ENV_CREDENTIAL_ORG_IDS`.

## What to avoid in the demo

- **Both demo orgs' bank feeds are stale until (12) is fixed.** /cashflow will then show today's opening, closing and headroom as חסר in every week. That is correct, and the opening card shows the last booked balance with its date. Explain it as "no invented numbers", or run the GO steps above before 08:00.

- /forecasting (open-documents view only). Use /cashflow.
- The new bank-match screen (PR #103), unless it gets a GO.
- The "הפק" button on the documents screen (round-1 item 7 is still open).

## Verification

- Touched-area tests: all new and updated BDO tests pass (`test_bdo_*`, `test_live_forecast_service`, `test_kpi_insights_bank_report`, `test_dashboard_fees`, `test_open_finance_routes`, dashboard/runway tests).
- Frontend: `npx tsc --noEmit` clean, `eslint` clean on touched files, `npm run build` OK.
- Full `pytest tests/`: see the PR comment for head vs main (e961c65). Failures that main also has are listed there as pre-existing.
- Known pre-existing failure: `test_live_forecast_service.py::test_monthly_forecast_overdue_ar_and_ap_are_not_dropped` (also fails on main).
- Nothing here has been checked against prod screens. Each item needs a logged-in look on a preview before the demo.
