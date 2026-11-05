# Simplify E — Daily P&L UI

Branch `feat/simplify-e-daily-pnl-ui`, base `e961c65` (#102). PR #106. Code commits `61489f3` + `67248a2`; HEAD = the commit that adds this file's final version (see `git log -1`).

## Owner decision first
The same date range gives **known totals at month grain and חסר at day grain.** A day with no BOOKED movement, or with no filed documents, is *missing* (backend rule from #102: `_bank_bucket`/`_books_bucket` return null, and `_totals` uses `gap_is_missing=True`). So on day grain the totals row and the cumulative table usually show "חסר מ-<early day>". Should a quiet day inside synced bank coverage (`partial_banner.bank_as_of`) count as 0? That is a money-math change in the backend and needs an owner GO. Not done here.

## What changed (frontend only — no backend, no migration)
- `frontend/src/components/periodDaily.ts` — pure helpers:
  - `periodQuery(grain, start, end)` → the one `queryKey` + URL for `/cashflow/period`.
  - `pnlRange(grain)` → /pnl ranges; **day opens month-to-date** (the shared `presetRange('day')` = today only, one bar). Shared `presetRange` untouched (/budget, cashflow, /d/ unchanged).
  - `dailyChartRows(report)` → income/expense per bucket for books and bank; null stays null.
  - `hasDailyBudget(report)` → budget line only when the server returned a day-split budget.
  - `cumulativeRows(report)` → running totals using the server `_totals` rules: only elapsed buckets count; bank/books become חסר from the first missing elapsed bucket (`gap_is_missing=True`); budget skips buckets without a budget (`gap_is_missing=False`); withheld net (`profit_claim.allowed=false`) stays withheld, never rebuilt from in−out.
- `frontend/src/components/DailyPnl.tsx` — `PnlChart` (Recharts bars: income vs expense, toggle ספרים / בנק BOOKED, optional budget line, tooltip shows חסר for null (`filterNull={false}`; Recharts drops nulls by default), RTL date order) and `CumulativeTable`.
- `frontend/src/components/PnlPage.tsx` — lands on `month` (see owner decision); "יום" is one click and opens month-to-date; chart + cumulative + existing `PeriodCompareTable` all read the same `report.data` from one `useQuery`.

## Verification (local; GitHub CI is billing-blocked)
- `node --test src/**/*.test.ts src/*.test.ts` → 32 pass, 0 fail (9 new in `periodDaily.test.ts`: query key/URL changes with filter; month-to-date day range; null≠0 in chart rows; budget only when day-split; last cumulative == totals on a hand-written fixture (mirrors `_totals` rules; not a test against the Python `_totals` itself); missing day stops bank/books cumulative; budget skips gaps; not-started days neither counted nor missing; withheld net stays null).
- `npx tsc --noEmit` clean; `npm run lint` (max-warnings 0) clean; `npm run build` OK.
- No `?? 0` / `|| 0` in the changed files.
- No screenshot (needs an authenticated org; not run against prod).

## Remaining gaps / owner decisions
1. The owner decision above (quiet day = 0 or missing). Until then day-grain cumulative is mostly חסר on real data.
2. `books.net` per day is null when the day has revenue but no costs (or the reverse), the same rule.
3. Chart is shown for every grain (bars per bucket); the 100-line cap on bank day lines is unchanged.
4. Visual QA in a real org still pending.
