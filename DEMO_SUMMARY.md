# BDO demo P0s: status

Branch `feat/bdo-demo-p0`, draft PR #104. Not merged, no prod migration, no writes to prod, no SUMIT or Financy calls.
This file contains no client figures. Every test uses made-up amounts.

## Round 1 (spec of 04.11)

| # | P0 | Status | Where |
|---|---|---|---|
| 1 | One October P&L on every screen | **Done** for dashboard, /dashboard/pnl, /daily-reports, /pnl, /budget: all of them read `period_compare.books_months` (/cashflow/period books). Bill/Expense twins count once. A profit that /pnl withholds is withheld everywhere. | c7c13b7, `tests/test_bdo_one_pnl_source.py` |
| 2 | "Bank until · books until" banner | **Done** on dashboard, /cashflow and /forecasting (`org_partial_banner`). A missing stamp shows חסר. | 9c1de16, `tests/test_live_forecast_service.py` |
| 3 | Balance / limit / used / available / overrun | **Done** on dashboard and /cashflow (`credit_lines`, last booked balance). A stale balance keeps its amount and shows its date. Overrun is red. | e8adbd8, 9c1de16, `tests/test_bdo_credit_lines.py` |
| 4 | 30-day forecast: outflows not 0, cheque discounting and loans are financing | **Done** on /cashflow and the dashboard: both read the 13-week forecast (loans, payroll, cards, VAT, run-rate). An unknown side is חסר. | 49819a1, 9c1de16, `tests/test_bdo_cashflow_one_forecast.py` |
| 8 | Hide EXPIRED OF connections | **Done.** Expired consents with no accounts are hidden from status, from the list and from the provider count. | 04d4d1f, `tests/test_open_finance_routes.py` |
| 5 | Budget placeholder shows חסר | Not touched in this branch (`budget_fill` placeholder_warning already exists on main). Needs a visual check. | — |
| 6 | PR #103 bank match | Out of scope. Handled on its own branch. | — |
| 7 | Document issue = preview only | **Left.** | — |
| 9 | /d/eliav share link | **Left.** Needs a logged-in owner. | — |

## Round 2 (CFO prod walkthrough)

| # | Finding | Status |
|---|---|---|
| 1 | Bank report margin ×100 too high, net profit with 3 decimals | Left |
| 2 | Executive and bank report profit differ from /pnl | Left |
| 3 | /cashflow and /forecasting disagree | Partly: /cashflow is on the 13-week forecast; /forecasting is still on `LiveForecastService` |
| 4 | Checking balance missing or 0 while diagnostics show an overdrawn stale balance | Partly: dashboard and /cashflow done; executive and bank report left |
| 5 | Budget variance 100% when actual = 0 | Left |
| 6 | Executive loads in ~10s | Left |
| 7 | One org's books empty: its SUMIT sync never ran | Left (diagnosis only) |
| 8 | Executive and bank report show 0 instead of חסר | Left |
| 9 | Loans tile mixed with the credit line | Left |
| 10 | /cashflow opening, closing and net 0 in weeks with inflows | Left |
| 11 | Command Center bank 0/0 for the current month | Left |
| 12 | Prod bank data a week behind Financy | Left (diagnosis only) |

## Pre-existing failures

`tests/test_live_forecast_service.py::test_monthly_forecast_overdue_ar_and_ap_are_not_dropped` also fails on main (e961c65).
