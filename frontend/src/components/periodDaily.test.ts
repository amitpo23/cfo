import assert from 'node:assert/strict';
import { test } from 'node:test';
import { cumulativeRows, dailyChartRows, hasDailyBudget, pnlRange, periodQuery } from './periodDaily.ts';
import type { Figure, PeriodCompare, PeriodRow } from './PeriodCompare.tsx';

const figure = (amount: number | null): Figure => ({ amount, as_of: '2026-03-03', missing_label: amount == null ? 'חסר' : null });

function day(date: string, opts: {
  bankIn?: number | null; bankOut?: number | null; bankNet?: number | null;
  rev?: number | null; costs?: number | null; booksNet?: number | null;
  budgetNet?: number | null; elapsed?: boolean;
} = {}): PeriodRow {
  const v = (key: keyof typeof opts) => (key in opts ? (opts[key] as number | null) : null);
  return {
    label: date, start: date, end: date, elapsed: opts.elapsed ?? true,
    budget: { revenue: figure(null), costs: figure(null), net: figure(v('budgetNet')) },
    bank: { in: figure(v('bankIn')), out: figure(v('bankOut')), net: figure(v('bankNet')) },
    books: { revenue: figure(v('rev')), costs: figure(v('costs')), net: figure(v('booksNet')) },
    variance: { books_vs_budget: figure(null), bank_vs_budget: figure(null) },
  };
}

function report(periods: PeriodRow[], extra: Partial<PeriodCompare> = {}): PeriodCompare {
  return { grain: 'day', start: periods[0].start, end: periods[periods.length - 1].end, periods, ...extra };
}

test('one query: grain and dates are the key and the URL', () => {
  const a = periodQuery('day', '2026-03-01', '2026-03-05');
  const b = periodQuery('day', '2026-03-01', '2026-03-06');
  const c = periodQuery('week', '2026-03-01', '2026-03-05');
  assert.deepEqual(a.queryKey, ['cashflow-period', 'day', '2026-03-01', '2026-03-05']);
  assert.equal(a.url, '/cashflow/period?grain=day&start=2026-03-01&end=2026-03-05');
  assert.notDeepEqual(a.queryKey, b.queryKey);
  assert.notDeepEqual(a.queryKey, c.queryKey);
  assert.notEqual(a.url, c.url);
});

test('day grain on /pnl opens month-to-date, not a single bar', () => {
  const today = new Date(2026, 2, 17);
  assert.deepEqual(pnlRange('day', today), { start: '2026-03-01', end: '2026-03-17' });
  assert.deepEqual(pnlRange('month', today), { start: '2026-03-01', end: '2026-03-31' });
});

test('chart rows keep a missing figure as null, never 0', () => {
  const rows = dailyChartRows(report([
    day('2026-03-01', { bankIn: 100, bankOut: 40, rev: 80, costs: null }),
    day('2026-03-02'),
  ]));
  assert.equal(rows.length, 2);
  assert.deepEqual(rows[0], {
    date: '2026-03-01', label: '2026-03-01', elapsed: true,
    bankIn: 100, bankOut: 40, booksRevenue: 80, booksCosts: null, budgetNet: null,
  });
  for (const key of ['bankIn', 'bankOut', 'booksRevenue', 'booksCosts', 'budgetNet'] as const) {
    assert.equal(rows[1][key], null, key);
  }
});

test('budget series shows only when some day has a day-split budget', () => {
  assert.equal(hasDailyBudget(report([day('2026-03-01'), day('2026-03-02')])), false);
  assert.equal(hasDailyBudget(report([day('2026-03-01'), day('2026-03-02', { budgetNet: 10 })])), true);
});

test('cumulative matches server totals when no day is missing', () => {
  const r = report([
    day('2026-03-01', { bankIn: 100, bankOut: 40, bankNet: 60, rev: 80, costs: 30, booksNet: 50, budgetNet: 5 }),
    day('2026-03-02', { bankIn: 10.5, bankOut: 20, bankNet: -9.5, rev: 20, costs: 5, booksNet: 15, budgetNet: 5 }),
  ], {
    totals: {
      budget: { revenue: figure(null), costs: figure(null), net: figure(10) },
      books: { revenue: figure(100), costs: figure(35), net: figure(65) },
      bank: { in: figure(110.5), out: figure(60), net: figure(50.5) },
    },
  });
  const rows = cumulativeRows(r);
  const last = rows[rows.length - 1];
  assert.equal(last.bankIn.amount, r.totals!.bank.in.amount);
  assert.equal(last.bankOut.amount, r.totals!.bank.out.amount);
  assert.equal(last.bankNet.amount, r.totals!.bank.net.amount);
  assert.equal(last.booksRevenue.amount, r.totals!.books.revenue.amount);
  assert.equal(last.booksCosts.amount, r.totals!.books.costs.amount);
  assert.equal(last.booksNet.amount, r.totals!.books.net.amount);
  assert.equal(last.budgetNet.amount, r.totals!.budget.net.amount);
  assert.equal(rows[0].bankNet.amount, 60);
});

test('a missing elapsed day makes bank/books cumulative missing from that day on', () => {
  const rows = cumulativeRows(report([
    day('2026-03-01', { bankIn: 100, rev: 80 }),
    day('2026-03-02', { bankIn: null, rev: 20 }),
    day('2026-03-03', { bankIn: 50, rev: 10 }),
  ]));
  assert.equal(rows[0].bankIn.amount, 100);
  assert.equal(rows[1].bankIn.amount, null);
  assert.equal(rows[1].bankIn.missingSince, '2026-03-02');
  assert.equal(rows[2].bankIn.amount, null);
  assert.equal(rows[2].bankIn.missingSince, '2026-03-02');
  assert.equal(rows[2].booksRevenue.amount, 110);
});

test('budget cumulative skips days without a budget, like the server total', () => {
  const rows = cumulativeRows(report([
    day('2026-03-01', { budgetNet: 5 }),
    day('2026-03-02'),
    day('2026-03-03', { budgetNet: 7 }),
  ]));
  assert.equal(rows[0].budgetNet.amount, 5);
  assert.equal(rows[1].budgetNet.amount, 5);
  assert.equal(rows[2].budgetNet.amount, 12);
  assert.equal(cumulativeRows(report([day('2026-03-01')]))[0].budgetNet.amount, null);
});

test('days that have not started are not counted and not missing', () => {
  const rows = cumulativeRows(report([
    day('2026-03-01', { bankIn: 100 }),
    day('2026-03-02', { elapsed: false }),
  ]));
  assert.equal(rows[1].bankIn.amount, null);
  assert.equal(rows[1].bankIn.notStarted, true);
  assert.equal(rows[1].bankIn.missingSince, undefined);
});

test('withheld net stays withheld; it is not rebuilt from in minus out', () => {
  const rows = cumulativeRows(report([
    day('2026-03-01', { bankIn: 100, bankOut: 40, bankNet: null, rev: 80, costs: 30, booksNet: null }),
  ], { profit_claim: { allowed: false, reason_he: 'יש הוצאות לא מסווגות' } }));
  assert.equal(rows[0].bankIn.amount, 100);
  assert.equal(rows[0].bankNet.amount, null);
  assert.equal(rows[0].booksNet.amount, null);
});
