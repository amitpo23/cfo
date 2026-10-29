import assert from 'node:assert/strict';
import { test } from 'node:test';
import { sumPeriodBankTotals } from './periodBankTotals.ts';
import type { PeriodCompare, PeriodRow } from './PeriodCompare.tsx';

function row(bank: { in: number | null; out: number | null; net: number | null }): PeriodRow {
  const figure = (amount: number | null) => ({
    amount,
    missing_label: amount == null ? 'חסר' : null,
  });
  return {
    label: 'יום',
    start: '2026-10-29',
    end: '2026-10-29',
    budget: { revenue: figure(null), costs: figure(null), net: figure(null) },
    bank: { in: figure(bank.in), out: figure(bank.out), net: figure(bank.net) },
    books: { revenue: figure(null), costs: figure(null), net: figure(null) },
    variance: { books_vs_budget: figure(null), bank_vs_budget: figure(null) },
  };
}

function report(periods: PeriodRow[]): PeriodCompare {
  return { grain: 'day', start: '2026-10-29', end: '2026-10-29', periods };
}

test('selected days sum bank inflows, outflows and net', () => {
  const totals = sumPeriodBankTotals(report([
    row({ in: 100, out: 40, net: 60 }),
    row({ in: 0, out: 15.5, net: -15.5 }),
  ]));
  assert.deepEqual(totals, { inflows: 100, outflows: 55.5, net: 44.5 });
});

test('a day with no booked movement stays a real zero', () => {
  assert.deepEqual(sumPeriodBankTotals(report([row({ in: 0, out: 0, net: 0 })])), {
    inflows: 0,
    outflows: 0,
    net: 0,
  });
});

test('a missing figure stays missing and is not added as zero', () => {
  const totals = sumPeriodBankTotals(report([
    row({ in: 10, out: null, net: null }),
    row({ in: 5, out: 1, net: 4 }),
  ]));
  assert.equal(totals?.inflows, 15);
  assert.equal(totals?.outflows, null);
  assert.equal(totals?.net, null);
});

test('loading and an empty period payload are not a total', () => {
  assert.equal(sumPeriodBankTotals(null), null);
  assert.equal(sumPeriodBankTotals(undefined), null);
  assert.equal(sumPeriodBankTotals(report([])), null);
});
