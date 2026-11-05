# Simplify E — Daily P&L UI

Branch `feat/simplify-e-daily-pnl-ui`, base `e961c65` (#102). Code commit `61489f3`.

## What changed (frontend only — no backend, no migration)
- `frontend/src/components/periodDaily.ts` — pure helpers:
  - `periodQuery(grain, start, end)` → the one `queryKey` + URL for `/cashflow/period`.
  - `pnlRange(grain)` → /pnl ranges; **day opens month-to-date** (the shared `presetRange('day')` = today only, one bar). Shared `presetRange` untouched (/budget, cashflow, /d/ unchanged).
  - `dailyChartRows(report)` → income/expense per bucket for books and bank; null stays null.
  - `hasDailyBudget(report)` → budget line only when the server returned a day-split budget.
  - `cumulativeRows(report)` → running totals using the server `_totals` rules: only elapsed buckets count; bank/books become חסר from the first missing elapsed bucket (`gap_is_missing=True`); budget skips buckets without a budget (`gap_is_missing=False`); withheld net (`profit_claim.allowed=false`) stays withheld, never rebuilt from in−out.
- `frontend/src/components/DailyPnl.tsx` — `PnlChart` (Recharts bars: income vs expense, toggle ספרים / בנק BOOKED, optional budget line, tooltip shows חסר for null, RTL date order) and `CumulativeTable`.
- `frontend/src/components/PnlPage.tsx` — default grain `day`; chart + cumulative + existing `PeriodCompareTable` all read the same `report.data` from one `useQuery`.

## Verification (local; GitHub CI is billing-blocked)
- `node --test src/**/*.test.ts src/*.test.ts` → 32 pass, 0 fail (9 new in `periodDaily.test.ts`: query key/URL changes with filter; month-to-date day range; null≠0 in chart rows; budget only when day-split; last cumulative == server totals when nothing missing; missing day stops bank/books cumulative; budget skips gaps; not-started days neither counted nor missing; withheld net stays null).
- `npx tsc --noEmit` clean; `npm run lint` (max-warnings 0) clean; `npm run build` OK.
- No `?? 0` / `|| 0` in the changed files.
- No screenshot (needs an authenticated org; not run against prod).

## Remaining gaps / owner decisions
1. **Day with no bank movement = missing, not 0.** That's the backend rule from A (`_bank_bucket` returns null when no BOOKED rows; totals use `gap_is_missing=True`). On day grain the bank cumulative will usually show "חסר מ-<first quiet day>" and the server total for bank will be null. Whether a quiet day *inside a synced range* should count as 0 is an owner decision for the money math — deliberately not changed here.
2. Same for books: a day with no filed documents makes books cumulative חסר from that day.
3. Chart is shown for every grain (bars per bucket); the 100-line cap on bank day lines is unchanged.
4. Visual QA in a real org still pending.
